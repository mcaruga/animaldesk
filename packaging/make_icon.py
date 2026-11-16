"""Genera le icone dell'app dal disegno vettoriale (nessun asset binario in repo)."""

from __future__ import annotations

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QGuiApplication, QPainter, QPixmap  # noqa: E402

from animaldesk import render  # noqa: E402


def main() -> int:
    app = QGuiApplication.instance() or QGuiApplication([])
    out = Path(__file__).resolve().parents[1] / "assets"
    out.mkdir(exist_ok=True)
    for size in (16, 32, 64, 128, 256, 512):
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        painter = QPainter(pix)
        render.draw_head_icon(painter, size)
        painter.end()
        pix.save(str(out / f"icon-{size}.png"))
        if size == 256:
            pix.save(str(out / "icon.png"))
            pix.save(str(out / "icon.ico"))
    print(f"icone generate in {out}")
    del app
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
