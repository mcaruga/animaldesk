"""Dalla foto dell'animale alla pelle animata, in automatico.

    python -m animaldesk.tools.auto_skin foto.jpg --nome fido

Passi:
1. un modello di visione (Claude) guarda la foto e restituisce, come JSON
   validato da schema, il riquadro testa+petto e i punti del viso (occhi, naso,
   bocca, cima della testa, collo, orecchie);
2. lo sfondo viene tolto (GrabCut guidato da quei punti + alpha matting sul pelo);
3. i punti vengono rifiniti sui pixel (centro reale di occhi e naso);
4. si scrive sprite.png + rig.json.

Tutte le azioni (seduto, dormi, nascondino, testa di lato, linguetta, ...) sono
guidate dal rig, quindi funzionano subito sul nuovo animale senza altro lavoro.
Senza chiave API si usa una stima dai pixel (meno affidabile): la finestra
"Nuovo cane da foto" lascia correggere i punti a mano.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
from pathlib import Path

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"

_POINT = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
          "required": ["x", "y"], "additionalProperties": False}
_EAR = {"type": "object",
        "properties": {"base": _POINT, "tip": _POINT},
        "required": ["base", "tip"], "additionalProperties": False}

SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "problem": {"type": "string"},
        "species": {"type": "string"},
        "bust": {"type": "object",
                 "properties": {k: {"type": "number"} for k in ("x0", "y0", "x1", "y1")},
                 "required": ["x0", "y0", "x1", "y1"], "additionalProperties": False},
        "eye_left": _POINT, "eye_right": _POINT, "nose": _POINT, "mouth": _POINT,
        "head_top": _POINT, "neck": _POINT, "ear_left": _EAR, "ear_right": _EAR,
    },
    "required": ["usable", "problem", "species", "bust", "eye_left", "eye_right", "nose",
                 "mouth", "head_top", "neck", "ear_left", "ear_right"],
    "additionalProperties": False,
}

PROMPT = """This photo will become an animated desktop pet: the animal's head and chest are cut \
out of the photo and rigged so the head can turn, tilt and blink. I need the positions of the \
facial landmarks so the rig lines up with this specific animal.

Return coordinates normalized to the image: x from 0 (left edge) to 1 (right edge), y from 0 \
(top edge) to 1 (bottom edge). "Left" and "right" mean left and right in the image, not the \
animal's own left and right.

- bust: the box around the head, both ears and the neck/upper chest of the main animal. Leave a \
small margin so no fur is clipped. If the chest runs out of the frame, let the box touch that edge.
- eye_left, eye_right: the centre of each eye (the pupil).
- nose: the centre of the nose leather.
- mouth: the point on the lip line directly below the nose, where a tongue would come out.
- head_top: the highest point of the skull between the ears.
- neck: where the head meets the neck, on the animal's midline, just below the chin.
- ear_left, ear_right: base is where the ear attaches to the skull, tip is the far end of the ear.

Set usable to false, and say why in problem, when the rig cannot work: no animal, the face is \
turned away or mostly hidden, an eye is covered, or the head is cut off by the frame. Otherwise \
set usable to true and leave problem empty. If there are several animals, use the most prominent one."""


# ----------------------------------------------------------------- visione AI
def analyze_photo(image_bgr, client=None) -> dict | None:
    """Chiede a Claude riquadro e punti del viso. None se non disponibile o rifiutato."""
    import cv2

    try:
        import anthropic
    except ImportError:
        return None
    h, w = image_bgr.shape[:2]
    s = min(1.0, 1568 / max(h, w))
    small = cv2.resize(image_bgr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else image_bgr
    ok, jpg = cv2.imencode(".jpg", small, [cv2.IMWRITE_JPEG_QUALITY, 90])
    if not ok:
        return None
    data = base64.standard_b64encode(jpg.tobytes()).decode("ascii")

    try:
        client = client or anthropic.Anthropic()
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=4000,
            betas=[FALLBACK_BETA],
            fallbacks="default",                 # se il modello declina, risponde quello di riserva
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/jpeg", "data": data}},
                {"type": "text", "text": PROMPT},
            ]}],
        )
    except anthropic.AuthenticationError:
        return None                               # nessuna credenziale valida: stima dai pixel
    except anthropic.RateLimitError:
        return None
    except anthropic.APIStatusError as exc:
        if exc.status_code >= 500:
            return None
        raise
    except anthropic.APIConnectionError:
        return None
    except (TypeError, anthropic.AnthropicError):
        return None                               # credenziali assenti nell'ambiente

    if response.stop_reason in ("refusal", "max_tokens"):
        return None
    text = next((b.text for b in response.content if b.type == "text"), "")
    try:
        return json.loads(text)
    except ValueError:
        return None


# ------------------------------------------------------------------- ritaglio
def _matte(img, hard):
    """Alpha a livello del pelo (pymatting) o, se manca, una sfumatura semplice."""
    import cv2
    import numpy as np

    h, w = hard.shape
    side = max(h, w)
    try:
        from pymatting import estimate_alpha_cf, estimate_foreground_ml
    except ImportError:
        return img, cv2.GaussianBlur(hard, (0, 0), side * 0.004).astype(np.float32) / 255
    k_in, k_out = max(3, int(side * 0.010)), max(5, int(side * 0.026))
    fg = cv2.erode(hard, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_in * 2 + 1,) * 2))
    bg = cv2.dilate(hard, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k_out * 2 + 1,) * 2))
    trimap = np.full((h, w), 0.5)
    trimap[fg > 0] = 1.0
    trimap[bg == 0] = 0.0
    rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float64) / 255
    alpha = np.clip(estimate_alpha_cf(rgb, trimap), 0, 1)
    alpha[alpha < 0.02] = 0
    keep = cv2.dilate((alpha > 0.12).astype(np.uint8), np.ones((9, 9), np.uint8))
    n, lab, stats, _ = cv2.connectedComponentsWithStats(keep, 8)
    if n > 2:
        alpha[lab != 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA])] = 0
    fgc = np.clip(estimate_foreground_ml(rgb, alpha), 0, 1)
    return (fgc[:, :, ::-1] * 255).astype(np.uint8), alpha.astype(np.float32)


def cutout(img, seeds: list[tuple[float, float]] | None = None, side: int = 1300):
    """Toglie lo sfondo. `seeds` = punti (0..1) sicuramente sull'animale (occhi, naso...)."""
    import cv2
    import numpy as np

    s = side / max(img.shape[:2])
    if s < 1:
        img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    mask[int(h * 0.04):, int(w * 0.04):int(w * 0.96)] = cv2.GC_PR_FGD
    if seeds:
        pts = np.array([(int(x * w), int(y * h)) for x, y in seeds], np.int32)
        hull = cv2.convexHull(pts)
        cv2.fillConvexPoly(mask, hull, cv2.GC_FGD)
        for x, y in pts:
            cv2.circle(mask, (int(x), int(y)), int(side * 0.035), cv2.GC_FGD, -1)
    else:
        mask[int(h * 0.30):int(h * 0.92), int(w * 0.32):int(w * 0.68)] = cv2.GC_FGD
    mask[:max(2, int(h * 0.02)), :] = cv2.GC_BGD
    bgd, fgd = np.zeros((1, 65)), np.zeros((1, 65))
    cv2.grabCut(img, mask, None, bgd, fgd, 8, cv2.GC_INIT_WITH_MASK)
    hard = np.where((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD), 255, 0).astype(np.uint8)
    n, lab, stats, _ = cv2.connectedComponentsWithStats(hard, 8)
    if n > 2:
        hard = np.where(lab == 1 + np.argmax(stats[1:, cv2.CC_STAT_AREA]), 255, 0).astype(np.uint8)
    hard = cv2.morphologyEx(hard, cv2.MORPH_CLOSE, np.ones((17, 17), np.uint8))
    rgb, alpha = _matte(img, hard)

    # dove l'animale esce dall'inquadratura (lati, in basso) il taglio sfuma a ciocche
    rng = np.random.default_rng(11)
    streak = cv2.resize(rng.random((h // 60 + 2, w // 14 + 2)).astype(np.float32), (w, h),
                        interpolation=cv2.INTER_CUBIC)
    streak = cv2.GaussianBlur(streak, (0, 0), 3)
    u = np.linspace(0, 1, w, dtype=np.float32)[None, :].repeat(h, 0)
    v = np.linspace(0, 1, h, dtype=np.float32)[:, None].repeat(w, 1)

    def ramp(d, width):
        t = np.clip(d / width + (streak - 0.5) * 0.35, 0, 1)
        return t * t * (3 - 2 * t)

    if (alpha[:, :3] > 0.5).mean() > 0.04:
        alpha *= 1 - np.clip((v - 0.45) / 0.12, 0, 1) * (1 - ramp(u, 0.10))
    if (alpha[:, -3:] > 0.5).mean() > 0.04:
        alpha *= 1 - np.clip((v - 0.45) / 0.12, 0, 1) * (1 - ramp(1 - u, 0.10))

    ys, xs = np.where(alpha > 0.03)
    if len(xs) == 0:
        raise ValueError("non riesco a separare l'animale dallo sfondo")
    x0, x1, y0, y1 = xs.min(), xs.max() + 1, ys.min(), ys.max() + 1
    rgba = np.dstack([rgb, (np.clip(alpha, 0, 1) * 255).astype(np.uint8)])[y0:y1, x0:x1]
    return rgba, (x0 / w, y0 / h, x1 / w, y1 / h)      # sprite + riquadro usato (0..1 del ritaglio)


# ------------------------------------------------------------- punti del viso
def _dark_blob(sprite, cx: float, cy: float, radius: float):
    """Centro e mezzo-assi della macchia scura piu' vicina a (cx, cy): occhio o naso veri."""
    import cv2
    import numpy as np

    h, w = sprite.shape[:2]
    r = int(radius * w)
    x0, x1 = max(0, int(cx * w) - r), min(w, int(cx * w) + r)
    y0, y1 = max(0, int(cy * h) - r), min(h, int(cy * h) + r)
    if x1 - x0 < 6 or y1 - y0 < 6:
        return None
    patch = cv2.cvtColor(sprite[y0:y1, x0:x1, :3], cv2.COLOR_BGR2GRAY)
    patch = cv2.GaussianBlur(patch, (0, 0), max(1.0, r * 0.05))
    lo, hi = float(np.percentile(patch, 4)), float(np.percentile(patch, 70))
    if hi - lo < 28:                       # poco contrasto (es. occhi scuri su pelo nero)
        return None
    dark = (patch < lo + (hi - lo) * 0.33).astype(np.uint8)
    n, lab, stats, cent = cv2.connectedComponentsWithStats(dark, 8)
    best, best_d = None, 1e9
    for k in range(1, n):
        if stats[k, cv2.CC_STAT_AREA] < r * r * 0.012:
            continue
        d = math.hypot(cent[k][0] - (cx * w - x0), cent[k][1] - (cy * h - y0))
        if d < best_d:
            best, best_d = k, d
    if best is None or best_d > r * 0.8:
        return None
    return ((x0 + cent[best][0]) / w, (y0 + cent[best][1]) / h,
            stats[best, cv2.CC_STAT_WIDTH] / 2 / w, stats[best, cv2.CC_STAT_HEIGHT] / 2 / h)


def guess_landmarks(sprite) -> dict | None:
    """Senza AI: le tre macchie scure e compatte del muso (due occhi sopra, naso sotto)."""
    import cv2
    import numpy as np

    h, w = sprite.shape[:2]
    gray = cv2.GaussianBlur(cv2.cvtColor(sprite[:, :, :3], cv2.COLOR_BGR2GRAY), (0, 0), w * 0.006)
    inside = cv2.erode((sprite[:, :, 3] > 200).astype(np.uint8), np.ones((int(w * 0.05) | 1,) * 2, np.uint8))
    vals = gray[inside > 0]
    if vals.size < 100:
        return None
    dark = ((gray < np.percentile(vals, 6)) & (inside > 0)).astype(np.uint8)
    dark[int(h * 0.80):] = 0
    n, lab, stats, cent = cv2.connectedComponentsWithStats(dark, 8)
    blobs = []
    for k in range(1, n):
        area, bw, bh = stats[k, cv2.CC_STAT_AREA], stats[k, cv2.CC_STAT_WIDTH], stats[k, cv2.CC_STAT_HEIGHT]
        if area < w * h * 0.0006 or area / float(bw * bh) < 0.42 or max(bw, bh) > 3.2 * min(bw, bh):
            continue
        blobs.append((area, cent[k][0] / w, cent[k][1] / h))
    blobs.sort(reverse=True)
    blobs = blobs[:5]
    if len(blobs) < 3:
        return None
    nose = max(blobs, key=lambda b: b[0])
    eyes = sorted((b for b in blobs if b is not nose and b[2] < nose[2] - 0.04), key=lambda b: -b[0])[:2]
    if len(eyes) < 2:
        return None
    eyes.sort(key=lambda b: b[1])
    e = math.hypot((eyes[1][1] - eyes[0][1]) * w, (eyes[1][2] - eyes[0][2]) * h)
    mid = ((eyes[0][1] + eyes[1][1]) / 2, (eyes[0][2] + eyes[1][2]) / 2)
    return {
        "eye_left": {"x": eyes[0][1], "y": eyes[0][2]}, "eye_right": {"x": eyes[1][1], "y": eyes[1][2]},
        "nose": {"x": nose[1], "y": nose[2]},
        "mouth": {"x": nose[1], "y": min(0.98, nose[2] + 0.55 * e / h)},
        "head_top": {"x": mid[0], "y": max(0.0, mid[1] - 0.85 * e / h)},
        "neck": {"x": mid[0], "y": min(0.97, nose[2] + 1.05 * e / h)},
        "ear_left": {"base": {"x": eyes[0][1] - 0.45 * e / w, "y": eyes[0][2] - 0.25 * e / h},
                     "tip": {"x": eyes[0][1] - 0.85 * e / w, "y": eyes[0][2] + 0.75 * e / h}},
        "ear_right": {"base": {"x": eyes[1][1] + 0.45 * e / w, "y": eyes[1][2] - 0.25 * e / h},
                      "tip": {"x": eyes[1][1] + 0.85 * e / w, "y": eyes[1][2] + 0.75 * e / h}},
    }


def make_rig(sprite, marks: dict, name: str, has_paw: bool = False) -> dict:
    """Punti (gia' in coordinate dello sprite) → rig.json, rifiniti sui pixel."""
    h, w = sprite.shape[:2]
    clamp = lambda v: max(0.0, min(1.0, float(v)))      # noqa: E731
    pt = lambda key: (clamp(marks[key]["x"]), clamp(marks[key]["y"]))   # noqa: E731
    (lx, ly), (rx_, ry_) = pt("eye_left"), pt("eye_right")
    if lx > rx_:
        (lx, ly), (rx_, ry_) = (rx_, ry_), (lx, ly)
    e_px = math.hypot((rx_ - lx) * w, (ry_ - ly) * h)
    angle = math.degrees(math.atan2((ry_ - ly) * h, (rx_ - lx) * w))
    eyes = []
    for ex, ey in ((lx, ly), (rx_, ry_)):
        blob = _dark_blob(sprite, ex, ey, 0.22 * e_px / w)
        if blob:
            ex, ey = blob[0], blob[1]
            erx = max(0.10 * e_px / w, min(0.17 * e_px / w, blob[2] * 1.12))
            ery = max(0.075 * e_px / h, min(0.12 * e_px / h, blob[3] * 1.15))
        else:
            erx, ery = 0.125 * e_px / w, 0.088 * e_px / h
        eyes.append({"x": round(ex, 4), "y": round(ey, 4), "rx": round(erx, 4), "ry": round(ery, 4),
                     "angle": round(angle, 1)})
    nx, ny = pt("nose")
    blob = _dark_blob(sprite, nx, ny, 0.30 * e_px / w)
    if blob:
        nx, ny = blob[0], blob[1]

    def ear(key):
        base, tip = marks[key]["base"], marks[key]["tip"]
        bx, by, tx, ty = clamp(base["x"]), clamp(base["y"]), clamp(tip["x"]), clamp(tip["y"])
        return [round(bx * 0.35 + tx * 0.65, 4), round(by * 0.35 + ty * 0.65, 4), round(bx, 4), round(by, 4)]

    ears = sorted((ear("ear_left"), ear("ear_right")), key=lambda a: a[2])
    rig = {
        "name": name, "sprite": "sprite.png",
        "eyes": eyes,
        "nose": [round(nx, 4), round(ny, 4)],
        "mouth": [round(v, 4) for v in pt("mouth")],
        "head_top": [round(v, 4) for v in pt("head_top")],
        "neck": [round(v, 4) for v in pt("neck")],
        "ear_l": ears[0], "ear_r": ears[1],
        "feet": 1.03, "tongue": "#D8748A",
    }
    if has_paw:
        rig["paw"] = "paw.png"
    return rig


# ------------------------------------------------------------------- pipeline
def build_skin(photo: Path, name: str, out_root: Path, use_ai: bool = True, client=None,
               analysis: dict | None = None) -> dict:
    """Foto → cartella pelle. Ritorna un rapporto (metodo usato, avvisi)."""
    import cv2

    img = cv2.imread(str(photo))
    if img is None:
        raise ValueError(f"non riesco a leggere {photo}")
    H, W = img.shape[:2]
    report = {"name": name, "method": "pixel", "warnings": []}

    if analysis is None and use_ai:
        analysis = analyze_photo(img, client)
    if analysis is not None and not analysis.get("usable", True):
        raise ValueError(analysis.get("problem") or "foto non adatta")

    box = (0.0, 0.0, 1.0, 1.0)
    seeds = None
    if analysis is not None:
        report["method"] = "ai"
        report["species"] = analysis.get("species", "")
        b = analysis["bust"]
        mx, my = 0.04 * (b["x1"] - b["x0"]), 0.04 * (b["y1"] - b["y0"])
        box = (max(0.0, b["x0"] - mx), max(0.0, b["y0"] - my), min(1.0, b["x1"] + mx), min(1.0, b["y1"] + my))
    cx0, cy0, cx1, cy1 = box
    crop = img[int(cy0 * H):int(cy1 * H), int(cx0 * W):int(cx1 * W)]

    def to_crop(p):
        return ((p["x"] - cx0) / (cx1 - cx0), (p["y"] - cy0) / (cy1 - cy0))

    if analysis is not None:
        seeds = [to_crop(analysis[k]) for k in ("eye_left", "eye_right", "nose", "mouth", "neck")]
        seeds = [(min(0.98, max(0.02, x)), min(0.98, max(0.02, y))) for x, y in seeds]
    sprite, (sx0, sy0, sx1, sy1) = cutout(crop, seeds)

    if analysis is not None:
        def to_sprite(p):
            x, y = to_crop(p)
            return {"x": (x - sx0) / (sx1 - sx0), "y": (y - sy0) / (sy1 - sy0)}

        marks = {k: to_sprite(analysis[k]) for k in ("eye_left", "eye_right", "nose", "mouth", "head_top", "neck")}
        for k in ("ear_left", "ear_right"):
            marks[k] = {"base": to_sprite(analysis[k]["base"]), "tip": to_sprite(analysis[k]["tip"])}
    else:
        marks = guess_landmarks(sprite)
        if marks is None:
            report["warnings"].append("occhi e naso non trovati in automatico: indicali a mano")
            marks = {"eye_left": {"x": 0.38, "y": 0.30}, "eye_right": {"x": 0.62, "y": 0.30},
                     "nose": {"x": 0.5, "y": 0.5}, "mouth": {"x": 0.5, "y": 0.62},
                     "head_top": {"x": 0.5, "y": 0.03}, "neck": {"x": 0.5, "y": 0.78},
                     "ear_left": {"base": {"x": 0.25, "y": 0.2}, "tip": {"x": 0.14, "y": 0.5}},
                     "ear_right": {"base": {"x": 0.75, "y": 0.2}, "tip": {"x": 0.86, "y": 0.5}}}
            report["method"] = "manuale"

    s = 1000 / sprite.shape[0]
    sprite = cv2.resize(sprite, (max(1, int(sprite.shape[1] * s)), 1000), interpolation=cv2.INTER_AREA)
    folder = out_root / name
    folder.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(folder / "sprite.png"), sprite, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    rig = make_rig(sprite, marks, name, has_paw=(folder / "paw.png").exists())
    (folder / "rig.json").write_text(json.dumps(rig, indent=2), encoding="utf-8")
    report.update(folder=str(folder), size=[sprite.shape[1], sprite.shape[0]], rig=rig)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Crea in automatico una pelle animata da una foto")
    ap.add_argument("foto", type=Path)
    ap.add_argument("--nome", default="mio-animale")
    ap.add_argument("--out", type=Path, default=None, help="cartella skins (default: quella utente)")
    ap.add_argument("--senza-ai", action="store_true", help="non chiamare il modello di visione")
    args = ap.parse_args(argv)
    from ..config import config_dir

    out = args.out or (config_dir() / "skins")
    try:
        rep = build_skin(args.foto, args.nome, out, use_ai=not args.senza_ai)
    except ValueError as exc:
        print(f"non riuscito: {exc}")
        return 1
    print(f"pelle creata: {rep['folder']}  ({rep['size'][0]}x{rep['size'][1]}, metodo: {rep['method']})")
    for wmsg in rep["warnings"]:
        print("  attenzione:", wmsg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
