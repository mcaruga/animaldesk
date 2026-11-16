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
