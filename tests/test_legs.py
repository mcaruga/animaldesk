"""Zampe animate a figura intera + morph tra le viste (niente dissolvenza)."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtGui = pytest.importorskip("PySide6.QtGui")

from animaldesk import config as cfg_mod
from animaldesk.pet import Pet
from animaldesk.render_types import Pose
from animaldesk.skin import MORPH_TIME, SkinSet


@pytest.fixture(scope="module")
def app():
    from PySide6.QtWidgets import QApplication      # lo stesso tipo che usano i test dell'overlay

    return QApplication.instance() or QApplication([])


@pytest.fixture()
def skin(app):
    return SkinSet.load(cfg_mod.find_skin("golden-reale"))


def _draw(skin, pose, size=200):
    img = QtGui.QImage(520, 520, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    painter = QtGui.QPainter(img)
    painter.translate(260, 500)
    skin.draw(painter, pose, size)
    painter.end()
    return img


def _settle(view, pose, n=30):
    for _ in range(n):
        view.advance(1 / 30, pose)
    view.clock = 0.0


def _nearest(view, u, v):
    """Indice del vertice piu' vicino al punto dello sprite (u, v)."""
    c = view.uv(u, v)
    return min(range(len(view._src)),
               key=lambda i: (view._src[i][0] - c.x()) ** 2 + (view._src[i][1] - c.y()) ** 2)


def test_la_pelle_di_default_ha_le_zampe(skin):
    assert skin.legged
    for name in ("seduto", "serio"):
        assert len(skin.views[name].rig.legs) == 2
    assert len(skin.views["dietro"].rig.legs) >= 1
    assert not skin.views["busto"].rig.legs


@pytest.mark.parametrize("view_name", ["seduto", "serio"])
def test_alzare_la_zampa_sposta_il_piede_non_il_petto(skin, view_name):
    v = skin.views[view_name]
    leg = v.rig.legs[1]
    v._prepare(300)
    foot, chest = _nearest(v, leg[2], leg[3]), _nearest(v, v.rig.neck[0], v.rig.neck[1] + 0.12)
    rest = v._displace()
    _settle(v, Pose(lift_r=1.0))
    up = v._displace()
    assert up[foot][1] < rest[foot][1] - v.sh * 0.04, "il piede deve salire"
    assert abs(up[chest][1] - rest[chest][1]) < 1.0 and abs(up[chest][0] - rest[chest][0]) < 1.0


def test_le_zampe_si_muovono_indipendenti(skin):
    v = skin.views["seduto"]
    v._prepare(300)
    left = _nearest(v, v.rig.legs[0][2], v.rig.legs[0][3])
    rest = v._displace()
    _settle(v, Pose(lift_r=1.0, swing_r=-0.6))
    moved = v._displace()
    assert abs(moved[left][0] - rest[left][0]) < 1.0 and abs(moved[left][1] - rest[left][1]) < 1.0


def test_la_zampa_resta_attaccata_e_non_si_stira(skin):
    """Anche al massimo, nessun vertice si sposta piu' della lunghezza della gamba."""
    v = skin.views["seduto"]
    v._prepare(300)
    rest = v._displace()
    for pose in (Pose(lift_l=1.0, lift_r=1.0, swing_l=1.0, swing_r=1.0),
                 Pose(lift_l=1.0, lift_r=1.0, swing_l=-1.0, swing_r=-1.0)):
        _settle(v, pose)
        cur = v._displace()
        far = max(((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5 for a, b in zip(cur, rest))
        assert far < max(g[4] for g in v.rig.legs) * v.sw * 2.2 + 0.4 * v.sh * 0.3 + 40


@pytest.mark.parametrize("pose", [Pose(lift_l=1.0), Pose(lift_r=1.0, swing_r=-0.6),
                                  Pose(lift_l=0.6, swing_l=0.5, lift_r=0.6, swing_r=0.5)])
def test_con_le_zampe_alzate_il_cane_resta_intero(skin, pose):
    skin.cur = skin.home
    _settle(skin.view, pose)
    img = _draw(skin, pose)
    for dy in range(-170, -60, 10):                 # il busto resta pieno: nessuna fessura
        assert img.pixelColor(260, 500 + dy).alpha() > 200


# --------------------------------------------------------------------- pet
def _pet(legs):
    return Pet(bust=True, full=True, views=("seduto", "serio", "dietro", "busto"), legs=legs)


def _pose(pet, state, t=0.3):
    pet.state, pet.t, pet.duration = state, t, 4.0
    pet.leg_phase = 0.0
    return pet._build_pose()


@pytest.mark.parametrize("action", ["typing", "lick", "scratch", "boop", "tease", "bark"])
def test_le_azioni_con_zampe_restano_a_figura_intera(action):
    pet = _pet(True)
    lifted = False
    for t in (0.4, 0.55, 0.7, 0.9, 1.1, 1.3):
        pose = _pose(pet, action, t)
        assert pose.view != "busto"
        lifted |= max(pose.lift_l, pose.lift_r) > 0.15
    assert lifted, f"{action}: almeno una zampa deve muoversi"


def test_senza_zampe_si_usa_ancora_il_primo_piano():
    assert _pose(_pet(False), "typing").view == "busto"


def test_battere_alla_tastiera_alterna_le_zampe():
    pet = _pet(True)
    seen_l = seen_r = False
    for i in range(40):
        pose = _pose(pet, "typing", 0.6 + i * 0.01)
        seen_l |= pose.lift_l > 0.3 and pose.lift_r == 0.0
        seen_r |= pose.lift_r > 0.3 and pose.lift_l == 0.0
        assert pose.prop == "keyboard"
    assert seen_l and seen_r


def test_nascondino_scende_anche_a_figura_intera():
    pet = _pet(True)
    assert _pose(pet, "hide", 1.0).sink > 0.5


def test_di_spalle_cammina(skin):
    pet = _pet(True)
    best = 0.0
    for i in range(30):
        pet.leg_phase = i * 0.3
        pet.state, pet.t, pet.duration = "leave", 1.5, 6.0
        pose = pet._build_pose()
        assert pose.view == "dietro"
        best = max(best, pose.lift_l)
    assert best > 0.3


# -------------------------------------------------------------------- morph
def _go(skin, view, seconds, pose=None):
    pose = pose or Pose(view=view)
    for _ in range(int(seconds * 30)):
        skin.advance(1 / 30, pose)


@pytest.mark.parametrize("a,b", [("seduto", "serio"), ("seduto", "dietro"), ("dietro", "seduto")])
def test_il_passaggio_tra_figure_intere_e_un_morph(skin, a, b):
    skin.cur = a
    _go(skin, a, 1.0)
    skin.advance(1 / 30, Pose(view=b))
    assert skin.morph and skin.prev == a and skin.cur == b
    _go(skin, b, MORPH_TIME + 0.2)
    assert skin.prev is None and skin.cur == b


def test_col_primo_piano_resta_la_dissolvenza(skin):
    skin.cur = "seduto"
    _go(skin, "seduto", 0.5)
    skin.advance(1 / 30, Pose(view="busto"))
    assert not skin.morph


def test_il_campo_porta_le_parti_sulle_parti(skin):
    """Il vertice sul naso della vista vecchia si sposta (quasi) sul naso della nuova."""
    a, b = skin.views["seduto"], skin.views["dietro"]
    sa, sb = 200 * a.rig.height, 200 * b.rig.height
    field = a.field_to(b, sa, sb)
    anch_a, anch_b = a.anchors(sa), b.anchors(sb)
    idx = _nearest(a, *a.rig.nose)
    want = (anch_b["nose"][0] - anch_a["nose"][0], anch_b["nose"][1] - anch_a["nose"][1])
    got = field[idx]
    assert abs(got[0] - want[0]) < 0.08 * sa and abs(got[1] - want[1]) < 0.08 * sa
    assert a.field_to(b, sa, sb) is field                      # in cache


def _solid(img):
    return sum(1 for y in range(0, 520, 3) for x in range(0, 520, 3) if img.pixelColor(x, y).alpha() > 200)


def test_il_morph_non_e_mai_trasparente(skin):
    """A meta' strada il cane non e' "sbiadito": la superficie piena non scende sotto quella delle
    due viste (una dissolvenza la farebbe crollare)."""
    skin.cur = "seduto"
    _go(skin, "seduto", 1.0)
    start = _solid(_draw(skin, Pose(view="seduto")))
    other = SkinSet.load(cfg_mod.find_skin("golden-reale"))
    other.cur = "dietro"
    _go(other, "dietro", 1.0)
    end = _solid(_draw(other, Pose(view="dietro")))
    for i in range(int(MORPH_TIME * 30) + 2):
        skin.advance(1 / 30, Pose(view="dietro"))
        if skin.prev is not None:
            assert _solid(_draw(skin, Pose(view="dietro"))) > 0.8 * min(start, end), f"frame {i}"


def test_il_morph_comincia_e_finisce_come_le_viste(skin):
    """All'inizio e' la vista vecchia, alla fine la nuova: nessun salto."""
    skin.cur = "seduto"
    _go(skin, "seduto", 1.0)
    before = _draw(skin, Pose(view="seduto"))
    skin.advance(1 / 30, Pose(view="serio"))
    first = _draw(skin, Pose(view="serio"))
    diff = sum(1 for y in range(0, 520, 4) for x in range(0, 520, 4)
               if abs(before.pixelColor(x, y).alpha() - first.pixelColor(x, y).alpha()) > 100)
    assert diff < 0.04 * (130 * 130)
    _go(skin, "serio", MORPH_TIME + 0.3)
    after = _draw(skin, Pose(view="serio"))
    skin2 = SkinSet.load(cfg_mod.find_skin("golden-reale"))
    skin2.cur = "serio"
    _go(skin2, "serio", 1.0)
    plain = _draw(skin2, Pose(view="serio"))
    diff = sum(1 for y in range(0, 520, 4) for x in range(0, 520, 4)
               if abs(after.pixelColor(x, y).alpha() - plain.pixelColor(x, y).alpha()) > 100)
    assert diff < 0.03 * (130 * 130)


def test_il_morph_ha_spazio_nella_maschera(skin):
    skin.cur = "seduto"
    _go(skin, "seduto", 0.5)
    quiet = skin.bounds(200)
    skin.advance(1 / 30, Pose(view="dietro"))
    assert skin.bounds(200).width() > quiet.width()


# -------------------------------------------------------------- altri animali
def test_zampe_trovate_dalla_sagoma():
    np = pytest.importorskip("numpy")
    cv2 = pytest.importorskip("cv2")
    from animaldesk.tools.auto_skin import find_legs

    folder = cfg_mod.find_skin("golden-reale")
    for name in ("seduto", "serio"):
        img = cv2.imread(str(folder / f"{name}.png"), cv2.IMREAD_UNCHANGED)
        legs = find_legs(img, 0.5)
        assert len(legs) == 2 and legs[0][2] < 0.35 < 0.55 < legs[1][2]
        assert all(0.05 < g[4] <= 0.24 for g in legs)
    blob = np.zeros((400, 200, 4), np.uint8)
    blob[:, 40:160, 3] = 255                                   # un blocco solo: niente piedi distinti
    assert find_legs(blob) == []
