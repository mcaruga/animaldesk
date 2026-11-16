from animaldesk.props import Ball, Bowl, Particles


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
