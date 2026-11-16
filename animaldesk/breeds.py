"""Razze: tutto cio' che cambia tra un cane e l'altro sta qui dentro."""

from __future__ import annotations

from dataclasses import dataclass, field

from PySide6.QtGui import QColor


@dataclass(frozen=True)
class Breed:
    key: str
    label: str
    # manto
    base: str          # colore principale
    light: str         # schiariture (dorso, luce)
    cream: str         # petto, pancia, frange
    dark: str          # ombre, orecchie
    nose: str
    iris: str
    # forma
    coat: str = "feathered"      # "feathered" (pelo lungo liscio) | "curly" (riccio)
    tail: str = "plume"          # "plume" (piumata) | "pompom"
    ear_len: float = 20.0
    ear_width: float = 11.0
    muzzle_len: float = 20.0
    muzzle_depth: float = 10.0
    body_depth: float = 1.0      # moltiplicatore profondita' torace
    leg_scale: float = 1.0
    topknot: bool = False
    curl_size: float = 3.1

    def c(self, name: str) -> QColor:
        return QColor(getattr(self, name))


GOLDEN = Breed(
    key="golden",
    label="Golden retriever",
    base="#D9A24F",
    light="#F2D69C",
    cream="#F7E8C8",
    dark="#A86F2A",
    nose="#241B14",
    iris="#8A5A2A",
    coat="feathered",
    tail="plume",
    ear_len=19.5,
    ear_width=9.0,
    muzzle_len=21.0,
    muzzle_depth=10.5,
    body_depth=1.0,
    leg_scale=1.0,
)

POODLE = Breed(
    key="barboncino",
    label="Barboncino",
    base="#C99A66",
    light="#E8C79A",
    cream="#F3E0C4",
    dark="#9A6B3C",
    nose="#1E1A18",
    iris="#5A3A22",
    coat="curly",
    tail="pompom",
    ear_len=21.0,
    ear_width=9.5,
    muzzle_len=22.0,
    muzzle_depth=8.0,
    body_depth=0.92,
    leg_scale=1.08,
    topknot=True,
    curl_size=3.4,
)

BREEDS: dict[str, Breed] = {b.key: b for b in (GOLDEN, POODLE)}


def get(key: str) -> Breed:
    return BREEDS.get(key, GOLDEN)
