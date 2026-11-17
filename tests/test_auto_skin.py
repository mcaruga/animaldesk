import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

cv2 = pytest.importorskip("cv2")
np = pytest.importorskip("numpy")

from animaldesk.tools import auto_skin


def _photo(tmp_path, eyes_dark=True):
    """Foto sintetica: testa chiara su fondo grigio-blu, due occhi e un naso scuri."""
    img = np.full((600, 500, 3), (150, 120, 95), np.uint8)
    cv2.ellipse(img, (250, 330), (150, 210), 0, 0, 360, (150, 200, 235), -1)       # testa + petto
    rng = np.random.default_rng(1)
    img = np.clip(img.astype(np.int16) + rng.integers(-6, 7, img.shape), 0, 255).astype(np.uint8)
    if eyes_dark:
        cv2.ellipse(img, (195, 250), (20, 13), 0, 0, 360, (12, 12, 14), -1)
        cv2.ellipse(img, (305, 250), (20, 13), 0, 0, 360, (12, 12, 14), -1)
        cv2.ellipse(img, (250, 340), (34, 26), 0, 0, 360, (16, 14, 18), -1)
    path = tmp_path / "foto.png"
    cv2.imwrite(str(path), img)
    return path


ANALYSIS = {
    "usable": True, "problem": "", "species": "cane",
    "bust": {"x0": 0.16, "y0": 0.16, "x1": 0.84, "y1": 0.94},
    # volutamente spostati di ~2%: la rifinitura sui pixel deve riportarli sugli occhi veri
    "eye_left": {"x": 0.41, "y": 0.43}, "eye_right": {"x": 0.59, "y": 0.40},
    "nose": {"x": 0.52, "y": 0.58}, "mouth": {"x": 0.50, "y": 0.66},
    "head_top": {"x": 0.50, "y": 0.21}, "neck": {"x": 0.50, "y": 0.78},
    "ear_left": {"base": {"x": 0.30, "y": 0.30}, "tip": {"x": 0.24, "y": 0.50}},
    "ear_right": {"base": {"x": 0.70, "y": 0.30}, "tip": {"x": 0.76, "y": 0.50}},
}


def test_pipeline_con_analisi_ai(tmp_path):
    rep = auto_skin.build_skin(_photo(tmp_path), "prova", tmp_path / "skins", analysis=ANALYSIS)
    assert rep["method"] == "ai"
    folder = tmp_path / "skins" / "prova"
    sprite = cv2.imread(str(folder / "sprite.png"), cv2.IMREAD_UNCHANGED)
    assert sprite.shape[2] == 4 and sprite.shape[0] == 1000
    assert sprite[2, 2, 3] == 0, "l'angolo deve essere trasparente"
    rig = json.loads((folder / "rig.json").read_text())
    assert len(rig["eyes"]) == 2
    h, w = sprite.shape[:2]
    for eye in rig["eyes"]:      # il punto rifinito cade su un pixel scuro: l'occhio vero
        px = sprite[int(eye["y"] * h), int(eye["x"] * w), :3]
        assert int(px.max()) < 70
    nose = sprite[int(rig["nose"][1] * h), int(rig["nose"][0] * w), :3]
    assert int(nose.max()) < 70
    assert rig["eyes"][0]["x"] < rig["eyes"][1]["x"]


def test_pipeline_senza_ai_trova_occhi_e_naso(tmp_path):
    rep = auto_skin.build_skin(_photo(tmp_path), "pixel", tmp_path / "skins", use_ai=False)
    assert rep["method"] == "pixel" and not rep["warnings"]
    rig = rep["rig"]
    assert rig["eyes"][0]["y"] < rig["nose"][1] < rig["mouth"][1]


def test_senza_punti_riconoscibili_avvisa(tmp_path):
    rep = auto_skin.build_skin(_photo(tmp_path, eyes_dark=False), "boh", tmp_path / "skins", use_ai=False)
    assert rep["method"] == "manuale" and rep["warnings"]


def test_foto_non_adatta_viene_rifiutata(tmp_path):
    bad = dict(ANALYSIS, usable=False, problem="il muso e' girato")
    with pytest.raises(ValueError, match="girato"):
        auto_skin.build_skin(_photo(tmp_path), "no", tmp_path / "skins", analysis=bad)


class _FakeMessages:
    def __init__(self, response):
        self.response, self.kwargs = response, None

    def create(self, **kwargs):
        self.kwargs = kwargs
        return self.response


def _client(response):
    messages = _FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_richiesta_al_modello_di_visione():
    pytest.importorskip("anthropic")
    reply = SimpleNamespace(stop_reason="end_turn",
                            content=[SimpleNamespace(type="thinking", thinking=""),
                                     SimpleNamespace(type="text", text=json.dumps(ANALYSIS))])
    client, messages = _client(reply)
    out = auto_skin.analyze_photo(np.zeros((3000, 2000, 3), np.uint8), client)
    assert out == ANALYSIS
    kw = messages.kwargs
    assert kw["model"] == "claude-opus-5-5"
    assert kw["output_config"]["format"]["type"] == "json_schema"
    assert kw["output_config"]["format"]["schema"]["additionalProperties"] is False
    assert kw["fallbacks"] == "default" and kw["betas"] == [auto_skin.FALLBACK_BETA]
    assert "thinking" not in kw and "temperature" not in kw
    image = kw["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/jpeg"
    assert "\n" not in image["source"]["data"]


def test_rifiuto_del_modello_ricade_sui_pixel():
    pytest.importorskip("anthropic")
    client, _ = _client(SimpleNamespace(stop_reason="refusal", content=[]))
    assert auto_skin.analyze_photo(np.zeros((100, 100, 3), np.uint8), client) is None


# ------------------------------------------------------- piu' foto, piu' viste
def _full_photo(tmp_path, name, serious=False, back=False):
    """Animale intero sintetico: corpo, testa in alto, due occhi e un naso (non di spalle)."""
    img = np.full((900, 600, 3), (150, 120, 95), np.uint8)
    cv2.ellipse(img, (300, 560), (150, 260), 0, 0, 360, (150, 200, 235), -1)       # corpo
    cv2.ellipse(img, (300, 250), (120, 130), 0, 0, 360, (160, 210, 240), -1)       # testa
    rng = np.random.default_rng(3)
    img = np.clip(img.astype(np.int16) + rng.integers(-6, 7, img.shape), 0, 255).astype(np.uint8)
    if not back:
        for cx in (255, 345):
            cv2.ellipse(img, (cx, 235), (16, 11), 0, 0, 360, (12, 12, 14), -1)
        cv2.ellipse(img, (300, 290), (26, 20), 0, 0, 360, (16, 14, 18), -1)
    path = tmp_path / name
    cv2.imwrite(str(path), img)
    W, H = 600, 900
    pt = lambda x, y: {"x": x / W, "y": y / H}          # noqa: E731
    info = {
        "usable": True, "problem": "", "species": "cat",
        "framing": "full_back" if back else "full_front",
        "mood": "serious" if serious else "happy", "mouth_open": not serious and not back,
        "bust": {"x0": 150 / W, "y0": 100 / H, "x1": 450 / W, "y1": 470 / H},
        "body": {"x0": 120 / W, "y0": 100 / H, "x1": 480 / W, "y1": 840 / H},
        "eye_left": pt(258, 238), "eye_right": pt(342, 232), "nose": pt(302, 292), "mouth": pt(300, 322),
        "head_top": pt(300, 122), "neck": pt(300, 378),
        "ear_left": {"base": pt(215, 170), "tip": pt(200, 110)},
        "ear_right": {"base": pt(385, 170), "tip": pt(400, 110)},
    }
    return path, info


def test_tre_foto_diventano_quattro_viste(tmp_path):
    from animaldesk.skin import SkinSet

    pytest.importorskip("PySide6.QtGui")
    photos, infos = zip(_full_photo(tmp_path, "felice.png"),
                        _full_photo(tmp_path, "serio.png", serious=True),
                        _full_photo(tmp_path, "spalle.png", back=True))
    rep = auto_skin.build_skin(list(photos), "micio", tmp_path / "skins", analysis=list(infos))
    assert rep["method"] == "ai" and rep["species"] == "gatto" and rep["home"] == "seduto"
    assert rep["views"] == {"seduto": "felice.png", "busto": "felice.png (ritaglio)",
                            "serio": "serio.png", "dietro": "spalle.png"}
    assert rep["missing"] == [] and not rep["warnings"]
    folder = tmp_path / "skins" / "micio"
    rig = json.loads((folder / "rig.json").read_text())
    assert rig["species"] == "gatto" and rig["sprite"] == "sprite.png" and len(rig["eyes"]) == 2
    assert set(rig["views"]) == {"seduto", "serio", "dietro"}
    seduto = rig["views"]["seduto"]
    assert seduto["full"] and seduto["open_mouth"] and seduto["feet"] == 1.0
    assert abs(seduto["neck"][0] - 0.5) < 0.02, "lo sprite e' centrato sul collo"
    assert rig["views"]["dietro"]["face"] is False
    assert "open_mouth" not in rig["views"]["serio"]
    for name in ("sprite.png", "seduto.png", "serio.png", "dietro.png"):
        sprite = cv2.imread(str(folder / name), cv2.IMREAD_UNCHANGED)
        assert sprite.shape[0] == 1000 and sprite[2, 2, 3] == 0, name
    eye = seduto["eyes"][0]
    sprite = cv2.imread(str(folder / "seduto.png"), cv2.IMREAD_UNCHANGED)
    assert int(sprite[int(eye["y"] * 1000), int(eye["x"] * sprite.shape[1]), :3].max()) < 70

    skin = SkinSet.load(folder)                       # e il programma la carica cosi' com'e'
    assert set(skin.views) == {"busto", "seduto", "serio", "dietro"}
    assert skin.species == "gatto" and skin.full


def test_il_primo_piano_vero_sostituisce_quello_ricavato(tmp_path):
    full, info_full = _full_photo(tmp_path, "intero.png")
    rep = auto_skin.build_skin([full, _photo(tmp_path)], "due", tmp_path / "skins",
                               analysis=[info_full, dict(ANALYSIS, framing="closeup", body=ANALYSIS["bust"])])
    assert rep["views"]["busto"] == "foto.png" and rep["views"]["seduto"] == "intero.png"
    assert rep["missing"] == ["serio", "dietro"]


def test_foto_doppia_e_foto_non_adatta_non_bloccano_le_altre(tmp_path):
    a, ia = _full_photo(tmp_path, "a.png")
    b, ib = _full_photo(tmp_path, "b.png")
    c, ic = _full_photo(tmp_path, "c.png")
    d, id_ = _full_photo(tmp_path, "d.png")
    id_ = dict(id_, usable=False, problem="il muso e' coperto")
    rep = auto_skin.build_skin([a, b, c, d], "tanti", tmp_path / "skins", analysis=[ia, ib, ic, id_])
    assert set(rep["views"]) == {"seduto", "serio", "busto"}        # la seconda felice fa da "serio"
    assert len(rep["warnings"]) == 2
    with pytest.raises(ValueError, match="coperto"):
        auto_skin.build_skin([d], "niente", tmp_path / "skins", analysis=[id_])


def test_correzione_a_mano_di_una_vista(tmp_path):
    full, info = _full_photo(tmp_path, "intero.png")
    rep = auto_skin.build_skin(full, "ritocco", tmp_path / "skins", analysis=info)
    folder = tmp_path / "skins" / "ritocco"
    old = rep["rigs"]["seduto"]
    pts = {"eye_left": [old["eyes"][0]["x"], old["eyes"][0]["y"]],
           "eye_right": [old["eyes"][1]["x"], old["eyes"][1]["y"]],
           "nose": list(old["nose"]), "mouth": list(old["mouth"]),
           "head_top": list(old["head_top"]), "neck": [old["neck"][0], old["neck"][1] + 0.03]}
    auto_skin.update_view(folder, "seduto", pts, species="gatto")
    rig = json.loads((folder / "rig.json").read_text())
    assert rig["species"] == "gatto"
    assert rig["views"]["seduto"]["neck"][1] == pytest.approx(old["neck"][1] + 0.03, abs=1e-3)
    assert rig["views"]["seduto"]["full"] and rig["views"]["seduto"]["open_mouth"]
    assert len(rig["eyes"]) == 2, "il primo piano non viene toccato"


def test_senza_ai_la_figura_intera_si_riconosce_dalle_proporzioni(tmp_path):
    full, _ = _full_photo(tmp_path, "intero.png")
    rep = auto_skin.build_skin(full, "px", tmp_path / "skins", use_ai=False)
    assert rep["method"] == "pixel" and list(rep["views"]) == ["seduto"]
    rep = auto_skin.build_skin(_photo(tmp_path), "px2", tmp_path / "skins", use_ai=False)
    assert list(rep["views"]) == ["busto"]


def test_lo_schema_chiede_specie_inquadratura_ed_espressione():
    props = auto_skin.SCHEMA["properties"]
    assert props["species"]["enum"] == ["dog", "cat", "other"]
    assert props["framing"]["enum"] == ["closeup", "full_front", "full_back"]
    assert set(auto_skin.SCHEMA["required"]) == set(props)
    assert "cat" in auto_skin.PROMPT and "full_back" in auto_skin.PROMPT
