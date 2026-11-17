"""Tipi condivisi tra il motore di disegno e il resto dell'app."""

from __future__ import annotations

from dataclasses import dataclass

UNIT = 100.0  # il cane e' disegnato in un box 100x100, poi scalato
GROUND = 95.0


@dataclass
class Pose:
    """Tutti i parametri animabili di una posa."""

    leg_phase: float = 0.0       # ciclo passo 0..2pi
    leg_swing: float = 0.0       # ampiezza passo (0 = fermo)
    body_bob: float = 0.0        # oscillazione verticale
    body_tilt: float = 0.0       # rotazione corpo in gradi
    tail_angle: float = -35.0    # angolo base coda
    tail_wag: float = 0.0        # ampiezza scodinzolio in gradi
    tail_phase: float = 0.0
    head_tilt: float = 0.0       # inclinazione testa
    head_drop: float = 0.0       # testa abbassata (annusa/mangia)
    ear_flop: float = 0.0        # orecchie che svolazzano
    eye_open: float = 1.0        # 0 = chiusi
    mouth_open: float = 0.0      # 0..1
    tongue: float = 0.0          # lingua fuori 0..1
    sit: float = 0.0             # 0 in piedi, 1 seduto
    lie: float = 0.0             # 0 in piedi, 1 sdraiato
    squash: float = 1.0          # 1 normale, <1 schiacciato (atterraggio)
    spin: float = 0.0            # rotazione di tutto il corpo in gradi
    flail: float = 0.0           # zampe che si agitano (preso in mano)
    facing: int = 1              # 1 destra, -1 sinistra
    blush: float = 0.0           # guance rosse quando viene coccolato
    shadow: float = 1.0          # opacita ombra a terra
    # --- pelle fotografica (rig a mesh) ---
    yaw: float = 0.0             # testa girata: -1 sinistra .. +1 destra
    pitch: float = 0.0           # testa: -1 in su .. +1 in giu'
    brow: float = 0.0            # sopracciglia alzate 0..1
    sink: float = 0.0            # quanto e' sceso sotto il bordo: 0 fuori .. 1 nascosto
    paws: float = 0.0            # zampe appoggiate al bordo 0..1
    paw_l: float = 0.0           # zampa sinistra sollevata 0..1
    paw_r: float = 0.0           # zampa destra sollevata 0..1
    paw_reach: float = 0.0       # zampa destra verso la bocca 0..1
    prop: str = ""               # oggetto di scena ("keyboard")
    view: str = ""               # vista richiesta: "" = casa, busto, seduto, serio, dietro
    away: float = 0.0            # si allontana: 0 qui .. 1 sparito in lontananza
    # zampe della figura intera (mesh): sollevamento 0..1 e oscillazione -1 (verso il petto) .. +1 (in fuori)
    lift_l: float = 0.0
    lift_r: float = 0.0
    swing_l: float = 0.0
    swing_r: float = 0.0
