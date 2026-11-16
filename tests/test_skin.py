import datetime as dt
import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtGui = pytest.importorskip("PySide6.QtGui")

from animaldesk import config as cfg_mod
from animaldesk import outfits
from animaldesk.breeds import BREEDS, GOLDEN, POODLE, get
from animaldesk.dogart import draw_dog
from animaldesk.render_types import Pose
from animaldesk.skin import Skin


@pytest.fixture(scope="module")
def app():
    return QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])


def _opaque(img, step=4):
    return sum(1 for y in range(0, img.height(), step) for x in range(0, img.width(), step)
               if img.pixelColor(x, y).alpha() > 0)


def _make_skin(tmp_path):
    """Pelle sintetica: rettangolo color pelo con due 'occhi' scuri."""
    folder = tmp_path / "prova"
    folder.mkdir(exist_ok=True)
    img = QtGui.QImage(160, 200, QtGui.QImage.Format_ARGB32)
    img.fill(QtGui.QColor(205, 165, 95, 255))
    for cx in (50, 110):
        for x in range(cx - 8, cx + 8):
            for y in range(56, 66):
                img.setPixelColor(x, y, QtGui.QColor(8, 8, 8))
    img.save(str(folder / "sprite.png"))
    (folder / "rig.json").write_text(json.dumps({
        "name": "prova", "sprite": "sprite.png",
        "eyes": [{"x": 50 / 160, "y": 61 / 200, "rx": 0.06, "ry": 0.03},
                 {"x": 110 / 160, "y": 61 / 200, "rx": 0.06, "ry": 0.03}],
        "nose": [0.5, 0.5], "mouth": [0.5, 0.62], "head_top": [0.5, 0.02], "neck": [0.5, 0.8],
    }))
    return folder


def _settle(skin, pose, n=60):
    for _ in range(n):
        skin.advance(1 / 30, pose)
    skin.clock = 0.0


def _draw(skin, pose, size=200):
    img = QtGui.QImage(420, 420, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    painter = QtGui.QPainter(img)
    painter.translate(210, 400)
    skin.draw(painter, pose, size)
    painter.end()
    return img


def test_pelle_di_default_si_carica(app):
    folder = cfg_mod.find_skin("golden-reale")
    assert folder is not None, "la pelle fotografica di default deve essere nel repo"
    skin = Skin.load(folder)
    assert len(skin.rig.eyes) == 2
    assert skin.paw is not None
    assert 0.5 < skin.aspect < 1.5
    # sfondo davvero trasparente negli angoli in alto
    assert skin.image.pixelColor(2, 2).alpha() == 0
    assert skin.image.pixelColor(skin.image.width() - 3, 2).alpha() == 0


@pytest.mark.parametrize("pose", [
    Pose(), Pose(yaw=1.0), Pose(yaw=-1.0), Pose(pitch=1.0), Pose(pitch=-1.0),
    Pose(head_tilt=14, brow=1.0), Pose(eye_open=0.0), Pose(tongue=1.0, mouth_open=1.0),
    Pose(paws=1.0, paw_l=1.0, prop="keyboard"), Pose(paws=1.0, paw_reach=1.0),
    Pose(sink=0.6), Pose(lie=1.0, sink=0.36, eye_open=0.0), Pose(facing=-1),
])
def test_ogni_posa_disegna_senza_buchi(app, tmp_path, pose):
    skin = Skin.load(_make_skin(tmp_path))
    _settle(skin, pose)
    img = _draw(skin, pose)
    assert _opaque(img) > 300
    if pose.sink == 0 and pose.lie == 0:
        # il centro del petto deve restare pieno: la griglia non lascia fessure
        for dx in range(-30, 31, 6):
            for dy in range(-120, -39, 8):
                assert img.pixelColor(210 + dx, 400 + dy).alpha() > 200


def test_la_deformazione_resta_piccola(app, tmp_path):
    """Il viso non deve mai stirarsi: nessun vertice si sposta piu' del 9% della taglia."""
    skin = Skin.load(_make_skin(tmp_path))
    size = 200
    for pose in (Pose(yaw=1.0, pitch=1.0), Pose(yaw=-1.0, pitch=-1.0, brow=1.0, mouth_open=1.0)):
        _settle(skin, pose)
        skin.render(pose, size)
        moved = max(((dx - sx - 10) ** 2 + (dy - sy - 10) ** 2) ** 0.5
                    for (sx, sy), (dx, dy) in zip(skin._src, skin._displace()))
        assert moved < size * 0.09


def test_la_palpebra_copre_l_occhio(app, tmp_path):
    skin = Skin.load(_make_skin(tmp_path))

    def eye_lightness(pose):
        _settle(skin, pose)
        skin.roll = skin.yaw = skin.pitch = 0.0
        buf = skin.render(pose, 200)
        pt = skin.uv(50 / 160, 61 / 200)
        return buf.pixelColor(int(pt.x()) + 10, int(pt.y()) + 10).lightness()

    assert eye_lightness(Pose()) < 60                # aperto: scuro
    assert eye_lightness(Pose(eye_open=0.0)) > 80    # chiuso: pelo


def test_inseguimento_morbido(app, tmp_path):
    skin = Skin.load(_make_skin(tmp_path))
    skin.advance(1 / 30, Pose(yaw=1.0))
    assert 0.0 < skin.yaw < 0.5, "un solo frame non deve far scattare la testa"
    _settle(skin, Pose(yaw=1.0), n=120)
    assert skin.yaw > 0.8


@pytest.mark.parametrize("outfit", ["santa", "summer", "ski"])
def test_i_costumi_si_disegnano(app, tmp_path, outfit):
    skin = Skin.load(_make_skin(tmp_path))
    plain = _opaque(_draw(skin, Pose()))
    skin.set_outfit(outfit)
    dressed = _opaque(_draw(skin, Pose()))
    assert dressed > plain, f"{outfit} deve aggiungere pixel"


def test_costume_stagionale():
    assert outfits.seasonal(dt.date(2026, 12, 24)) == "santa"
    assert outfits.seasonal(dt.date(2027, 1, 3)) == "santa"
    assert outfits.seasonal(dt.date(2026, 7, 20)) == "summer"
    assert outfits.seasonal(dt.date(2026, 3, 10)) == ""
    assert outfits.resolve("auto", dt.date(2026, 8, 1)) == "summer"
    assert outfits.resolve("ski") == "ski"
    assert outfits.resolve("boh") == ""


def test_ricerca_pelli(tmp_path, monkeypatch):
    folder = _make_skin(tmp_path)
    monkeypatch.setattr(cfg_mod, "skins_dirs", lambda: [tmp_path])
    assert cfg_mod.list_skins() == ["prova"]
    assert cfg_mod.find_skin("prova") == folder
    assert cfg_mod.find_skin("non-esiste") is None
    assert cfg_mod.find_skin("") is None


def test_razze():
    assert set(BREEDS) == {"golden", "barboncino"}
    assert get("boh") is GOLDEN
    assert POODLE.coat == "curly" and POODLE.tail == "pompom" and POODLE.topknot


@pytest.mark.parametrize("breed", [GOLDEN, POODLE])
def test_ogni_razza_disegna(app, breed):
    img = QtGui.QImage(160, 160, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    painter = QtGui.QPainter(img)
    draw_dog(painter, Pose(leg_swing=1.0, leg_phase=1.0), 150, breed)
    painter.end()
    assert _opaque(img) > 200
    assert img.pixelColor(1, 1).alpha() == 0
