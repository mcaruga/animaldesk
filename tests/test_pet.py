import math
import random

import pytest

from animaldesk.pet import Pet, Stats, World


@pytest.fixture
def world():
    return World(left=0, right=1000, ground=700, cursor_x=500, cursor_y=400, scale=1.2)


def test_tutti_gli_stati_hanno_un_handler(world):
    pet = Pet()
    for state in ("idle", "walk", "run", "sit", "sleep", "bark", "jump", "dig",
                  "scratch", "spin", "roll", "pet", "chase", "fetch", "eat",
                  "dragged", "fall"):
        assert hasattr(pet, f"_do_{state}"), state
        pet.set_state(state, 1.0)
        pet.update(1 / 30, world)
        assert pet.pose is not None


def test_resta_dentro_lo_schermo(world):
    random.seed(7)
    pet = Pet()
    pet.y = world.ground
    for _ in range(6000):
        pet.update(1 / 30, world)
        assert world.left <= pet.x <= world.right
        assert pet.y <= world.ground + 1


def test_la_gravita_lo_riporta_a_terra(world):
    pet = Pet()
    pet.y = world.ground - 300
    pet.set_state("fall", 5.0)
    landed_at = None
    for i in range(120):
        pet.update(1 / 30, world)
        if pet.on_ground and pet.y == pytest.approx(world.ground):
            landed_at = i
            break          # dopo l'atterraggio puo' scegliere di saltare di nuovo
    assert landed_at is not None and landed_at < 40


def test_statistiche_limitate_e_sonno_recupera_energia(world):
    pet = Pet(stats=Stats(energia=5, fame=50, felicita=50))
    pet.set_state("sleep", 60.0)
    for _ in range(30 * 120):
        pet.update(1 / 30, world)
    assert pet.stats.energia > 5
    assert 0 <= pet.stats.energia <= 100
    assert 0 <= pet.stats.fame <= 100
    assert 0 <= pet.stats.felicita <= 100


def test_sceglie_di_dormire_se_esausto(world):
    pet = Pet(stats=Stats(energia=3, fame=0, felicita=50))
    assert pet.choose_behavior(world) == "sleep"


def test_sceglie_di_mangiare_se_affamato(world):
    pet = Pet(stats=Stats(energia=90, fame=95, felicita=50))
    assert pet.choose_behavior(world) == "eat"


def test_insegue_il_cursore(world):
    pet = Pet()
    pet.x = 100
    pet.set_state("chase", 10.0)
    for _ in range(90):
        pet.update(1 / 30, world)
    assert pet.x > 150
    assert pet.facing == 1


def test_riporta_la_palla(world):
    class FakeBall:
        x, y = 820.0, 700.0

    world.ball = FakeBall()
    pet = Pet()
    pet.x = 200
    pet.set_state("fetch", 25.0)
    for _ in range(30 * 8):
        pet.update(1 / 30, world)
        if pet.carrying_ball:
            break
    assert pet.carrying_ball


def test_la_posa_riflette_lo_stato(world):
    pet = Pet()
    pet.set_state("sit", 5.0)
    pose = pet.update(1 / 30, world)
    assert pose.sit == 1.0
    pet.set_state("sleep", 5.0)
    pose = pet.update(1 / 30, world)
    assert pose.lie == 1.0 and pose.eye_open == 0.0


BUST_STATES = ("sit", "sleep", "typing", "hide", "lick", "look", "tilt", "scratch",
               "squint", "boop", "tease", "bark")


@pytest.mark.parametrize("state", BUST_STATES)
def test_azioni_del_busto(world, state):
    random.seed(2)
    pet = Pet(bust=True)
    pet.y = world.ground
    pet.set_state(state, None)
    seen = set()
    for _ in range(30 * 12):
        pose = pet.update(1 / 30, world)
        seen.add(pet.state)
        assert -1.0 <= pose.yaw <= 1.0 and -1.0 <= pose.pitch <= 1.0
        assert 0.0 <= pose.tongue <= 1.0 and 0.0 <= pose.paws <= 1.0
        assert abs(pose.head_tilt) <= 17.0, "inclinazione eccessiva: deforma il viso"
        assert pet.y == pytest.approx(world.ground), "il busto non si stacca dal bordo"
    assert state in seen


def test_il_busto_non_salta_ne_rotola(world):
    random.seed(4)
    pet = Pet(bust=True)
    pet.y = world.ground
    seen = set()
    for _ in range(30 * 600):
        pet.update(1 / 30, world)
        seen.add(pet.state)
    assert not seen & {"jump", "roll", "spin", "dig", "run"}
    assert {"typing", "hide", "lick", "look", "tilt"} <= seen


def test_pose_delle_azioni_nuove(world):
    pet = Pet(bust=True)
    pet.y = world.ground
    pet.set_state("typing", 6.0)
    for _ in range(40):
        pose = pet.update(1 / 30, world)
    assert pose.prop == "keyboard" and pose.paws > 0.9 and pose.pitch > 0.4
    pet.set_state("hide", None)
    for _ in range(60):
        pose = pet.update(1 / 30, world)
    assert pose.sink > 1.0                      # del tutto nascosto
    pet.set_state("boop", 3.0)
    for _ in range(40):
        pose = pet.update(1 / 30, world)
    assert 0.2 < pose.tongue < 0.5              # solo la punta


# ------------------------------------------------------------ figura intera
def _full(**kw):
    return Pet(bust=True, full=True, views=("busto", "seduto", "serio", "dietro"), **kw)


def _run(pet, world, seconds, collect=None):
    for _ in range(int(seconds * 30)):
        pet.update(1 / 30, world)
        if collect is not None:
            collect.extend(pet.effects)
        pet.effects.clear()


def test_la_figura_intera_non_scivola(world):
    random.seed(3)
    pet = _full()
    pet.x, pet.y = 500.0, world.ground
    for state in ("walk", "run", "idle", "sit", "look", "bark"):
        pet.set_state(state, 2.0)
        x0 = pet.x
        _run(pet, world, 1.5)
        assert pet.x == x0, state
    for _ in range(400):                       # e da sola non sceglie mai di camminare
        assert pet.choose_behavior(world) not in ("walk", "run", "chase", "jump", "roll", "spin", "dig")


def test_spostarsi_vuol_dire_andare_via_di_spalle_e_tornare(world):
    pet = _full()
    pet.x, pet.y = 200.0, world.ground
    pet.set_state("chase", 4.0)
    world.cursor_x = 800.0
    seen = set()
    for _ in range(120):
        pet.update(1 / 30, world)
        if pet.pose.away > 0.3:
            seen.add(pet.pose.view)
        if pet._trav is None and pet.x != 200.0:
            break
    assert "dietro" in seen
    assert abs(pet.x - 800.0) < 1.0 and pet.pose.away < 0.05


def test_me_ne_vado_e_poi_torna_altrove(world):
    random.seed(11)
    pet = _full()
    pet.x, pet.y = 500.0, world.ground
    pet.set_state("leave")
    said, max_away, views = [], 0.0, set()
    while pet.state == "leave":
        pet.update(1 / 30, world)
        said += [e.text for e in pet.effects if e.kind == "bubble"]
        pet.effects.clear()
        max_away = max(max_away, pet.pose.away)
        views.add(pet.pose.view)
    assert max_away > 0.99 and "dietro" in views
    assert abs(pet.x - 500.0) > 100, "torna in un punto diverso"
    assert pet.state == "idle" and len(said) == 2      # saluta quando va e quando torna


def test_me_ne_vado_senza_foto_di_spalle_scende_sotto_il_bordo(world):
    pet = Pet(bust=True)                                # pelle a una sola foto (primo piano)
    pet.y = world.ground
    pet.set_state("leave")
    _run(pet, world, 3.5)
    assert pet.pose.sink > 1.0 and pet.pose.away == 0.0


def test_non_ho_voglia_usa_la_faccia_seria(world):
    pet = _full()
    pet.set_state("nope")
    _run(pet, world, 3.0)
    p = pet.pose
    assert p.view == "serio" and abs(p.yaw) > 0.3 and p.eye_open < 0.75
    _run(pet, world, 6.0)
    assert pet.state != "nope"


def test_fai_la_cacca_ne_lascia_una_sola(world):
    random.seed(2)
    pet = _full()
    pet.x, pet.y = 500.0, world.ground
    pet.set_state("poop")
    fx = []
    _run(pet, world, 2.0, fx)
    assert pet.pose.view == "serio" and pet.pose.squash < 1.0     # accucciato, serissimo
    _run(pet, world, 5.5, fx)
    poops = [e for e in fx if e.kind == "poop"]
    assert len(poops) == 1 and abs(poops[0].x - 500.0) > 30
    assert any(e.kind == "dirt" for e in fx)
    assert pet.state in ("idle", "leave")


def test_azioni_da_primo_piano_chiedono_il_busto(world):
    pet = _full()
    for state in ("typing", "lick", "hide", "sleep", "boop", "tease"):
        pet.set_state(state, 3.0)
        pet.update(1 / 30, world)
        assert pet.pose.view == "busto", state
    pet.set_state("tilt", 3.0)
    pet.update(1 / 30, world)
    assert pet.pose.view == "" and pet.pose.sink == 0.0


def test_figura_intera_senza_primo_piano(world):
    pet = Pet(bust=True, full=True, views=("seduto", "dietro"))
    pet.set_state("hide")
    _run(pet, world, 2.0)
    assert pet.pose.sink == 0.0 and pet.pose.away > 0.9      # con la foto di spalle: si allontana
    pet = Pet(bust=True, full=True, views=("seduto",))
    pet.set_state("hide")
    _run(pet, world, 2.0)
    assert pet.pose.sink > 0.9 and pet.pose.away == 0.0      # senza: scende sotto il bordo
    for _ in range(300):
        assert pet.choose_behavior(world) not in ("typing", "lick")


def test_biscotto_lo_raggiunge_e_lo_mangia(world):
    for pet in (_full(), Pet(bust=True)):
        pet.x, pet.y = 300.0, world.ground
        pet.stats.fame = 50.0
        world.treat = type("T", (), {"x": 700.0})()
        assert pet.choose_behavior(world) == "treat"
        pet.set_state("treat")
        fx = []
        _run(pet, world, 12.0, fx)
        assert any(e.kind == "eat_treat" for e in fx)
        assert abs(pet.x - 700.0) < 120 and pet.stats.fame < 50.0
    world.treat = None


def test_palla_in_volo_poi_presa_e_riportata(world):
    for pet in (_full(), Pet(bust=True)):
        pet.x, pet.y = 200.0, world.ground
        ball = type("B", (), {"x": 600.0, "resting": False, "delivered": False})()
        world.ball, world.cursor_x = ball, 250.0
        pet.set_state("fetch", 25.0)
        _run(pet, world, 1.0)
        assert pet.x == 200.0 and not pet.carrying_ball        # finche' rimbalza la guarda
        ball.resting = True
        carried = False
        for _ in range(600):
            pet.update(1 / 30, world)
            carried = carried or pet.carrying_ball
            if any(e.kind == "drop_ball" for e in pet.effects):
                ball.delivered = True                  # come fa la finestra quando la posa a terra
                break
            pet.effects.clear()
        assert carried and ball.delivered and not pet.carrying_ball
        assert all(pet.choose_behavior(world) != "fetch" for _ in range(200))
    world.ball = None


def test_senza_ciotola_chiede_ma_non_mangia(world):
    pet = _full()
    pet.stats.fame = 95.0
    world.has_bowl = False
    assert pet.choose_behavior(world) == "idle"
    pet.stats.fame = 20.0
    assert all(pet.choose_behavior(world) != "eat" for _ in range(300))
    world.has_bowl = True


def test_il_gatto_miagola(world):
    cat = Pet(bust=True, species="gatto")
    cat.set_state("bark")
    text = [e.text for e in cat.effects if e.kind == "bubble"][0]
    assert text[0] == "M"
    cat.effects.clear()
    cat.say("leave")                                   # il resto e' in comune
    assert cat.effects[0].text
