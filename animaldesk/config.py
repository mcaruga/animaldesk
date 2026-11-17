"""Configurazione persistente di AnimalDesk (JSON nella cartella utente)."""

from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

SIZES = {"mini": 90, "piccolo": 120, "medio": 160, "grande": 220}


def config_dir() -> Path:
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "AnimalDesk"


def skins_dirs() -> list[Path]:
    """Dove cercare le pelli fotografiche: utente, pacchetto, sorgenti."""
    here = Path(__file__).resolve().parent
    dirs = [config_dir() / "skins"]
    if getattr(sys, "frozen", False):
        dirs.append(Path(getattr(sys, "_MEIPASS", here)) / "assets" / "skins")
    dirs += [here / "assets" / "skins", here.parent / "assets" / "skins"]
    return dirs


def find_skin(name: str) -> Path | None:
    if not name:
        return None
    for folder in skins_dirs():
        candidate = folder / name
        if (candidate / "rig.json").exists():
            return candidate
    return None


def list_skins() -> list[str]:
    names: list[str] = []
    for folder in skins_dirs():
        if not folder.is_dir():
            continue
        for item in sorted(folder.iterdir()):
            if (item / "rig.json").exists() and item.name not in names:
                names.append(item.name)
    return names


@dataclass
class Config:
    size: int = SIZES["medio"]
    speed: float = 1.0
    follow_cursor: bool = False
    sounds: bool = False
    autostart: bool = False
    screen_index: int = 0
    name: str = "Golden"
    skin: str = "golden-reale"      # cartella in assets/skins, "" = disegno vettoriale
    breed: str = "golden"           # razza usata dal disegno vettoriale
    outfit: str = "auto"            # auto (stagionale) | "" | santa | summer | ski
    framing: str = "intera"         # intera (figura intera) | busto (primo piano dal bordo)
    props_ttl: int = 180            # secondi dopo cui palla, biscotti e ricordini spariscono (0 = mai)
    stats: dict[str, float] = field(default_factory=lambda: {"energia": 100.0, "fame": 0.0, "felicita": 80.0})

    @classmethod
    def load(cls) -> "Config":
        path = config_dir() / "config.json"
        try:
            data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return cls()
        cfg = cls()
        for key, value in data.items():
            if hasattr(cfg, key) and value is not None:
                setattr(cfg, key, value)
        cfg.size = max(60, min(400, int(cfg.size)))
        cfg.speed = max(0.25, min(3.0, float(cfg.speed)))
        cfg.props_ttl = max(0, min(3600, int(cfg.props_ttl)))
        if cfg.framing not in ("intera", "busto"):
            cfg.framing = "intera"
        base = cls().stats
        base.update({k: float(v) for k, v in dict(cfg.stats).items() if k in base})
        cfg.stats = base
        return cfg

    def save(self) -> None:
        path = config_dir() / "config.json"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")
            tmp.replace(path)
        except OSError:
            pass
