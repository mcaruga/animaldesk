"""Cervello del cane: macchina a stati, fisica e statistiche. Zero dipendenze Qt."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Callable

from .render import Pose

GRAVITY = 1400.0          # px/s^2
WALK_SPEED = 55.0         # px/s a scala 1
RUN_SPEED = 150.0
DRAG_FLAIL = 1.0
TRAVEL_OUT = 1.15         # figura intera: secondi per andare via di spalle...
TRAVEL_IN = 0.9           # ...e per ricomparire nel punto nuovo
CLOSE_UPS = ("typing", "lick", "hide", "sleep", "boop", "tease")   # azioni da primo piano
# anche con le zampe animate, queste restano piu' belle da vicino (se c'e' la foto in primo piano)
PREFER_CLOSE = ("typing", "sleep")


@dataclass
class World:
    """Quello che il cane sa del mondo esterno, aggiornato ogni frame."""

    left: float = 0.0
    right: float = 1920.0
    ground: float = 1000.0
    cursor_x: float = 0.0
    cursor_y: float = 0.0
    ball: object | None = None     # la palla, anche in volo (ha .x e .resting)
    bowl_x: float = 0.0
    has_bowl: bool = True          # c'e' una ciotola con del cibo
    treat: object | None = None    # biscotto a terra piu' vicino (ha .x)
    scale: float = 1.2        # size / 100


@dataclass
class Stats:
    energia: float = 100.0
    fame: float = 0.0
    felicita: float = 80.0

    def clamp(self) -> None:
        self.energia = max(0.0, min(100.0, self.energia))
        self.fame = max(0.0, min(100.0, self.fame))
        self.felicita = max(0.0, min(100.0, self.felicita))


@dataclass
class Effect:
    """Richiesta verso il livello grafico (particelle, fumetti, suoni)."""

    kind: str
    x: float = 0.0
    y: float = 0.0
    text: str = ""


BUBBLES = {
    "bark": ["Woof!", "Bau!", "Woof woof!"],
    "happy": ["<3", "Yay!", "*scodinzola*"],
    "hungry": ["Ho fame...", "Crocchette?", "*uggiola*"],
    "sleepy": ["Zzz...", "*sbadiglio*"],
    "dragged": ["Uh?!", "Woah!", "*zampe in aria*"],
    "fetch": ["La palla!", "Mia!", "Woof!"],
    "hide": ["Cucu'!", "Trovato!", "Bu!"],
    "tease": ["Prendimi!", "Gne gne!", "Dai, gioca!"],
    "tilt": ["Eh?", "Mh?", "Cosa?"],
    "leave": ["Me ne vado.", "Ciao eh.", "Io vado!"],
    "back": ["Rieccomi!", "Sono tornato!", "Mi sei mancato?"],
    "nope": ["Non ho voglia...", "Dopo.", "Adesso no."],
    "sigh": ["Uff.", "*sospiro*", "Mh."],
    "poop": ["Un attimo...", "Non guardare!", "Occupato."],
    "relief": ["Fatto!", "Ahh...", "Molto meglio."],
    "rest": ["Che relax.", "Qui sto bene.", "*si stiracchia*"],
    "treat": ["Biscotto!", "Gnam!", "Ancora?"],
}

# Cio' che cambia per specie: tutto il resto e' in comune.
SPECIES_BUBBLES = {
    "gatto": {
        "bark": ["Miao!", "Meow!", "Mrrr!"],
        "happy": ["Purr...", "<3", "*fa le fusa*"],
        "hungry": ["Miaoo...", "Croccantini?", "*fissa la ciotola*"],
        "fetch": ["Mia!", "Presa!", "Mrr!"],
        "tease": ["Prendimi!", "Mrrr!", "Dai, gioca!"],
        "treat": ["Bocconcino!", "Gnam!", "Ancora?"],
    },
}

KEYS = list("woofbauciao!?") + ["zzz", "<3"]


class Pet:
    """Il golden retriever. x = centro, y = zampe (suolo)."""

    def __init__(self, stats: Stats | None = None, speed: float = 1.0, bust: bool = False,
                 full: bool = False, views: tuple[str, ...] | set[str] = (), species: str = "cane",
                 legs: bool = False) -> None:
        self.bust = bust              # pelle fotografica: niente salti, capriole, scavi
        self.full = full              # figura intera: non cammina, va via di spalle e ricompare
        self.legs = legs              # la figura intera ha le zampe animabili: niente primo piano per le azioni
        self.views = set(views)
        self.species = species
        self._trav: list | None = None    # spostamento in corso [tempo, x d'arrivo, gia' spostato]
        self._side = 1
        self._moved: bool | None = False
        self.x = 400.0
        self.y = 600.0
        self.vx = 0.0
        self.vy = 0.0
        self.facing = 1
        self.speed = speed
        self.stats = stats or Stats()
        self.state = "idle"
        self.t = 0.0                 # tempo nello stato corrente
        self.duration = 2.0
        self.leg_phase = 0.0
        self.tail_phase = 0.0
        self.blink = 1.0
        self.blink_timer = random.uniform(2.0, 5.0)
        self.spin = 0.0
        self.squash = 1.0
        self.pose = Pose()
        self.carrying_ball = False
        self.effects: list[Effect] = []
        self.on_ground = True
        self._emit_timer = 0.0
        self._bark_left = 0
        self._stat_timer = 0.0

    # ---------------------------------------------------------------- utility
    def emit(self, kind: str, dx: float = 0.0, dy: float = -40.0, text: str = "") -> None:
        self.effects.append(Effect(kind, self.x + dx, self.y + dy, text))

    def say(self, group: str) -> None:
        lines = SPECIES_BUBBLES.get(self.species, {}).get(group) or BUBBLES[group]
        self.emit("bubble", 0.0, -70.0, random.choice(lines))

    @property
    def close(self) -> bool:
        """C'e' un primo piano da cui affacciarsi (zampe sul bordo, nascondino...)?"""
        return not self.full or "busto" in self.views

    def _goto(self, dt: float, x: float, world: World, tol: float, speed: float = RUN_SPEED) -> bool:
        """Raggiunge x; True quando c'e'. Il busto scorre lungo il bordo; la figura
        intera non ha foto di camminata: va via di spalle e ricompare nel punto nuovo."""
        if not self.full:
            dx = x - self.x
            if abs(dx) <= tol:
                self.vx = 0.0
                return True
            self.vx = math.copysign(speed * self.speed, dx)
            return False
        if self._trav is None:
            if abs(x - self.x) <= tol:
                return True
            self._trav = [0.0, x, False]
        tr = self._trav
        tr[0] += dt * max(0.7, min(1.6, self.speed))
        self.leg_phase += dt * 9.0
        if tr[0] >= TRAVEL_OUT and not tr[2]:
            tr[2] = True
            margin = 60.0 * world.scale
            self.x = max(world.left + margin, min(world.right - margin, tr[1]))
        if tr[0] >= TRAVEL_OUT + TRAVEL_IN:
            self._trav = None
            return True
        return False

    def set_state(self, state: str, duration: float | None = None) -> None:
        self.state = state
        self.t = 0.0
        self.duration = duration if duration is not None else random.uniform(2.0, 5.0)
        self._emit_timer = 0.0
        self._trav = None
        enter = getattr(self, f"_enter_{state}", None)
        if enter:
            enter()

    # ------------------------------------------------------------------ stati
    def _enter_walk(self) -> None:
        self.facing = random.choice((-1, 1))
        self.vx = WALK_SPEED * self.speed * self.facing
        self.duration = random.uniform(2.0, 6.0)

    def _enter_run(self) -> None:
        self.facing = random.choice((-1, 1))
        self.vx = RUN_SPEED * self.speed * self.facing
        self.duration = random.uniform(1.2, 2.8)

    def _enter_bark(self) -> None:
        self._bark_left = random.randint(2, 3)
        self.duration = 0.45 * self._bark_left + 0.3
        self.say("bark")
        self.stats.felicita += 2

    def _enter_sleep(self) -> None:
        self.duration = random.uniform(12.0, 28.0)
        self.vx = 0.0
        self.say("sleepy")

    def _enter_jump(self) -> None:
        self.vy = -520.0 * math.sqrt(self.speed)
        self.on_ground = False
        self.duration = 3.0

    def _enter_dig(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(2.5, 4.5)

    def _enter_spin(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(1.6, 3.0)

    def _enter_roll(self) -> None:
        self.vx = 0.0
        self.duration = 1.6

    def _enter_pet(self) -> None:
        self.vx = 0.0
        self.duration = 2.4
        self.stats.felicita += 12
        self.say("happy")

    def _enter_eat(self) -> None:
        self.duration = 4.0

    def _enter_tilt(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(2.2, 3.4)
        self._side = random.choice((-1, 1))
        if random.random() < 0.5:
            self.say("tilt")

    def _enter_look(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(4.0, 5.5)
        self._side = random.choice((-1, 1))

    def _enter_squint(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(2.8, 4.2)
        self.stats.felicita += 3

    def _enter_boop(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(2.4, 3.6)

    def _enter_tease(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(3.2, 4.4)
        self.say("tease")
        self.stats.felicita += 4

    def _enter_typing(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(6.0, 9.0)

    def _enter_hide(self) -> None:
        self.vx = 0.0
        self.duration = 6.4
        self._moved = False

    def _enter_lick(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(4.0, 5.5)

    def _enter_scratch(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(2.4, 3.4)

    def _enter_leave(self) -> None:
        """Me ne vado: ti guarda, si gira, se ne va. Poi torna, da un'altra parte."""
        self.vx = 0.0
        self.duration = random.uniform(9.0, 13.0)
        self._side = random.choice((-1, 1))
        self._moved = False
        self.say("leave")

    def _enter_nope(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(5.5, 7.5)
        self._side = random.choice((-1, 1))
        self._moved = False
        self.say("nope")

    def _enter_rest(self) -> None:
        self.vx = 0.0
        self.duration = random.uniform(9.0, 15.0)
        self._side = random.choice((-1, 1))
        self.say("rest")

    def _do_rest(self, dt: float, world: World) -> None:
        self.vx = 0.0
        if self.t >= self.duration:
            self.set_state("idle", 2.0)

    def _enter_poop(self) -> None:
        self.vx = 0.0
        self.duration = 7.2
        self._side = random.choice((-1, 1))
        self._moved = False
        self.say("poop")

    def _enter_treat(self) -> None:
        self.duration = 14.0
        self._moved = False

    def _enter_dragged(self) -> None:
        self.vx = self.vy = 0.0
        self.say("dragged")

    # ------------------------------------------------------------- aggiorna
    def update(self, dt: float, world: World) -> Pose:
        self.t += dt
        self._update_stats(dt)
        handler: Callable[[float, World], None] = getattr(self, f"_do_{self.state}", self._do_idle)
        handler(dt, world)

        if self.state not in ("dragged",):
            self._physics(dt, world)
        self._blink(dt)
        self.tail_phase += dt * (9.0 + self.stats.felicita / 12.0)
        self.pose = self._build_pose()
        return self.pose

    def _update_stats(self, dt: float) -> None:
        self._stat_timer += dt
        if self._stat_timer < 1.0:
            return
        step = self._stat_timer / 60.0
        self._stat_timer = 0.0
        s = self.stats
        if self.state == "sleep":
            s.energia += 9.0 * step
            s.fame += 0.25 * step
        else:
            cost = {"run": 5.0, "walk": 2.2, "chase": 4.5, "fetch": 4.0, "dig": 2.5}.get(self.state, 1.0)
            s.energia -= cost * step
            s.fame += 1.3 * step
        s.felicita -= 0.8 * step
        if s.fame > 70:
            s.felicita -= 0.6 * step
        s.clamp()

    def _physics(self, dt: float, world: World) -> None:
        if self.full:
            self.vx = 0.0                 # si sposta solo con _goto (via di spalle e ritorno)
        self.x += self.vx * dt
        if not self.on_ground or self.vy != 0.0:
            self.vy += GRAVITY * dt
            self.y += self.vy * dt
            if self.y >= world.ground:
                self.y = world.ground
                if self.vy > 240.0:
                    self.squash = 0.72
                    self.emit("dust", 0, -4)
                self.vy = 0.0
                self.on_ground = True
                if self.state == "fall":
                    self.set_state("idle", 1.0)
        margin = 50.0 * world.scale
        if self.x < world.left + margin:
            self.x = world.left + margin
            self.vx = abs(self.vx)
            self.facing = 1
        elif self.x > world.right - margin:
            self.x = world.right - margin
            self.vx = -abs(self.vx)
            self.facing = -1
        if self.vx:
            self.facing = 1 if self.vx > 0 else -1
            self.leg_phase += dt * (abs(self.vx) / (14.0 * world.scale))
        self.squash += (1.0 - self.squash) * min(1.0, dt * 9.0)

    def _blink(self, dt: float) -> None:
        self.blink_timer -= dt
        if self.blink_timer <= 0:
            self.blink_timer = random.uniform(2.5, 6.0)
            self.blink = 0.0
        self.blink = min(1.0, self.blink + dt * 7.0)

    # ------------------------------------------------- comportamenti concreti
    def _do_idle(self, dt: float, world: World) -> None:
        self.vx = 0.0
        self.leg_phase += dt * 0.6
        if self.t >= self.duration:
            self.set_state(self.choose_behavior(world))

    def _do_walk(self, dt: float, world: World) -> None:
        if self.t >= self.duration:
            self.set_state("idle", random.uniform(1.0, 3.0))

    def _do_run(self, dt: float, world: World) -> None:
        if self.t >= self.duration:
            self.set_state("idle", random.uniform(0.8, 2.0))

    def _do_sit(self, dt: float, world: World) -> None:
        self.vx = 0.0
        if self.t >= self.duration:
            self.set_state("idle", 1.5)

    def _do_sleep(self, dt: float, world: World) -> None:
        self.vx = 0.0
        self._emit_timer -= dt
        if self._emit_timer <= 0:
            self._emit_timer = 1.4
            self.emit("zzz", (46.0 if self.bust else 18.0) * self.facing, -78.0 if self.bust else -46.0)
        # si sveglia da solo solo dopo un minimo di riposo (altrimenti il
        # comando "dormi" del menu verrebbe annullato subito a energia piena)
        if self.t >= self.duration or (self.stats.energia > 97 and self.t > 5.0):
            self.set_state("idle", 2.0)

    def _do_bark(self, dt: float, world: World) -> None:
        self.vx = 0.0
        if self.t >= self.duration:
            self.set_state("idle", 1.2)

    def _do_jump(self, dt: float, world: World) -> None:
        if self.on_ground and self.t > 0.2:
            self.set_state("idle", 0.8)

    def _do_dig(self, dt: float, world: World) -> None:
        self.vx = 0.0
        self.leg_phase += dt * 16.0
        self._emit_timer -= dt
        if self._emit_timer <= 0:
            self._emit_timer = 0.16
            self.emit("dirt", -22.0 * self.facing, -6.0)
        if self.t >= self.duration:
            self.set_state("idle", 1.5)

    def _do_scratch(self, dt: float, world: World) -> None:
        self.vx = 0.0
        self.leg_phase += dt * 24.0
        if self.t >= self.duration:
            self.set_state("idle", 1.2)

    def _do_spin(self, dt: float, world: World) -> None:
        """Si rincorre la coda."""
        self.vx = 0.0
        self.spin = (self.spin + dt * 520.0) % 360.0
        self.leg_phase += dt * 18.0
        if self.t >= self.duration:
            self.spin = 0.0
            self.stats.felicita += 4
            self.set_state("idle", 1.0)

    def _do_roll(self, dt: float, world: World) -> None:
        self.vx = 0.0
        self.spin = 360.0 * min(1.0, self.t / self.duration) * self.facing
        if self.t >= self.duration:
            self.spin = 0.0
            self.stats.felicita += 5
            self.emit("heart", 0, -50)
            self.set_state("idle", 1.2)

    def _do_pet(self, dt: float, world: World) -> None:
        self.vx = 0.0
        self._emit_timer -= dt
        if self._emit_timer <= 0:
            self._emit_timer = 0.35
            self.emit("heart", random.uniform(-14, 14), -54)
        if self.t >= self.duration:
            self.set_state("idle", 1.0)

    def _do_chase(self, dt: float, world: World) -> None:
        """Insegue il puntatore del mouse."""
        if self.full:
            self._goto(dt, world.cursor_x, world, 230.0 * world.scale)
            if self.t >= self.duration and self._trav is None:
                self.set_state("idle", 1.0)
            return
        dx = world.cursor_x - self.x
        if abs(dx) > 26.0 * world.scale:
            self.vx = math.copysign(RUN_SPEED * 0.8 * self.speed, dx)
        else:
            self.vx = 0.0
            if (not self.bust and world.cursor_y < self.y - 60 * world.scale and self.on_ground
                    and random.random() < 0.05):
                self.set_state("jump")
                return
        if self.t >= self.duration:
            self.set_state("idle", 1.0)

    def _do_fetch(self, dt: float, world: World) -> None:
        ball = world.ball
        if ball is None:
            self.carrying_ball = False
            self.set_state("idle", 1.0)
            return
        if not self.carrying_ball:
            if not getattr(ball, "resting", True):
                self.vx = 0.0                       # la segue con gli occhi finche' rimbalza
            elif self._goto(dt, ball.x, world, (46.0 if self.full else 18.0) * world.scale):
                self.carrying_ball = True
                self.say("fetch")
                self.stats.felicita += 8
        elif self._goto(dt, world.cursor_x, world, (150.0 if self.full else 30.0) * world.scale,
                        WALK_SPEED * 1.6):
            self.carrying_ball = False
            self.emit("drop_ball", 0, -10)
            self.set_state("sit", 2.5)
            return
        if self.t >= 25.0 and self._trav is None:
            if self.carrying_ball:
                self.emit("drop_ball", 0, -10)
            self.carrying_ball = False
            self.set_state("idle", 1.0)

    def _do_eat(self, dt: float, world: World) -> None:
        if self.full:
            there = self._goto(dt, world.bowl_x, world, 105.0 * world.scale)
            if not there:
                self.t = min(self.t, 0.5)           # il pasto comincia quando arriva
        else:
            there = abs(world.bowl_x - self.x) <= 10.0 * world.scale or self.t >= self.duration * 0.6
            if not there:
                self.vx = math.copysign(WALK_SPEED * 1.3 * self.speed, world.bowl_x - self.x)
        if there:
            self.vx = 0.0
            self._emit_timer -= dt
            if self._emit_timer <= 0:
                self._emit_timer = 0.3
                self.emit("crumb", 16.0 * self.facing, -8)
                self.stats.fame -= 6
                self.stats.clamp()
        if self.t >= self.duration:
            self.stats.felicita += 5
            self.set_state("idle", 1.5)

    def _still(self, dt: float, world: World) -> None:
        """Azione sul posto: finisce allo scadere della durata."""
        self.vx = 0.0
        if self.t >= self.duration:
            self.set_state("idle", random.uniform(1.0, 2.2))

    _do_tilt = _do_look = _do_squint = _do_boop = _do_tease = _do_lick = _still

    def _do_leave(self, dt: float, world: World) -> None:
        self.vx = 0.0
        back = self.duration - 1.5
        if 0.9 < self.t < 3.1 or self.t > back:
            self.leg_phase += dt * 8.5                      # passo dondolante
        if self.t > 3.3 and self._moved is False:
            self._moved = True
            margin = 90.0 * world.scale
            lo, hi = world.left + margin, max(world.left + margin + 1, world.right - margin)
            for _ in range(6):                              # torna in un punto diverso
                x = random.uniform(lo, hi)
                if abs(x - self.x) > 160.0 * world.scale:
                    break
            self.x = x
        if self.t > back + 0.9 and self._moved is True:
            self._moved = None
            self.say("back")
            self.stats.felicita += 3
        if self.t >= self.duration:
            self.set_state("idle", 2.0)

    def _do_nope(self, dt: float, world: World) -> None:
        self.vx = 0.0
        if self.t > self.duration * 0.55 and self._moved is False:
            self._moved = True
            self.say("sigh")
        if self.t >= self.duration:
            self.set_state("idle", 2.5)

    def _do_poop(self, dt: float, world: World) -> None:
        self.vx = 0.0
        if self.t > 3.6 and self._moved is False:
            self._moved = True
            self.emit("poop", self._side * (58.0 if self.full else 66.0) * world.scale, 0.0)
            self.emit("dust", self._side * 50.0 * world.scale, -4.0)
            self.stats.felicita += 6
        if self.t > 4.5 and self._moved is True:
            self._moved = None
            self.say("relief")
        if 4.9 < self.t < 6.3:                              # due zampate di terra per coprire
            self.leg_phase += dt * 20.0
            self._emit_timer -= dt
            if self._emit_timer <= 0:
                self._emit_timer = 0.14
                self.emit("dirt", self._side * 30.0 * world.scale, -6.0)
        if self.t >= self.duration:
            # ...e spesso si allontana fischiettando
            self.set_state("leave" if random.random() < 0.55 else "idle")

    def _do_treat(self, dt: float, world: World) -> None:
        """Biscotto a terra: lo raggiunge e lo sgranocchia."""
        treat = world.treat
        if treat is None and self._moved is False:
            self.vx = 0.0
            if self.t > 2.5:                    # sta ancora cadendo: lo aspetta, poi lascia perdere
                self.set_state("idle", 1.0)
            return
        if self._moved is False:
            if self._goto(dt, treat.x, world, (125.0 if self.full else 16.0) * world.scale, WALK_SPEED * 1.8):
                self._moved = True
                self.t = 0.0
                self.duration = 2.6
            elif self.t >= 13.0 and self._trav is None:
                self.set_state("idle", 1.0)
            return
        self.vx = 0.0
        self._emit_timer -= dt
        if self._emit_timer <= 0:
            self._emit_timer = 0.28
            self.emit("crumb", 14.0 * self.facing, -8)
        if self.t >= self.duration:
            self.emit("eat_treat", 0.0, 0.0)
            self.stats.fame -= 14
            self.stats.felicita += 7
            self.stats.clamp()
            self.say("treat")
            self.set_state("idle", 1.5)

    def _do_typing(self, dt: float, world: World) -> None:
        self.vx = 0.0
        self._emit_timer -= dt
        if self._emit_timer <= 0 and 0.6 < self.t < self.duration - 0.5:
            self._emit_timer = random.uniform(0.16, 0.34)
            self.emit("letter", random.uniform(-38, 38) * world.scale, -18 * world.scale,
                      random.choice(KEYS))
        if self.t >= self.duration:
            self.set_state("idle", 1.5)

    def _do_hide(self, dt: float, world: World) -> None:
        """Nascondino: sparisce sotto il bordo, riappare altrove e fa capolino."""
        self.vx = 0.0
        if self.t > 1.6 and not self._moved:
            self._moved = True
            margin = 90.0 * world.scale
            self.x = random.uniform(world.left + margin, max(world.left + margin + 1, world.right - margin))
        if self.t > 5.0 and self._moved is True:
            self._moved = None
            self.say("hide")
            self.stats.felicita += 6
        if self.t >= self.duration:
            self.set_state("idle", 1.5)

    def _do_dragged(self, dt: float, world: World) -> None:
        self.leg_phase += dt * 14.0

    def _do_fall(self, dt: float, world: World) -> None:
        self.on_ground = False

    # ------------------------------------------------------------- decisioni
    def choose_behavior(self, world: World) -> str:
        s = self.stats
        if s.energia < 14:
            return "sleep"
        if world.treat is not None:
            return "treat"
        if s.fame > 82:
            self.say("hungry")
            return "eat" if world.has_bowl else "idle"
        can_fetch = (world.ball is not None and getattr(world.ball, "resting", True)
                     and not getattr(world.ball, "delivered", False) and not self.carrying_ball)
        if self.bust:
            weights = {
                "walk": 20.0, "sit": 12.0, "idle": 8.0, "look": 12.0, "tilt": 12.0,
                "squint": 8.0, "boop": 8.0, "tease": 5.0, "typing": 7.0, "hide": 6.0,
                "lick": 7.0, "scratch": 6.0, "bark": 6.0, "chase": 4.0, "sleep": 3.0, "eat": 2.0,
                "nope": 3.0, "leave": 2.5, "poop": 1.0, "rest": 0.0,
            }
            if "sdraiato" in self.views:
                weights["rest"] = 7.0
            if self.full:                      # niente camminata: resta piu' spesso a guardarsi intorno
                weights.update(walk=0.0, chase=0.0, idle=16.0, sit=8.0, look=14.0)
                if not self.close and not self.legs:
                    for k in ("typing", "lick"):
                        weights[k] = 0.0
            weights["sleep"] += max(0.0, (40 - s.energia) * 0.6)
            weights["eat"] += max(0.0, (s.fame - 45) * 0.5)
            if not world.has_bowl:
                weights["eat"] = 0.0
            if s.energia < 35:
                weights["nope"] *= 3.0
            if s.felicita > 70:
                for k in ("tease", "boop", "squint", "hide"):
                    weights[k] *= 1.5
            if can_fetch:
                weights["fetch"] = 40.0
            names = list(weights)
            return random.choices(names, weights=[weights[n] for n in names])[0]
        weights = {
            "walk": 30.0,
            "sit": 14.0,
            "idle": 10.0,
            "bark": 7.0,
            "run": 9.0,
            "dig": 6.0,
            "scratch": 6.0,
            "spin": 5.0,
            "roll": 4.0,
            "jump": 5.0,
            "chase": 6.0,
            "sleep": 3.0,
            "eat": 2.0,
        }
        weights["sleep"] += max(0.0, (40 - s.energia) * 0.6)
        weights["eat"] += max(0.0, (s.fame - 45) * 0.5)
        if s.energia < 35:
            for k in ("run", "spin", "jump", "chase"):
                weights[k] *= 0.3
        if s.felicita > 70:
            for k in ("spin", "roll", "jump", "bark"):
                weights[k] *= 1.6
        if not world.has_bowl:
            weights["eat"] = 0.0
        if can_fetch:
            weights["fetch"] = 40.0
        names = list(weights)
        return random.choices(names, weights=[weights[n] for n in names])[0]

    # ------------------------------------------------------------------ posa
    def _build_pose(self) -> Pose:
        st = self.state
        moving = abs(self.vx) > 1.0
        p = Pose(facing=self.facing, leg_phase=self.leg_phase, spin=self.spin, squash=self.squash)
        p.eye_open = self.blink
        p.tail_phase = self.tail_phase
        p.tail_wag = 8.0 + self.stats.felicita * 0.18
        p.body_bob = math.sin(self.leg_phase * 2) * (1.6 if moving else 0.0) + math.sin(self.t * 2.2) * 0.6
        p.leg_swing = 1.0 if moving else 0.0

        if st == "run" or (st in ("chase", "fetch") and abs(self.vx) > 90):
            p.leg_swing = 1.5
            p.body_tilt = -5.0 * self.facing * 0 - 5.0
            p.tongue = 0.9
            p.mouth_open = 0.45
            p.ear_flop = 0.8
            p.tail_wag = 26.0
        elif st == "sit":
            p.sit = 1.0
            p.tail_angle = -10.0
            p.leg_swing = 0.0
        elif st == "sleep":
            p.lie = 1.0
            p.eye_open = 0.0
            p.tail_wag = 3.0
            p.head_drop = 0.25
            p.shadow = 0.55
        elif st == "bark":
            beat = (self.t * 2.4) % 1.0
            p.mouth_open = 1.0 if beat < 0.45 else 0.15
            p.head_tilt = -10.0 * (1.0 - beat)
            p.tail_wag = 24.0
        elif st == "dig":
            p.head_drop = 0.9
            p.leg_swing = 1.1
            p.body_tilt = 5.0
        elif st == "scratch":
            p.sit = 1.0
            p.flail = 0.5
            p.head_tilt = 12.0
            p.eye_open = 0.35
        elif st == "spin":
            p.leg_swing = 1.2
            p.tail_wag = 30.0
            p.mouth_open = 0.4
            p.tongue = 0.6
        elif st == "roll":
            p.lie = 0.75
            p.eye_open = 0.4
            p.flail = 0.6
            p.shadow = 0.4
        elif st == "pet":
            p.eye_open = 0.2
            p.blush = 1.0
            p.tail_wag = 34.0
            p.mouth_open = 0.35
            p.tongue = 0.9
        elif st == "eat":
            if abs(self.vx) < 1.0:
                p.head_drop = 1.0
                p.mouth_open = 0.5 + 0.4 * math.sin(self.t * 14)
        elif st == "dragged":
            p.flail = DRAG_FLAIL
            p.shadow = 0.0
            p.mouth_open = 0.5
            p.body_tilt = -8.0
            p.ear_flop = 1.0
        elif st in ("jump", "fall"):
            p.shadow = 0.4
            p.ear_flop = 1.0
            p.leg_swing = 1.2
            p.body_tilt = -8.0 if self.vy < 0 else 6.0
        if self.carrying_ball:
            p.mouth_open = 0.6
        self._rig_pose(p)
        return p

    def _ease(self, t_in: float = 0.45, t_out: float = 0.4) -> float:
        """0→1 all'inizio dello stato, 1→0 alla fine: niente scatti."""
        a = min(1.0, self.t / t_in)
        b = min(1.0, max(0.0, (self.duration - self.t) / t_out))
        k = min(a, b)
        return k * k * (3.0 - 2.0 * k)

    def _leg_pose(self, p: Pose, st: str, t: float, e: float) -> None:
        """Zampe della figura intera (mesh): `lift` alza il piede, `swing` lo porta in fuori (+) o
        verso il petto (-). Con una sola gamba (di spalle) vale la sinistra."""
        if st == "typing":                                  # zampe che battono, alternate
            tap = math.sin(t * 15.0)
            p.lift_l, p.lift_r = 0.55 * max(0.0, tap) * e, 0.55 * max(0.0, -tap) * e
            p.swing_l = p.swing_r = -0.12 * e
        elif st == "lick":                                  # porta la zampa al muso
            p.lift_r, p.swing_r = 0.80 * e, -0.60 * e
            p.lift_l = 0.10 * e * max(0.0, math.sin(t * 3.0))
        elif st == "scratch":                               # zampa che gratta il collo
            p.lift_r = 0.72 * e
            p.swing_r = (-0.42 + 0.22 * math.sin(t * 22.0)) * e
        elif st == "boop":                                  # zampette contente
            pat = math.sin(t * 9.0)
            p.lift_l, p.lift_r = 0.30 * max(0.0, pat) * e, 0.30 * max(0.0, -pat) * e
        elif st == "tease":                                 # "nanana": una zampa e l'altra
            pat = math.sin(t * 5.2)
            p.lift_l, p.lift_r = 0.62 * max(0.0, pat) * e, 0.62 * max(0.0, -pat) * e
            p.swing_l, p.swing_r = 0.34 * max(0.0, pat) * e, 0.34 * max(0.0, -pat) * e
        elif st == "bark":                                  # sobbalza a ogni latrato
            hop = max(0.0, 1.0 - ((t * 2.4) % 1.0) * 3.0)
            p.lift_l = p.lift_r = 0.30 * hop
        elif st == "dragged":                               # preso in mano: penzola
            p.lift_l, p.lift_r = 0.5 + 0.5 * math.sin(t * 13.0), 0.5 + 0.5 * math.sin(t * 13.0 + 2.2)
            p.swing_l, p.swing_r = 0.35 * math.sin(t * 9.0), -0.35 * math.sin(t * 9.0 + 1.0)
        elif st == "rest":                                  # sdraiato: ogni tanto allunga una zampa
            p.lift_l = 0.55 * max(0.0, math.sin(t * 0.9)) ** 4
            p.lift_r = 0.55 * max(0.0, math.sin(t * 0.9 + 2.4)) ** 4
            p.swing_r = 0.25 * max(0.0, math.sin(t * 0.9 + 2.4)) ** 4
        elif st in ("sit", "idle", "look", "tilt", "squint", "nope"):
            # a riposo non e' una statua: ogni tanto sposta il peso su una zampa
            shift = max(0.0, math.sin(t * 0.55 + 1.3)) ** 6
            p.lift_l = 0.12 * shift
            p.swing_l = 0.10 * shift

    def _rig_pose(self, p: Pose) -> None:
        """Campi usati dalla pelle fotografica (testa che gira, zampe, lingua...)."""
        st, t, e = self.state, self.t, self._ease()
        if self.full and self.close and st in (PREFER_CLOSE if self.legs else CLOSE_UPS):
            p.view = "busto"                    # viene vicino: le zampe arrivano sul bordo
        if st == "sleep" and "dorme" in self.views and self.full:
            p.view = "dorme" if t > 0.6 else ""          # si accoccola: morph sulla foto di lui che dorme
        elif st == "sleep":
            p.sink = 0.36
            if not self.close:
                p.pitch = 0.55
                if self.legs:
                    p.sink = 0.0
                    p.head_tilt = 6.0 * math.sin(t * 0.6)
        elif st == "bark":
            beat = (t * 2.4) % 1.0
            p.pitch = -0.55 * (1.0 - beat)
            p.brow = 0.6
        elif st == "scratch":
            p.head_tilt = (13.0 + 3.0 * math.sin(t * 38.0)) * e
            p.eye_open = min(p.eye_open, 1.0 - 0.7 * e)
            p.ear_flop = e
            p.sit = 0.0
            p.flail = 0.0
        elif st == "pet":
            p.pitch = -0.35
        elif st == "tilt":
            p.head_tilt = self._side * 13.0 * e
            p.brow = e
        elif st == "look":
            p.yaw = self._side * math.sin(2.0 * math.pi * t / max(0.1, self.duration)) * e
            p.brow = 0.4 * e
        elif st == "squint":
            p.eye_open = min(p.eye_open, 1.0 - 0.62 * e)
            p.pitch = -0.30 * e
        elif st == "boop":
            p.tongue = 0.36 * e
        elif st == "rest":
            p.view = "sdraiato"
            p.yaw = self._side * 0.45 * math.sin(t * 0.5) * e
            p.pitch = 0.12 * math.sin(t * 0.37 + 1.0) * e
            p.head_tilt = 5.0 * math.sin(t * 0.29) * e
            if 3.0 < t % 7.0 < 4.6:                       # ogni tanto: sorriso con la lingua
                p.mouth_open = 0.35 * e
                p.tongue = 0.55 * e
        elif st == "tease":
            p.tongue = 0.75 * e
            p.head_tilt = 10.0 * math.sin(t * 5.2) * e
            p.sink = 0.10 * abs(math.sin(t * 5.2)) * e if not self.full else 0.0
            p.brow = 0.7 * e
        elif st == "typing":
            p.paws = e
            tap = math.sin(t * 15.0)
            p.paw_l, p.paw_r = max(0.0, tap) * e, max(0.0, -tap) * e
            p.prop = "keyboard" if e > 0.05 else ""
            p.pitch = 0.62 * e
            p.yaw = 0.22 * math.sin(t * 2.1) * e
        elif st == "lick":
            p.paws = e
            p.paw_reach = e
            p.pitch = 0.78 * e
            p.head_tilt = 6.0 * e
            p.tongue = (0.45 + 0.4 * math.sin(t * 13.0)) * e
            p.eye_open = min(p.eye_open, 1.0 - 0.6 * e)
        elif st == "hide":
            if t < 1.3:
                p.sink = 1.05 * min(1.0, t / 0.9)
            elif t < 2.6:
                p.sink = 1.05
            elif t < 5.0:
                p.sink = 1.05 - 0.44 * min(1.0, (t - 2.6) / 0.9)      # fa capolino: solo gli occhi
                p.yaw = math.sin((t - 2.6) * 2.4) * 0.9
                p.brow = 1.0
            else:
                p.sink = 0.61 * max(0.0, 1.0 - (t - 5.0) / 0.35)
                p.brow = 0.5
        elif st == "dragged":
            p.brow = 1.0
        elif st in ("eat", "treat") and abs(self.vx) < 1.0 and self._trav is None:
            if st == "eat" or self._moved:
                p.pitch = 0.8
                p.mouth_open = 0.5 + 0.4 * math.sin(t * 14)
        elif st == "leave":
            back = self.duration - 1.5
            if t < 0.9:                                   # ti guarda, poi distoglie lo sguardo
                p.yaw = -self._side * 0.7 * min(1.0, t / 0.7)
                p.brow = 0.5
            elif t < back:
                k = min(1.0, (t - 0.9) / 2.2)
                gone = k * k * (3.0 - 2.0 * k)
                p.view = "dietro"
                p.away = gone
                p.lift_l = 0.45 * max(0.0, math.sin(self.leg_phase)) * (1.0 - 0.5 * gone)
                p.body_tilt = math.sin(self.leg_phase) * 9.0 * (1.0 - gone)
                p.body_bob = -abs(math.sin(self.leg_phase)) * 3.0
                if "dietro" not in self.views:
                    p.view = ""
                    p.away, p.sink = 0.0, 1.05 * gone     # senza foto di spalle: scende sotto il bordo
            else:
                k = min(1.0, (t - back) / 1.3)
                p.away = 1.0 - k * k * (3.0 - 2.0 * k)
                p.body_bob = -abs(math.sin(self.leg_phase)) * 3.0 * (1.0 - k)
                if "dietro" not in self.views:
                    p.sink, p.away = 1.05 * p.away, 0.0
        elif st == "nope":
            turn = min(1.0, max(0.0, (t - 1.0) / 1.2))
            turn = turn * turn * (3.0 - 2.0 * turn)
            p.view = "serio"
            p.yaw = self._side * 0.55 * turn * e           # si volta piano dall'altra parte
            p.head_tilt = -self._side * 3.0 * turn * e
            p.pitch = 0.20 * e
            p.eye_open = min(p.eye_open, 1.0 - 0.40 * e)   # palpebre a mezz'asta
            p.tail_wag = 0.0
        elif st == "poop":
            if t < 4.1:
                k = min(1.0, t / 0.8) * min(1.0, max(0.0, (4.1 - t) / 0.4))
                p.view = "serio"                           # ti fissa serissimo
                p.squash = 1.0 - 0.055 * k                 # si accuccia appena
                p.body_tilt = math.sin(t * 46.0) * 1.6 * k if 1.0 < t < 3.5 else 0.0
                p.pitch = 0.16 * k
                p.eye_open = min(p.eye_open, 1.0 - 0.34 * k)
                p.ear_flop = 0.6 * k
                p.tail_wag = 0.0
            else:
                k = min(1.0, (t - 4.1) / 0.5) * min(1.0, max(0.0, (self.duration - t) / 0.4))
                p.pitch = -0.32 * k                        # muso in su, sollevato
                p.eye_open = min(p.eye_open, 1.0 - 0.55 * k)
                p.brow = 0.4 * k

        if self.legs and self.full:
            self._leg_pose(p, st, t, e)

        if self._trav is not None:                         # in viaggio: via di spalle, poi ritorno
            tt = self._trav[0]
            if "dietro" not in self.views:                 # senza foto di spalle: giu' e su dal bordo
                k = min(1.0, tt / TRAVEL_OUT) if tt < TRAVEL_OUT else 1.0 - min(1.0, (tt - TRAVEL_OUT) / TRAVEL_IN)
                p.view, p.away = "", 0.0
                p.sink = 1.05 * k * k * (3.0 - 2.0 * k)
            elif tt < TRAVEL_OUT:
                k = tt / TRAVEL_OUT
                p.view = "dietro"
                p.away = k * k * (3.0 - 2.0 * k)
                p.lift_l = 0.45 * max(0.0, math.sin(self.leg_phase))
                p.body_tilt = math.sin(self.leg_phase) * 9.0 * (1.0 - p.away)
            else:
                k = min(1.0, (tt - TRAVEL_OUT) / TRAVEL_IN)
                p.view = ""
                p.away = 1.0 - k * k * (3.0 - 2.0 * k)
            p.body_bob = -abs(math.sin(self.leg_phase)) * 3.0
            p.yaw = p.pitch = p.head_tilt = 0.0
        if self.full and p.view != "busto" and p.sink > 0.0 and not self.legs and "dietro" in self.views:
            # la figura intera non "scende sotto il bordo": semmai si allontana
            if not self.close:
                p.away = max(p.away, min(1.0, p.sink))
            p.sink = 0.0
