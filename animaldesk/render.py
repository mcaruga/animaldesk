"""Oggetti di scena (palla, ciotola, particelle, fumetti) e icona dell'app.

Il cane vero e proprio e' in dogart.py.
"""

from __future__ import annotations

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen

from .breeds import GOLDEN, Breed
from .dogart import draw_dog  # noqa: F401  (riesportato: render.draw_dog)
from .render_types import GROUND, UNIT, Pose  # noqa: F401

# tavolozza di comodo per le icone
FUR = QColor(GOLDEN.base)
FUR_LIGHT = QColor(GOLDEN.light)
FUR_DARK = QColor(GOLDEN.dark)
NOSE = QColor(GOLDEN.nose)
EYE = QColor("#3A2A1C")
TONGUE = QColor("#E0697F")


# --------------------------------------------------------------------- props
BALL_A = QColor("#E8453C")
BALL_B = QColor("#FFF4E0")
BOWL = QColor("#4C8FD6")
KIBBLE = QColor("#8A5A2B")


def draw_ball(painter: QPainter, x: float, y: float, r: float) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(0, 0, 0, 40))
    painter.drawEllipse(QRectF(x - r, y + r * 0.2, r * 2, r * 0.6))
    painter.setBrush(BALL_A)
    painter.drawEllipse(QPointF(x, y - r), r, r)
    painter.setBrush(BALL_B)
    painter.drawChord(QRectF(x - r, y - 2 * r, 2 * r, 2 * r), 200 * 16, 140 * 16)
    painter.setBrush(QColor(255, 255, 255, 170))
    painter.drawEllipse(QPointF(x - r * 0.35, y - r * 1.4), r * 0.22, r * 0.18)
    painter.restore()


def draw_bowl(painter: QPainter, x: float, y: float, w: float, full: float = 1.0) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.setPen(Qt.NoPen)
    h = w * 0.52
    painter.setBrush(BOWL)
    path = QPainterPath(QPointF(x - w / 2, y - h))
    path.lineTo(QPointF(x + w / 2, y - h))
    path.lineTo(QPointF(x + w * 0.34, y))
    path.lineTo(QPointF(x - w * 0.34, y))
    path.closeSubpath()
    painter.drawPath(path)
    painter.setBrush(QColor(255, 255, 255, 60))
    painter.drawRect(QRectF(x - w / 2, y - h, w, h * 0.22))
    if full > 0.05:  # crocchette sopra il bordo
        painter.setBrush(KIBBLE)
        painter.drawEllipse(QRectF(x - w * 0.34, y - h - w * 0.13 * full, w * 0.68, w * 0.28 * full + w * 0.08))
    painter.restore()


def draw_particle(painter: QPainter, kind: str, x: float, y: float, alpha: float,
                  size: float, text: str = "", spin: float = 0.0) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    a = int(235 * alpha)
    painter.setPen(Qt.NoPen)
    if kind == "heart":
        painter.translate(x, y)
        painter.scale(size / 20.0, size / 20.0)
        painter.setBrush(QColor(230, 80, 110, a))
        path = QPainterPath(QPointF(0, 6))
        path.cubicTo(QPointF(-9, -1), QPointF(-6, -9), QPointF(0, -4))
        path.cubicTo(QPointF(6, -9), QPointF(9, -1), QPointF(0, 6))
        painter.drawPath(path)
    elif kind == "zzz":
        f = painter.font()
        f.setPointSizeF(max(7.0, size * 0.8))
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(240, 240, 255, a))
        painter.drawText(QPointF(x, y), "z")
    elif kind == "letter":
        f = painter.font()
        f.setPointSizeF(max(7.0, size * 0.42))
        f.setBold(True)
        painter.setFont(f)
        painter.setPen(QColor(20, 20, 26, int(a * 0.55)))
        painter.drawText(QPointF(x + 1, y + 1), text)
        painter.setPen(QColor(255, 255, 255, a))
        painter.drawText(QPointF(x, y), text)
    elif kind in ("dirt", "crumb"):
        painter.setBrush(QColor(140, 96, 48, a) if kind == "dirt" else QColor(150, 100, 50, a))
        painter.drawEllipse(QPointF(x, y), size * 0.22, size * 0.18)
    elif kind == "dust":
        painter.setBrush(QColor(220, 215, 205, int(a * 0.7)))
        painter.drawEllipse(QPointF(x, y), size * 0.35, size * 0.22)
    elif kind == "star":
        painter.translate(x, y)
        painter.rotate(spin)
        painter.setBrush(QColor(255, 214, 102, a))
        path = QPainterPath()
        for i in range(10):
            r = size * (0.42 if i % 2 == 0 else 0.18)
            ang = math.pi * i / 5 - math.pi / 2
            pt = QPointF(r * math.cos(ang), r * math.sin(ang))
            path.lineTo(pt) if i else path.moveTo(pt)
        path.closeSubpath()
        painter.drawPath(path)
    painter.restore()


def draw_bubble(painter: QPainter, x: float, y: float, text: str, alpha: float, scale: float) -> QRectF:
    """Fumetto del cane. Ritorna il rettangolo occupato (per la maschera)."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    font = painter.font()
    font.setPointSizeF(max(7.5, 9.5 * scale))
    font.setBold(True)
    painter.setFont(font)
    metrics = painter.fontMetrics()
    w = metrics.horizontalAdvance(text) + 18 * scale
    h = metrics.height() + 10 * scale
    rect = QRectF(x - w / 2, y - h, w, h)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor(255, 255, 255, int(236 * alpha)))
    painter.drawRoundedRect(rect, 9 * scale, 9 * scale)
    tail = QPainterPath(QPointF(x - 5 * scale, y))
    tail.lineTo(QPointF(x + 5 * scale, y))
    tail.lineTo(QPointF(x, y + 7 * scale))
    tail.closeSubpath()
    painter.drawPath(tail)
    painter.setPen(QColor(40, 40, 46, int(255 * alpha)))
    painter.drawText(rect, Qt.AlignCenter, text)
    painter.restore()
    return rect.adjusted(-2, -2, 2, 9 * scale)


def draw_head_icon(painter: QPainter, size: float, breed: Breed = GOLDEN) -> None:
    """Testa del cane per l'icona nella tray."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size / 40.0, size / 40.0)
    painter.setPen(Qt.NoPen)
    painter.setBrush(breed.c("dark"))
    painter.drawEllipse(QRectF(1, 10, 9, 20))
    painter.drawEllipse(QRectF(30, 10, 9, 20))
    painter.setBrush(breed.c("base"))
    painter.drawEllipse(QRectF(5, 5, 30, 28))
    painter.setBrush(breed.c("cream"))
    painter.drawEllipse(QRectF(12, 20, 16, 14))
    painter.setBrush(QColor(breed.iris).darker(220))
    painter.drawEllipse(QRectF(13, 15, 4, 5))
    painter.drawEllipse(QRectF(23, 15, 4, 5))
    painter.setBrush(QColor(breed.nose))
    painter.drawEllipse(QRectF(17, 23, 6, 5))
    painter.restore()
