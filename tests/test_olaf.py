"""Olaf, il barboncino: seconda pelle con viste diverse (seduto in smoking, sdraiato, dorme)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtGui = pytest.importorskip("PySide6.QtGui")

from animaldesk import config as cfg_mod
from animaldesk.pet import Pet
from animaldesk.render_types import Pose
from animaldesk.skin import SkinSet


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def olaf(app):
    folder = cfg_mod.find_skin("olaf")
    assert folder is not None, "la pelle di Olaf deve essere nel repo"
    return SkinSet.load(folder)


def _draw(skin, pose, size=160):
    img = QtGui.QImage(560, 520, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    painter = QtGui.QPainter(img)
    painter.translate(280, 500)
    skin.draw(painter, pose, size)
    painter.end()
    return img


def _opaque(img, step=4):
    return sum(1 for y in range(0, img.height(), step) for x in range(0, img.width(), step)
               if img.pixelColor(x, y).alpha() > 40)


def test_olaf_ha_le_sue_viste(olaf):
    assert set(olaf.views) == {"busto", "seduto", "sdraiato", "dorme"}
    assert olaf.home == "seduto" and olaf.full and olaf.legged
    assert olaf.framings() == ["intera", "busto"]
    assert olaf.views["busto"].paw is not None              # la sua zampa vera per tastiera e leccata
    assert len(olaf.views["sdraiato"].rig.legs) == 2
    assert not olaf.views["dorme"].rig.face            # dorme a occhi chiusi: niente palpebre
    for name, v in olaf.views.items():
        assert v.image.pixelColor(2, 2).alpha() == 0, f"{name}: sfondo non trasparente"


def test_l_occhio_nascosto_non_ha_palpebra(olaf):
    """Testa di tre quarti: un occhio e' dietro al muso; chiudere gli occhi non deve
    disegnare una fessura sul pelo."""
    v = olaf.views["seduto"]
    hidden = [e for e in v.rig.eyes if e.hidden]
    assert len(hidden) == 1
    v._prepare(200)
    c = v.uv(hidden[0].x, hidden[0].y)
    open_eyes = v._work_texture(Pose(eye_open=1.0)).pixelColor(int(c.x()), int(c.y()))
    closed = v._work_texture(Pose(eye_open=0.0)).pixelColor(int(c.x()), int(c.y()))
    assert open_eyes == closed


@pytest.mark.parametrize("view", ["busto", "seduto", "sdraiato", "dorme"])
def test_ogni_vista_di_olaf_disegna(olaf, view):
    olaf.cur = view
    for _ in range(20):
        olaf.advance(1 / 30, Pose(view=view))
    assert _opaque(_draw(olaf, Pose(view=view))) > 400


def test_le_teste_hanno_la_stessa_misura(olaf):
    """Passando da una vista all'altra il cane non deve cambiare taglia: stessa testa."""
    heads = [v.rig.head * v.rig.height for k, v in olaf.views.items() if k not in ("dorme", "busto")]
    assert max(heads) / min(heads) < 1.15


def _pet():
    return Pet(bust=True, full=True, views=("busto", "seduto", "sdraiato", "dorme"), legs=True)


def _pose(pet, state, t):
    pet.state, pet.t, pet.duration = state, t, 10.0
    return pet._build_pose()


def test_sdraiati_usa_la_foto_sdraiata_e_muove_le_zampe():
    pet = _pet()
    lifted = 0.0
    for i in range(80):
        pose = _pose(pet, "rest", 0.5 + i * 0.1)
        assert pose.view == "sdraiato"
        lifted = max(lifted, pose.lift_l, pose.lift_r)
    assert lifted > 0.3


def test_dorme_con_la_foto_vera():
    pet = _pet()
    assert _pose(pet, "sleep", 2.0).view == "dorme"


def test_senza_foto_di_spalle_se_ne_va_sotto_il_bordo():
    pet = _pet()
    pet.state, pet.t, pet.duration = "leave", 2.5, 6.0
    pose = pet._build_pose()
    assert pose.view != "dietro" and pose.away == 0.0 and pose.sink > 0.3


def test_sdraiati_solo_se_c_e_la_foto():
    pet = Pet(bust=True, full=True, views=("seduto",), legs=True)
    pet.stats.energia = pet.stats.fame = 50
    from animaldesk.pet import World

    world = World(ground=600, left=0, right=800, has_bowl=False, scale=1.0)
    assert all(pet.choose_behavior(world) != "rest" for _ in range(300))


def test_le_foto_di_olaf_non_mostrano_numeri_di_telefono():
    """La medaglietta e' ridipinta di blu pieno: nessun pixel chiaro (le cifre incise) dentro."""
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    folder = cfg_mod.find_skin("olaf")
    for name, box in (("seduto", (275, 452, 342, 518)), ("sdraiato", (535, 468, 605, 535))):
        img = cv2.imread(str(folder / f"{name}.png"), cv2.IMREAD_UNCHANGED)
        x0, y0, x1, y1 = box
        hsv = cv2.cvtColor(img[y0:y1, x0:x1, :3], cv2.COLOR_BGR2HSV)
        blue = (hsv[:, :, 0] > 92) & (hsv[:, :, 0] < 128) & (hsv[:, :, 1] > 70)
        assert blue.sum() > 200, f"{name}: medaglietta non trovata nel riquadro"
        ys, xs = np.where(blue)
        inner = hsv[ys.min() + 4:ys.max() - 4, xs.min() + 4:xs.max() - 4]
        inside = blue[ys.min() + 4:ys.max() - 4, xs.min() + 4:xs.max() - 4]
        light = (inner[:, :, 2] > 200) & (inner[:, :, 1] < 60) & inside
        assert light.sum() < 5
