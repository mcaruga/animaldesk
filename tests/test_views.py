"""Pelle a piu' viste: figura intera, serio, di spalle, primo piano."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtGui = pytest.importorskip("PySide6.QtGui")

from animaldesk import config as cfg_mod
from animaldesk.render_types import Pose
from animaldesk.skin import SkinSet


@pytest.fixture(scope="module")
def app():
    return QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])


@pytest.fixture()
def skin(app):
    return SkinSet.load(cfg_mod.find_skin("golden-reale"))


def _draw(skin, pose, size=120):
    img = QtGui.QImage(420, 420, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    painter = QtGui.QPainter(img)
    painter.translate(210, 400)
    skin.draw(painter, pose, size)
    painter.end()
    return img


def _opaque(img, step=4):
    return sum(1 for y in range(0, img.height(), step) for x in range(0, img.width(), step)
               if img.pixelColor(x, y).alpha() > 40)


def _settle(skin, pose, n=40):
    for _ in range(n):
        skin.advance(1 / 30, pose)


def test_la_pelle_di_default_ha_tutte_le_viste(skin):
    assert set(skin.views) == {"busto", "seduto", "serio", "dietro"}
    assert skin.home == "seduto" and skin.full and skin.species == "cane"
    assert skin.framings() == ["intera", "busto"]
    assert skin.views["seduto"].rig.full and skin.views["seduto"].rig.open_mouth
    assert not skin.views["busto"].rig.full and skin.views["busto"].paw is not None
    assert not skin.views["dietro"].rig.face, "di spalle non c'e' un viso da animare"
    for key, view in skin.views.items():           # sfondo davvero trasparente negli angoli in alto
        assert view.image.pixelColor(2, 2).alpha() == 0, key
        assert view.image.pixelColor(view.image.width() - 3, 2).alpha() == 0, key


def test_inquadratura_scelta_dall_utente(skin):
    skin.set_framing("busto")
    assert skin.home == "busto" and not skin.full
    skin.set_framing("intera")
    assert skin.home == "seduto" and skin.full


def test_vista_mancante_ripiega_sulla_piu_vicina(skin):
    assert skin.resolve("") == "seduto"
    assert skin.resolve("serio") == "serio"
    del skin.views["serio"]
    assert skin.resolve("serio") == "seduto"
    del skin.views["dietro"]
    assert skin.resolve("dietro") == "seduto"
    assert skin.resolve("sdraiato") == "seduto"


def test_cambio_di_vista_senza_scatti(skin):
    _settle(skin, Pose())
    assert skin.cur == "seduto" and skin.prev is None
    skin.advance(1 / 30, Pose(view="serio"))
    assert skin.cur == "serio" and skin.prev == "seduto" and 0 < skin.mix < 0.5
    assert _opaque(_draw(skin, Pose(view="serio"))) > 200, "a meta' del passaggio il cane c'e' sempre"
    _settle(skin, Pose(view="serio"))
    assert skin.prev is None and skin.mix == 1.0


def test_il_primo_piano_sale_da_sotto_il_bordo(skin):
    _settle(skin, Pose())
    skin.advance(1 / 30, Pose(view="busto"))
    assert skin.cur == "busto" and skin.view.sink > 0.7
    _settle(skin, Pose(view="busto"), n=60)
    assert skin.view.sink < 0.05


@pytest.mark.parametrize("view", ["seduto", "serio", "dietro", "busto"])
def test_ogni_vista_disegna(skin, view):
    pose = Pose(view=view, yaw=0.6, eye_open=0.3, mouth_open=0.5)
    _settle(skin, pose, n=60)
    assert _opaque(_draw(skin, pose)) > 300


def test_andando_via_rimpicciolisce_e_sparisce(skin):
    here = Pose(view="dietro")
    _settle(skin, here, n=60)
    near = skin.rect(120).height()
    half = Pose(view="dietro", away=0.5)
    _settle(skin, half, n=60)
    assert skin.rect(120).height() < near * 0.85
    gone = Pose(view="dietro", away=1.0)
    _settle(skin, gone, n=60)
    assert not skin.visible
    assert _opaque(_draw(skin, gone)) == 0


def test_la_figura_intera_non_deforma_il_corpo(skin):
    """Testa girata al massimo: il viso si muove poco, zampe e petto restano fermi."""
    view = skin.views["seduto"]
    pose = Pose(yaw=1.0, pitch=1.0, brow=1.0, mouth_open=1.0)
    for _ in range(90):
        view.advance(1 / 30, pose)
    view.clock = 0.0
    view.render(pose, 300)
    worst = feet = 0.0
    for (sx, sy), (dx, dy), w in zip(view._src, view._displace(), view._weights):
        moved = ((dx - sx - 10) ** 2 + (dy - sy - 10) ** 2) ** 0.5
        worst = max(worst, moved)
        if w[1] > 0.75:                               # meta' bassa dello sprite: zampe
            feet = max(feet, moved)
    assert worst < view.hs * 0.125
    assert feet < 0.5


def test_di_spalle_non_si_muove_la_testa(skin):
    view = skin.views["dietro"]
    pose = Pose(yaw=1.0, pitch=1.0, head_tilt=14)
    for _ in range(60):
        view.advance(1 / 30, pose)
    view.clock = 0.0
    view.render(pose, 300)
    assert all(w[2] == 0.0 for w in view._weights)


def test_costumi_su_tutte_le_viste(skin):
    for outfit in ("santa", "summer", "ski"):
        skin.set_outfit(outfit)
        for view in skin.views:
            pose = Pose(view=view)
            _settle(skin, pose, n=30)
            assert _opaque(_draw(skin, pose)) > 300, (outfit, view)
