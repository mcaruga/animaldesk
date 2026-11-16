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
