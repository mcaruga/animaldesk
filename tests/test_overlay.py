"""La finestra: oggetti a terra che spariscono, click, inquadrature."""
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtWidgets = pytest.importorskip("PySide6.QtWidgets")
from PySide6.QtCore import QPointF

from animaldesk import config as cfg_mod
from animaldesk.overlay import MAX_ITEMS, PetOverlay
from animaldesk.pet import Effect, Stats
from animaldesk.props import Bowl, Item
from animaldesk.skin import SkinSet


@pytest.fixture(scope="module")
def app():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture()
def ov(app):
    skin = SkinSet.load(cfg_mod.find_skin("golden-reale"))
    overlay = PetOverlay(app.primaryScreen(), 120, 1.0, Stats(), skin=skin, props_ttl=60.0)
    overlay._timer.stop()
    overlay.pet.set_state("sit", 9999.0)
    yield overlay
    overlay.deleteLater()


def _ticks(ov, seconds):
    for _ in range(int(seconds * 30)):
        ov._tick()


class _Press:
    def __init__(self, x, y):
        self._p, self.accepted = QPointF(x, y), False

    def position(self):
        return self._p

    def button(self):
        from PySide6.QtCore import Qt
        return Qt.LeftButton

    def accept(self):
        self.accepted = True

    def ignore(self):
        self.accepted = False


def test_figura_intera_di_default_e_primo_piano_a_scelta(ov):
    assert ov.pet.full and ov.pet.bust and ov.pet.views == {"busto", "seduto", "serio", "dietro"}
    tall = ov.dog_rect().height()
    ov.set_framing("busto")
    ov.pet.set_state("sit", 9999.0)              # fermo: niente azioni a caso durante la verifica
    _ticks(ov, 1.5)
    assert not ov.pet.full and ov.skin.cur == "busto"
    assert ov.dog_rect().height() < tall
    ov.set_framing("intera")
    ov.pet.set_state("sit", 9999.0)
    _ticks(ov, 1.5)
    assert ov.pet.full and ov.skin.cur == "seduto"


def test_il_ricordino_resta_qualche_minuto_poi_sparisce(ov):
    ov.pet.effects.append(Effect("poop", ov.pet.x + 80, ov.ground()))
    ov._tick()
    assert [i.kind for i in ov.items] == ["poop"]
    _ticks(ov, 30)
    assert len(ov.items) == 1, "a meta' del tempo c'e' ancora"
    assert not ov.grab().isNull()
    _ticks(ov, 31)
    assert ov.items == []


def test_con_ttl_zero_non_sparisce_mai(ov):
    ov.props_ttl = 0.0
    ov._add_item(Item("poop", 200.0, ov.ground(), resting=True))
    _ticks(ov, 70)
    assert len(ov.items) == 1


def test_palla_e_ciotola_spariscono_da_sole(ov):
    ov.throw_ball()
    ov.pet.set_state("sit", 9999.0)              # fermo: nessuno tocca la palla
    ov.bowl = Bowl(x=300.0, y=ov.ground())
    _ticks(ov, 30)
    assert ov.ball is not None and ov.ball.resting and ov.bowl is not None
    _ticks(ov, 45)
    assert ov.ball is None and ov.bowl is None


def test_click_sul_ricordino_lo_raccoglie(ov):
    ov._add_item(Item("poop", 220.0, ov.ground(), size=20.0, resting=True))
    press = _Press(220.0, ov.ground() - 12.0)
    ov.mousePressEvent(press)
    assert press.accepted and ov.items == [] and not ov.dragging
    assert any(p.kind == "star" for p in ov.particles.items)


def test_click_sulla_palla_ferma_la_rilancia(ov):
    ov.throw_ball()
    ov.pet.set_state("sit", 9999.0)
    _ticks(ov, 6)
    ball = ov.ball
    assert ball.resting
    ball.delivered = True
    ov.mousePressEvent(_Press(ball.x, ball.y - ball.radius))
    assert not ball.resting and not ball.delivered and ball.vy < 0


def test_il_biscotto_viene_mangiato(ov):
    import random

    random.seed(7)                      # niente estrazioni sfortunate (es. sonno appena lanciato)
    ov.pet.stats.energia = 90.0
    ov.pet.set_state("idle", 0.1)
    ov.command("treat")
    assert [i.kind for i in ov.items] == ["treat"]
    hunger = ov.pet.stats.fame = 40.0
    _ticks(ov, 14)
    assert ov.items == [] and ov.pet.stats.fame < hunger


def test_mai_troppi_oggetti_e_pulisci_tutto(ov):
    for k in range(MAX_ITEMS + 5):
        ov._add_item(Item("poop", 100.0 + k * 20, ov.ground(), resting=True))
    assert len(ov.items) == MAX_ITEMS
    ov.command("clean")
    assert ov.items == [] and ov.ball is None


def test_quando_e_via_non_si_clicca_e_non_si_vede(ov):
    ov.command("leave")
    _ticks(ov, 4.0)
    assert not ov.skin.visible
    assert not ov._hits_dog(QPointF(ov.pet.x, ov.pet.y - 20))
    assert ov.paint_rect().width() <= 1
    while ov.pet.state == "leave":
        ov._tick()
    _ticks(ov, 0.5)
    assert ov.skin.visible and ov.skin.cur == "seduto"


def test_ogni_azione_del_menu_disegna(ov):
    from animaldesk.app import PHOTO_ACTIONS

    for framing in ("intera", "busto"):
        ov.set_framing(framing)
        for _, action in PHOTO_ACTIONS:
            ov.command(action)
            _ticks(ov, 1.2)
            assert not ov.grab().isNull(), (framing, action)
