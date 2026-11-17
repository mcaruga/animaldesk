"""Dalle foto dell'animale (cane, gatto...) alla pelle animata, in automatico.

    python -m animaldesk.tools.auto_skin seduto.jpg muso.jpg spalle.jpg --nome fido

Per ogni foto:
1. un modello di visione (Claude) la guarda e restituisce, come JSON validato da
   schema: specie, tipo di inquadratura (primo piano, figura intera di fronte,
   di spalle), espressione, riquadri di testa+petto e dell'intero animale, punti
   del viso (occhi, naso, bocca, cima della testa, collo, orecchie);
2. lo sfondo viene tolto (GrabCut guidato da quei punti + alpha matting sul pelo);
3. i punti vengono rifiniti sui pixel (centro reale di occhi e naso);
4. la foto diventa una "vista" della pelle: busto, seduto, serio, dietro.

Tutte le azioni sono guidate dal rig, quindi funzionano subito sul nuovo animale:
quelle da primo piano usano "busto", "non ho voglia" usa "serio", "me ne vado"
usa "dietro". Se una vista manca l'azione ripiega su quella piu' vicina; da una
sola foto a figura intera si ricava anche il primo piano. Senza chiave API si
usa una stima dai pixel (meno affidabile): la finestra "Nuovo animale da foto"
lascia correggere i punti a mano.
"""

from __future__ import annotations

import argparse
import base64
import json
import math
from pathlib import Path

MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
FULL_HEIGHT = 1.62         # altezza della figura intera rispetto alla taglia del primo piano
SPECIES = {"dog": "cane", "cat": "gatto", "cane": "cane", "gatto": "gatto"}
FACE_KEYS = ("eye_left", "eye_right", "nose", "mouth", "head_top", "neck")

_POINT = {"type": "object", "properties": {"x": {"type": "number"}, "y": {"type": "number"}},
          "required": ["x", "y"], "additionalProperties": False}
_EAR = {"type": "object",
        "properties": {"base": _POINT, "tip": _POINT},
        "required": ["base", "tip"], "additionalProperties": False}

_BOX = {"type": "object",
        "properties": {k: {"type": "number"} for k in ("x0", "y0", "x1", "y1")},
        "required": ["x0", "y0", "x1", "y1"], "additionalProperties": False}

SCHEMA = {
    "type": "object",
    "properties": {
        "usable": {"type": "boolean"},
        "problem": {"type": "string"},
        "species": {"type": "string", "enum": ["dog", "cat", "other"]},
        "framing": {"type": "string", "enum": ["closeup", "full_front", "full_back"]},
        "mood": {"type": "string", "enum": ["happy", "neutral", "serious"]},
        "mouth_open": {"type": "boolean"},
        "bust": _BOX, "body": _BOX,
        "eye_left": _POINT, "eye_right": _POINT, "nose": _POINT, "mouth": _POINT,
        "head_top": _POINT, "neck": _POINT, "ear_left": _EAR, "ear_right": _EAR,
    },
    "required": ["usable", "problem", "species", "framing", "mood", "mouth_open", "bust", "body",
                 "eye_left", "eye_right", "nose", "mouth", "head_top", "neck", "ear_left", "ear_right"],
    "additionalProperties": False,
}

PROMPT = """This photo will become one view of an animated desktop pet: the animal is cut out of \
the photo and rigged so the head can turn, tilt and blink. I need to know what kind of view this \
photo is and where the facial landmarks are, so the rig lines up with this specific animal.

Return coordinates normalized to the image: x from 0 (left edge) to 1 (right edge), y from 0 \
(top edge) to 1 (bottom edge). "Left" and "right" mean left and right in the image, not the \
animal's own left and right. If there are several animals, use the most prominent one.

- species: dog, cat, or other.
- framing: "closeup" when the head and chest fill the photo and the legs are not all visible; \
"full_front" when the whole animal is visible, paws included, and it faces the camera (sitting, \
standing or lying); "full_back" when the whole animal is visible and seen from behind.
- mood: "happy" for an open, relaxed or smiling expression, "serious" for a closed mouth with a \
stern, bored or unimpressed look, "neutral" otherwise.
- mouth_open: true when the mouth is open in the photo, with the tongue or teeth showing.
- bust: the box around the head, both ears and the neck/upper chest. Leave a small margin so no \
fur is clipped. If the chest runs out of the frame, let the box touch that edge.
- body: the box around the entire animal, tail and paws included, with a small margin. For a \
closeup it is the same as bust.
- eye_left, eye_right: the centre of each eye (the pupil).
- nose: the centre of the nose leather.
- mouth: the point on the lip line directly below the nose, where a tongue would come out.
- head_top: the highest point of the skull between the ears.
- neck: where the head meets the neck, on the animal's midline, just below the chin.
- ear_left, ear_right: base is where the ear attaches to the skull, tip is the far end of the \
ear (the hanging end of a floppy ear, the point of an upright one).

For "full_back" there is no face: put eye_left and eye_right on the left and right sides of the \
skull at the height where the eyes would be, nose and mouth on the back of the head at the \
height they would be, and give head_top, neck and the ears as seen from behind.

Set usable to false, and say why in problem, when the rig cannot work: no animal; in a closeup \
or full_front view the face is turned away or mostly hidden, an eye is covered, or the head is \
cut off by the frame; in a full view the body is mostly hidden. Otherwise set usable to true \
and leave problem empty."""


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


def cutout(img, seeds: list[tuple[float, float]] | None = None, side: int = 1300, body: bool = False):
    """Toglie lo sfondo. `seeds` = punti (0..1) sicuramente sull'animale (occhi, naso...).

    `body` = figura intera: l'animale sta tutto nel riquadro, quindi i bordi sono
    sfondo e niente sfumatura "a ciocche" dove esce dall'inquadratura."""
    import cv2
    import numpy as np

    s = side / max(img.shape[:2])
    if s < 1:
        img = cv2.resize(img, (int(img.shape[1] * s), int(img.shape[0] * s)), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    mask = np.full((h, w), cv2.GC_PR_BGD, np.uint8)
    if body:
        # l'animale e' al centro del riquadro: la cornice attorno insegna com'e' fatto lo sfondo
        cv2.ellipse(mask, (w // 2, int(h * 0.52)), (int(w * 0.41), int(h * 0.46)), 0, 0, 360, cv2.GC_PR_FGD, -1)
        edge = max(2, int(min(h, w) * 0.02))
        mask[:edge, :] = mask[-edge:, :] = mask[:, :edge] = mask[:, -edge:] = cv2.GC_BGD
    else:
        mask[int(h * 0.07):, int(w * 0.07):int(w * 0.93)] = cv2.GC_PR_FGD
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

    if not body and (alpha[:, :3] > 0.5).mean() > 0.04:
        alpha *= 1 - np.clip((v - 0.45) / 0.12, 0, 1) * (1 - ramp(u, 0.10))
    if not body and (alpha[:, -3:] > 0.5).mean() > 0.04:
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


def make_rig(sprite, marks: dict, name: str, has_paw: bool = False, refine: bool = True) -> dict:
    """Punti (gia' in coordinate dello sprite) → rig.json, rifiniti sui pixel.

    `refine=False` per le viste senza viso (di spalle): non c'e' un occhio da cercare."""
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
        blob = _dark_blob(sprite, ex, ey, 0.22 * e_px / w) if refine else None
        if blob:
            ex, ey = blob[0], blob[1]
            erx = max(0.10 * e_px / w, min(0.17 * e_px / w, blob[2] * 1.12))
            ery = max(0.075 * e_px / h, min(0.12 * e_px / h, blob[3] * 1.15))
        else:
            erx, ery = 0.125 * e_px / w, 0.088 * e_px / h
        eyes.append({"x": round(ex, 4), "y": round(ey, 4), "rx": round(erx, 4), "ry": round(ery, 4),
                     "angle": round(angle, 1)})
    nx, ny = pt("nose")
    blob = _dark_blob(sprite, nx, ny, 0.30 * e_px / w) if refine else None
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


def _center_on(sprite, marks: dict, key: str = "neck"):
    """Allarga lo sprite con bordo trasparente finche' il collo sta al centro: cosi'
    tutte le viste girano attorno allo stesso asse e si sovrappongono bene."""
    import cv2

    h, w = sprite.shape[:2]
    cx = int(max(0.05, min(0.95, marks[key]["x"])) * w)
    pad_l, pad_r = max(0, (w - cx) - cx), max(0, cx - (w - cx))
    if pad_l == pad_r == 0:
        return sprite, marks
    sprite = cv2.copyMakeBorder(sprite, 0, 0, pad_l, pad_r, cv2.BORDER_CONSTANT, value=(0, 0, 0, 0))
    nw = w + pad_l + pad_r

    def shift(p):
        return {"x": (p["x"] * w + pad_l) / nw, "y": p["y"]}

    out = {}
    for k, v in marks.items():
        out[k] = {"base": shift(v["base"]), "tip": shift(v["tip"])} if "base" in v else shift(v)
    return sprite, out


def make_view(sprite, marks: dict, kind: str, open_mouth: bool = False) -> dict:
    """Rig di una vista. kind: busto | seduto | serio | dietro."""
    rig = make_rig(sprite, marks, kind, refine=kind != "dietro")
    rig.pop("name", None)
    rig["sprite"] = "sprite.png" if kind == "busto" else f"{kind}.png"
    if kind != "busto":
        rig.update(feet=1.0, full=True, height=FULL_HEIGHT)
    if kind == "dietro":
        rig.update(face=False, height=round(FULL_HEIGHT * 1.06, 3))
    if open_mouth:
        rig["open_mouth"] = True
    return rig


def write_rig(folder: Path, name: str, species: str, views: dict[str, dict]) -> dict:
    """rig.json: il primo piano sta al livello principale (compatibile con le pelli a
    una sola foto), le altre viste sotto "views"."""
    rig: dict = {"name": name, "species": species}
    if "busto" in views:
        rig.update(views["busto"])
        if (folder / "paw.png").exists():
            rig["paw"] = "paw.png"
    rest = {k: v for k, v in views.items() if k != "busto"}
    if rest:
        rig["views"] = rest
    rig["home"] = next((k for k in ("seduto", "serio", "busto") if k in views), next(iter(views)))
    rig.setdefault("tongue", "#D8748A")
    (folder / "rig.json").write_text(json.dumps(rig, indent=2), encoding="utf-8")
    return rig


def read_views(folder: Path) -> tuple[dict, dict[str, dict]]:
    """rig.json → (dati generali, viste per nome)."""
    data = json.loads((Path(folder) / "rig.json").read_text(encoding="utf-8"))
    views = dict(data.get("views", {}))
    if "eyes" in data:
        views = {"busto": {k: v for k, v in data.items()
                           if k not in ("views", "name", "species", "home", "paw")}, **views}
    return data, views


def update_view(folder: Path, kind: str, points: dict[str, list[float]], species: str | None = None) -> None:
    """Punti corretti a mano (occhi, naso, bocca, testa, collo) → rig della vista riscritto."""
    import cv2

    folder = Path(folder)
    data, views = read_views(folder)
    old = views[kind]
    marks = {k: {"x": v[0], "y": v[1]} for k, v in points.items()}
    for key, ear in (("ear_left", old["ear_l"]), ("ear_right", old["ear_r"])):
        marks[key] = {"base": {"x": ear[2], "y": ear[3]},
                      "tip": {"x": (ear[0] - 0.35 * ear[2]) / 0.65, "y": (ear[1] - 0.35 * ear[3]) / 0.65}}
    sprite = cv2.imread(str(folder / old.get("sprite", "sprite.png")), cv2.IMREAD_UNCHANGED)
    new = make_view(sprite, marks, kind, bool(old.get("open_mouth")))
    views[kind] = new
    write_rig(folder, data.get("name", folder.name), species or data.get("species", "cane"), views)


# ------------------------------------------------------------------- pipeline
_DEFAULT_MARKS = {"eye_left": {"x": 0.38, "y": 0.30}, "eye_right": {"x": 0.62, "y": 0.30},
                  "nose": {"x": 0.5, "y": 0.5}, "mouth": {"x": 0.5, "y": 0.62},
                  "head_top": {"x": 0.5, "y": 0.03}, "neck": {"x": 0.5, "y": 0.78},
                  "ear_left": {"base": {"x": 0.25, "y": 0.2}, "tip": {"x": 0.14, "y": 0.5}},
                  "ear_right": {"base": {"x": 0.75, "y": 0.2}, "tip": {"x": 0.86, "y": 0.5}}}


def _extract(img, box: dict | None, analysis: dict | None, body: bool):
    """Ritaglia `box` dalla foto, toglie lo sfondo, porta i punti dell'AI sullo sprite."""
    H, W = img.shape[:2]
    cx0, cy0, cx1, cy1 = 0.0, 0.0, 1.0, 1.0
    if box is not None:
        mx, my = 0.04 * (box["x1"] - box["x0"]), 0.04 * (box["y1"] - box["y0"])
        cx0, cy0 = max(0.0, box["x0"] - mx), max(0.0, box["y0"] - my)
        cx1, cy1 = min(1.0, box["x1"] + mx), min(1.0, box["y1"] + my)
    crop = img[int(cy0 * H):int(cy1 * H), int(cx0 * W):int(cx1 * W)]
    if crop.size == 0 or min(crop.shape[:2]) < 40:
        raise ValueError("il riquadro dell'animale e' troppo piccolo")

    def to_crop(p):
        return ((p["x"] - cx0) / (cx1 - cx0), (p["y"] - cy0) / (cy1 - cy0))

    seeds = None
    if analysis is not None:
        keys = ("eye_left", "eye_right", "nose", "mouth", "neck") if not body else ("head_top", "neck")
        seeds = [to_crop(analysis[k]) for k in keys]
        if body:                                   # anche il corpo: dal collo giu' fino a meta' zampe
            nx, ny = seeds[-1]
            seeds += [(nx * 0.5 + 0.25, ny + (0.82 - ny) * t) for t in (0.35, 0.7, 1.0)]
        seeds = [(min(0.98, max(0.02, x)), min(0.98, max(0.02, y))) for x, y in seeds]
    sprite, (sx0, sy0, sx1, sy1) = cutout(crop, seeds, body=body)

    def to_sprite(p):
        x, y = to_crop(p)
        return {"x": (x - sx0) / (sx1 - sx0), "y": (y - sy0) / (sy1 - sy0)}

    return sprite, (_marks(analysis, to_sprite) if analysis is not None else None), to_sprite


def _marks(analysis: dict, convert) -> dict:
    marks = {k: convert(analysis[k]) for k in FACE_KEYS}
    for k in ("ear_left", "ear_right"):
        marks[k] = {"base": convert(analysis[k]["base"]), "tip": convert(analysis[k]["tip"])}
    return marks


def _bust_from_body(sprite, analysis: dict, to_sprite):
    """Il primo piano ritagliato dalla figura intera gia' scontornata (stesso bordo pulito)."""
    h, w = sprite.shape[:2]
    b = analysis["bust"]
    p0, p1 = to_sprite({"x": b["x0"], "y": b["y0"]}), to_sprite({"x": b["x1"], "y": b["y1"]})
    x0, x1 = max(0, int(p0["x"] * w)), min(w, int(p1["x"] * w))
    y0, y1 = max(0, int(p0["y"] * h)), min(h, int(p1["y"] * h))
    if y1 - y0 < 200 or x1 - x0 < 120:
        return None                                  # troppo piccolo per reggere un primo piano
    crop = sprite[y0:y1, x0:x1]
    cols = crop[:, :, 3].max(axis=0) > 8
    if not cols.any():
        return None
    xa, xb = int(cols.argmax()), int(len(cols) - cols[::-1].argmax())
    crop = crop[:, xa:xb]
    x0 += xa

    def conv(p):
        q = to_sprite(p)
        return {"x": (q["x"] * w - x0) / crop.shape[1], "y": (q["y"] * h - y0) / crop.shape[0]}

    return crop, _marks(analysis, conv)


def _guess_framing(sprite, marks: dict | None) -> str:
    """Senza AI: occhi lontani tra loro rispetto all'altezza = primo piano."""
    if marks is None:
        return "closeup"
    h, w = sprite.shape[:2]
    e = math.hypot((marks["eye_right"]["x"] - marks["eye_left"]["x"]) * w,
                   (marks["eye_right"]["y"] - marks["eye_left"]["y"]) * h)
    return "closeup" if e / h > 0.19 else "full_front"


def _slot(framing: str, mood: str, taken: set[str]) -> str | None:
    """A quale vista della pelle corrisponde questa foto (None = doppione)."""
    if framing == "closeup":
        order = ("busto",)
    elif framing == "full_back":
        order = ("dietro",)
    else:
        order = ("serio", "seduto") if mood == "serious" else ("seduto", "serio")
    return next((k for k in order if k not in taken), None)


def _save_view(folder: Path, kind: str, sprite, marks: dict, open_mouth: bool) -> tuple[dict, list[int]]:
    import cv2

    if kind != "busto":
        sprite, marks = _center_on(sprite, marks)
    s = 1000 / sprite.shape[0]
    sprite = cv2.resize(sprite, (max(1, int(sprite.shape[1] * s)), 1000),
                        interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_CUBIC)
    rig = make_view(sprite, marks, kind, open_mouth)
    cv2.imwrite(str(folder / rig["sprite"]), sprite, [cv2.IMWRITE_PNG_COMPRESSION, 9])
    return rig, [sprite.shape[1], sprite.shape[0]]


def build_skin(photo, name: str, out_root: Path, use_ai: bool = True, client=None,
               analysis=None, species: str | None = None) -> dict:
    """Una o piu' foto → cartella pelle. Ritorna un rapporto (viste create, metodo, avvisi).

    `photo` e `analysis` possono essere singoli o liste parallele (una analisi per foto).
    """
    import cv2

    photos = [Path(p) for p in (photo if isinstance(photo, (list, tuple)) else [photo])]
    analyses = list(analysis) if isinstance(analysis, (list, tuple)) else [analysis] * len(photos)
    if isinstance(analysis, dict) and len(photos) > 1:
        analyses = [analysis] + [None] * (len(photos) - 1)
    report: dict = {"name": name, "method": "pixel", "warnings": [], "views": {}, "species": species or ""}
    folder = Path(out_root) / name
    views: dict[str, dict] = {}
    sizes: dict[str, list[int]] = {}
    errors: list[str] = []
    derived: set[str] = set()          # viste ricavate da un'altra foto: una foto vera le sostituisce

    for path, info in zip(photos, analyses):
        img = cv2.imread(str(path))
        if img is None:
            errors.append(f"non riesco a leggere {path.name}")
            continue
        if info is None and use_ai:
            info = analyze_photo(img, client)
        if info is not None and not info.get("usable", True):
            errors.append(info.get("problem") or f"{path.name}: foto non adatta")
            continue
        try:
            if info is not None:
                report["method"] = "ai"
                if not report["species"]:
                    report["species"] = SPECIES.get(str(info.get("species", "")).lower(), "")
                framing = info.get("framing", "closeup")
                body = framing != "closeup"
                sprite, marks, to_sprite = _extract(
                    img, info.get("body" if body else "bust") or info.get("bust"), info, body)
            else:
                sprite, _, to_sprite = _extract(img, None, None, False)
                marks = guess_landmarks(sprite)
                framing = _guess_framing(sprite, marks)
                if marks is None:
                    report["warnings"].append(f"{path.name}: occhi e naso non trovati in automatico, indicali a mano")
                    marks = json.loads(json.dumps(_DEFAULT_MARKS))
                    if report["method"] != "ai":
                        report["method"] = "manuale"
            kind = _slot(framing, (info or {}).get("mood", "happy"), set(views) - derived)
            if kind is None:
                report["warnings"].append(f"{path.name}: c'e' gia' una foto per questa vista, la salto")
                continue
            folder.mkdir(parents=True, exist_ok=True)
            open_mouth = bool((info or {}).get("mouth_open", False))
            views[kind], sizes[kind] = _save_view(folder, kind, sprite, marks, open_mouth)
            report["views"][kind] = path.name
            derived.discard(kind)
            # da una figura intera di fronte si ricava anche il primo piano (zampe sul bordo, nascondino...)
            if info is not None and kind in ("seduto", "serio") and "busto" not in views:
                cut = _bust_from_body(sprite, info, to_sprite)
                if cut is not None:
                    views["busto"], sizes["busto"] = _save_view(folder, "busto", cut[0], cut[1], open_mouth)
                    report["views"]["busto"] = f"{path.name} (ritaglio)"
                    derived.add("busto")
        except ValueError as exc:
            errors.append(f"{path.name}: {exc}")

    if not views:
        raise ValueError("; ".join(errors) or "nessuna foto utilizzabile")
    report["warnings"] += errors
    report["species"] = report["species"] or "cane"
    main = "busto" if "busto" in views else next(iter(views))
    full = write_rig(folder, name, report["species"], views)
    missing = [k for k in ("busto", "seduto", "serio", "dietro") if k not in views]
    report.update(folder=str(folder), size=sizes[main], rig=dict(views[main], name=name),
                  rigs=views, home=full["home"], missing=missing)
    return report


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Crea in automatico una pelle animata dalle foto del tuo animale")
    ap.add_argument("foto", type=Path, nargs="+",
                    help="una o piu' foto: primo piano, figura intera di fronte, seria, di spalle")
    ap.add_argument("--nome", default="mio-animale")
    ap.add_argument("--specie", choices=("cane", "gatto"), default=None, help="se omessa la riconosce l'AI")
    ap.add_argument("--out", type=Path, default=None, help="cartella skins (default: quella utente)")
    ap.add_argument("--senza-ai", action="store_true", help="non chiamare il modello di visione")
    args = ap.parse_args(argv)
    from ..config import config_dir

    out = args.out or (config_dir() / "skins")
    try:
        rep = build_skin(args.foto, args.nome, out, use_ai=not args.senza_ai, species=args.specie)
    except ValueError as exc:
        print(f"non riuscito: {exc}")
        return 1
    print(f"pelle creata: {rep['folder']}  ({rep['species']}, metodo: {rep['method']})")
    for kind, src in rep["views"].items():
        print(f"  vista {kind:7s} <- {src}")
    if rep["missing"]:
        print("  viste mancanti (le azioni ripiegano sulla piu' vicina):", ", ".join(rep["missing"]))
    for wmsg in rep["warnings"]:
        print("  attenzione:", wmsg)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
