import pytest

from animaldesk.props import DEFAULT_TTL, FADE_TIME, Item, fade,\
     Ball, Bowl, Particles


def test_la_palla_rimbalza_e_si_ferma():
    ball = Ball(x=100, y=100, vx=250, vy=-150)
    for _ in range(60 * 12):
        ball.update(1 / 60, 0, 800, 600)
    assert ball.resting
    assert ball.y == 600
    assert 0 <= ball.x <= 800


def test_la_palla_non_esce_dai_bordi():
    ball = Ball(x=10, y=100, vx=-900, vy=0)
    for _ in range(200):
        ball.update(1 / 60, 0, 800, 600)
    assert ball.x >= ball.radius


def test_le_particelle_muoiono_e_restano_sotto_il_limite():
    ps = Particles(limit=20)
    for _ in range(100):
        ps.spawn("heart", 10, 10)
    assert len(ps.items) <= 20
    for _ in range(200):
        ps.update(1 / 30)
    assert ps.items == []


def test_ogni_tipo_di_particella_e_supportato():
    ps = Particles()
    for kind in Particles.PRESETS:
        ps.spawn(kind, 0, 0, "x")
    ps.update(1 / 30)
    assert len(ps.items) == len(Particles.PRESETS)


def test_gli_oggetti_a_terra_sbiadiscono_e_spariscono():
    assert DEFAULT_TTL >= 120, "devono restare qualche minuto"
    assert fade(0.0, 180.0) == 1.0 and fade(170.0, 180.0) == 1.0
    assert 0.0 < fade(180.0 - FADE_TIME / 2, 180.0) < 1.0
    assert fade(180.0, 180.0) == 0.0 and fade(999.0, 180.0) == 0.0
    assert fade(9999.0, 0.0) == 1.0, "ttl 0 = non spariscono mai"


def test_il_biscotto_cade_e_si_ferma():
    item = Item("treat", x=100.0, y=0.0, vx=120.0, vy=-80.0)
    for _ in range(300):
        item.update(1 / 30, 0.0, 400.0, 300.0)
    assert item.resting and item.y == 300.0 and 0.0 < item.x < 400.0
    assert item.age == pytest.approx(10.0, abs=0.1)


def test_la_palla_invecchia_solo_da_ferma():
    ball = Ball(x=50.0, y=0.0, vx=40.0)
    for _ in range(20):
        ball.update(1 / 30, 0.0, 400.0, 300.0)
    assert ball.age == 0.0
    ball.resting = True
    for _ in range(30):
        ball.update(1 / 30, 0.0, 400.0, 300.0)
    assert ball.age == pytest.approx(1.0, abs=0.05)
