"""Oggetti del mondo: palla, ciotola, particelle. Niente Qt, solo fisica."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

GRAVITY = 1500.0


@dataclass
class Ball:
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    radius: float = 11.0
    resting: bool = False

    def update(self, dt: float, left: float, right: float, ground: float) -> None:
        if self.resting:
            return
        self.vy += GRAVITY * dt
        self.x += self.vx * dt
        self.y += self.vy * dt
        if self.y >= ground:
            self.y = ground
            self.vy = -self.vy * 0.52
            self.vx *= 0.72
            if abs(self.vy) < 45.0:
                self.vy = 0.0
                self.vx = 0.0
                self.resting = True
        if self.x < left + self.radius:
            self.x = left + self.radius
            self.vx = abs(self.vx) * 0.6
        elif self.x > right - self.radius:
            self.x = right - self.radius
            self.vx = -abs(self.vx) * 0.6


@dataclass
class Bowl:
    x: float
    y: float
    width: float = 34.0


@dataclass
class Particle:
    kind: str
    x: float
    y: float
    vx: float = 0.0
    vy: float = 0.0
    life: float = 1.0
    max_life: float = 1.0
    text: str = ""
    spin: float = 0.0

    @property
    def alpha(self) -> float:
        return max(0.0, min(1.0, self.life / self.max_life))


class Particles:
    """Cuoricini, zzz, terra, briciole, polvere e fumetti."""

    PRESETS = {
        "heart": dict(life=1.3, vy=-42.0, spread=16.0),
        "zzz": dict(life=2.2, vy=-26.0, spread=10.0),
        "dirt": dict(life=0.7, vy=-150.0, spread=90.0),
        "dust": dict(life=0.5, vy=-30.0, spread=70.0),
        "crumb": dict(life=0.6, vy=-90.0, spread=60.0),
        "bubble": dict(life=1.8, vy=-14.0, spread=0.0),
        "star": dict(life=0.9, vy=-60.0, spread=50.0),
        "letter": dict(life=1.1, vy=-58.0, spread=14.0),
    }

    def __init__(self, limit: int = 160) -> None:
        self.items: list[Particle] = []
        self.limit = limit

    def spawn(self, kind: str, x: float, y: float, text: str = "") -> None:
        preset = self.PRESETS.get(kind, self.PRESETS["star"])
        if len(self.items) >= self.limit:
            self.items.pop(0)
        life = float(preset["life"])
        self.items.append(
            Particle(
                kind=kind,
                x=x,
                y=y,
                vx=random.uniform(-1.0, 1.0) * float(preset["spread"]),
                vy=float(preset["vy"]) * random.uniform(0.8, 1.25),
                life=life,
                max_life=life,
                text=text,
                spin=random.uniform(-180.0, 180.0),
            )
        )

    def update(self, dt: float) -> None:
        alive: list[Particle] = []
        for p in self.items:
            p.life -= dt
            if p.life <= 0:
                continue
            p.x += p.vx * dt
            p.y += p.vy * dt
            if p.kind in ("dirt", "crumb", "dust"):
                p.vy += GRAVITY * 0.45 * dt
            else:
                p.vy *= 0.985
                p.x += math.sin(p.life * 5.0) * 14.0 * dt
            alive.append(p)
        self.items = alive

    def clear(self) -> None:
        self.items.clear()
