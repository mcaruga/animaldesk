"""Costumi e oggetti di scena della pelle fotografica.

- draw_on_head: accessori disegnati NELLA texture (prima della deformazione),
  quindi seguono la testa quando gira o si inclina: cappello, occhiali, maschera.
- draw_behind / draw_front: oggetti nello spazio schermo, dietro o davanti al cane
  (salvagente, sci, tastiera).
"""

from __future__ import annotations

import datetime as _dt
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient)

OUTFITS = {
    "": "Nessuno",
    "santa": "Babbo Natale",
    "summer": "Mare",
    "ski": "Sci",
}


def seasonal(today: _dt.date | None = None) -> str:
    """Costume automatico in base alla data."""
    d = today or _dt.date.today()
    if (d.month == 12 and d.day >= 1) or (d.month == 1 and d.day <= 6):
        return "santa"
    if (d.month == 6 and d.day >= 15) or d.month in (7, 8) or (d.month == 9 and d.day <= 7):
        return "summer"
    return ""


def resolve(choice: str, today: _dt.date | None = None) -> str:
    return seasonal(today) if choice == "auto" else (choice if choice in OUTFITS else "")


# ------------------------------------------------------------------ utilita'
def _frame(skin):
    """Sistema di riferimento della testa: centro occhi, distanza occhi, inclinazione."""
    eyes = skin.rig.eyes
    a, b = skin.uv(eyes[0].x, eyes[0].y), skin.uv(eyes[-1].x, eyes[-1].y)
    e = math.hypot(b.x() - a.x(), b.y() - a.y()) or skin.sw * 0.3
    ang = math.degrees(math.atan2(b.y() - a.y(), b.x() - a.x()))
    return a, b, e, ang


def _fuzz(p: QPainter, path: QPainterPath, r: float, seed: int, color: QColor) -> None:
    """Bordo di pelliccia: pallini lungo un percorso."""
    p.setPen(Qt.NoPen)
    n = max(8, int(path.length() / (r * 0.9)))
    for k in range(n + 1):
        t = k / n
        pt = path.pointAtPercent(t)
        j = math.sin(seed + k * 12.9898) * 43758.5453
        j -= math.floor(j)
        col = QColor(color)
        col = col.darker(100 + int(j * 9))
        p.setBrush(col)
        p.drawEllipse(QPointF(pt.x() + (j - 0.5) * r * 0.5, pt.y() + (0.5 - j) * r * 0.4),
                      r * (0.85 + 0.4 * j), r * (0.8 + 0.35 * j))


# ----------------------------------------------------------- sulla testa
def draw_on_head(p: QPainter, outfit: str, skin) -> None:
    if not skin.rig.eyes:
        return
    a, b, e, ang = _frame(skin)
    top = skin.uv(*skin.rig.head_top)
    p.save()
    face = getattr(skin.rig, "face", True)          # di spalle: solo il cappello
    if outfit == "santa":
        _santa_hat(p, top, e, ang)
    elif outfit == "summer" and face:
        _sunglasses(p, a, b, e, ang)
    elif outfit == "ski":
        _beanie(p, top, e, ang)
        if face:
            _goggles(p, a, b, e, ang)
    p.restore()


def _santa_hat(p: QPainter, top: QPointF, e: float, ang: float) -> None:
    p.translate(top.x(), top.y() + e * 0.30)
    p.rotate(ang - 4.0)
    # cono rosso che ricade di lato
    cone = QPainterPath(QPointF(-0.80 * e, 0.02 * e))
    cone.cubicTo(QPointF(-0.62 * e, -0.95 * e), QPointF(0.10 * e, -1.42 * e), QPointF(0.62 * e, -1.12 * e))
    cone.cubicTo(QPointF(0.98 * e, -0.92 * e), QPointF(1.12 * e, -0.52 * e), QPointF(1.08 * e, -0.30 * e))
    cone.cubicTo(QPointF(0.92 * e, -0.62 * e), QPointF(0.78 * e, -0.50 * e), QPointF(0.80 * e, 0.0))
    cone.closeSubpath()
    red = QLinearGradient(-0.8 * e, -0.2 * e, 0.9 * e, -0.9 * e)
    red.setColorAt(0.0, QColor("#E2332E"))
    red.setColorAt(0.55, QColor("#C4201F"))
    red.setColorAt(1.0, QColor("#8C1114"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(red))
    p.drawPath(cone)
    fold = QPainterPath(QPointF(0.30 * e, -1.10 * e))            # piega in ombra
    fold.cubicTo(QPointF(0.62 * e, -0.86 * e), QPointF(0.70 * e, -0.50 * e), QPointF(0.62 * e, -0.14 * e))
    p.setPen(QPen(QColor(70, 6, 10, 110), e * 0.07, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(fold)
    p.setPen(QPen(QColor(255, 150, 140, 70), e * 0.05, Qt.SolidLine, Qt.RoundCap))
    hi = QPainterPath(QPointF(-0.52 * e, -0.30 * e))
    hi.cubicTo(QPointF(-0.40 * e, -0.80 * e), QPointF(-0.10 * e, -1.05 * e), QPointF(0.20 * e, -1.15 * e))
    p.drawPath(hi)
    # bordo di pelliccia bianca
    brim = QPainterPath(QPointF(-0.92 * e, 0.06 * e))
    brim.quadTo(QPointF(0.0, -0.20 * e), QPointF(0.90 * e, 0.02 * e))
    p.setPen(QPen(QColor("#DCDCE4"), e * 0.40, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(brim.translated(0, e * 0.035))
    p.setPen(QPen(QColor("#FAFAFC"), e * 0.36, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(brim)
    _fuzz(p, brim.translated(0, -e * 0.17), e * 0.075, 3, QColor("#FFFFFF"))
    _fuzz(p, brim.translated(0, e * 0.19), e * 0.075, 9, QColor("#E6E6EE"))
    # pompon
    c = QPointF(1.08 * e, -0.24 * e)
    pom = QRadialGradient(c.x() - e * 0.06, c.y() - e * 0.07, e * 0.26)
    pom.setColorAt(0.0, QColor("#FFFFFF"))
    pom.setColorAt(1.0, QColor("#D6D6E0"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(pom))
    p.drawEllipse(c, e * 0.21, e * 0.21)
    ring = QPainterPath()
    ring.addEllipse(c, e * 0.20, e * 0.20)
    _fuzz(p, ring, e * 0.06, 5, QColor("#FAFAFC"))


def _sunglasses(p: QPainter, a: QPointF, b: QPointF, e: float, ang: float) -> None:
    mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
    p.translate(mid)
    p.rotate(ang)
    half = e / 2
    p.setPen(QPen(QColor("#15151A"), e * 0.045, Qt.SolidLine, Qt.RoundCap))
    p.drawLine(QPointF(-half * 0.42, -e * 0.03), QPointF(half * 0.46, -e * 0.03))      # ponte
    p.drawLine(QPointF(-half - e * 0.36, -e * 0.03), QPointF(-half - e * 0.72, -e * 0.10))  # aste
    p.drawLine(QPointF(half + e * 0.30, -e * 0.03), QPointF(half + e * 0.52, -e * 0.12))
    for cx, k in ((-half, 1.0), (half, 0.86)):          # la lente lontana e' piu' piccola (3/4)
        w, h = e * 0.74 * k, e * 0.52 * k
        rect = QRectF(cx - w / 2, -h * 0.42, w, h)
        lens = QPainterPath()
        lens.addRoundedRect(rect, w * 0.30, h * 0.42)
        g = QLinearGradient(rect.topLeft(), rect.bottomRight())
        g.setColorAt(0.0, QColor(58, 64, 86, 250))
        g.setColorAt(0.5, QColor(22, 24, 34, 250))
        g.setColorAt(1.0, QColor(10, 10, 16, 250))
        p.setPen(QPen(QColor("#101014"), e * 0.05))
        p.setBrush(QBrush(g))
        p.drawPath(lens)
        p.save()
        p.setClipPath(lens)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(255, 255, 255, 46))
        glare = QPainterPath(QPointF(rect.left() + w * 0.10, rect.bottom()))
        glare.lineTo(rect.left() + w * 0.42, rect.top())
        glare.lineTo(rect.left() + w * 0.60, rect.top())
        glare.lineTo(rect.left() + w * 0.28, rect.bottom())
        glare.closeSubpath()
        p.drawPath(glare)
        p.restore()


def _beanie(p: QPainter, top: QPointF, e: float, ang: float) -> None:
    p.save()
    p.translate(top.x(), top.y() + e * 0.34)
    p.rotate(ang - 3.0)
    dome = QPainterPath(QPointF(-0.90 * e, 0.0))
    dome.cubicTo(QPointF(-0.88 * e, -0.80 * e), QPointF(0.84 * e, -0.86 * e), QPointF(0.88 * e, -0.04 * e))
    dome.closeSubpath()
    g = QLinearGradient(-0.9 * e, -0.6 * e, 0.9 * e, 0.0)
    g.setColorAt(0.0, QColor("#2FA7B8"))
    g.setColorAt(1.0, QColor("#17606E"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(g))
    p.drawPath(dome)
    p.save()
    p.setClipPath(dome)                                   # maglia a coste
    p.setPen(QPen(QColor(255, 255, 255, 34), e * 0.022))
    for k in range(-9, 10):
        x = k * e * 0.10
        rib = QPainterPath(QPointF(x, 0.0))
        rib.quadTo(QPointF(x * 0.9, -0.5 * e), QPointF(x * 0.35, -0.86 * e))
        p.drawPath(rib)
    p.setPen(QPen(QColor("#F4F4F0"), e * 0.07))           # banda decorativa
    band = QPainterPath(QPointF(-0.88 * e, -0.36 * e))
    band.quadTo(QPointF(0.0, -0.62 * e), QPointF(0.86 * e, -0.40 * e))
    p.drawPath(band)
    p.restore()
    cuff = QPainterPath(QPointF(-0.94 * e, 0.02 * e))
    cuff.quadTo(QPointF(0.0, -0.22 * e), QPointF(0.92 * e, -0.02 * e))
    p.setPen(QPen(QColor("#0F4A56"), e * 0.30, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(cuff.translated(0, e * 0.02))
    p.setPen(QPen(QColor("#1D7E8E"), e * 0.26, Qt.SolidLine, Qt.RoundCap))
    p.drawPath(cuff)
    c = QPointF(0.02 * e, -0.80 * e)
    pom = QRadialGradient(c.x() - e * 0.05, c.y() - e * 0.06, e * 0.24)
    pom.setColorAt(0.0, QColor("#FFFFFF"))
    pom.setColorAt(1.0, QColor("#CFCFD8"))
    p.setPen(Qt.NoPen)
    p.setBrush(QBrush(pom))
    p.drawEllipse(c, e * 0.19, e * 0.19)
    ring = QPainterPath()
    ring.addEllipse(c, e * 0.18, e * 0.18)
    _fuzz(p, ring, e * 0.055, 7, QColor("#F6F6FA"))
    p.restore()


def _goggles(p: QPainter, a: QPointF, b: QPointF, e: float, ang: float) -> None:
    mid = QPointF((a.x() + b.x()) / 2, (a.y() + b.y()) / 2)
    p.translate(mid)
    p.rotate(ang)
    half = e / 2
    # elastico attorno alla testa
    for x0, x1, dy in ((-half - e * 0.34, -half - e * 0.92, -0.10), (half + e * 0.30, half + e * 0.62, -0.12)):
        p.setPen(QPen(QColor("#1A1A22"), e * 0.26, Qt.SolidLine, Qt.FlatCap))
        p.drawLine(QPointF(x0, 0.0), QPointF(x1, dy * e))
        p.setPen(QPen(QColor("#F2C230"), e * 0.07, Qt.SolidLine, Qt.FlatCap))
        p.drawLine(QPointF(x0, 0.0), QPointF(x1, dy * e))
    rect = QRectF(-half - e * 0.44, -e * 0.34, e + e * 0.84, e * 0.66)
    frame = QPainterPath()
    frame.addRoundedRect(rect, e * 0.24, e * 0.26)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor("#17171D"))
    p.drawPath(frame)
    lens_rect = rect.adjusted(e * 0.07, e * 0.07, -e * 0.07, -e * 0.07)
    lens = QPainterPath()
    lens.addRoundedRect(lens_rect, e * 0.18, e * 0.20)
    g = QLinearGradient(lens_rect.topLeft(), lens_rect.bottomRight())
    g.setColorAt(0.0, QColor("#FFC24A"))
    g.setColorAt(0.38, QColor("#F2643D"))
    g.setColorAt(0.72, QColor("#B63A8E"))
    g.setColorAt(1.0, QColor("#3B4FC4"))
    p.setBrush(QBrush(g))
    p.drawPath(lens)
    p.save()
    p.setClipPath(lens)
    p.setBrush(QColor(255, 255, 255, 70))
    glare = QPainterPath(QPointF(lens_rect.left() + e * 0.10, lens_rect.bottom()))
    glare.lineTo(lens_rect.left() + e * 0.46, lens_rect.top())
    glare.lineTo(lens_rect.left() + e * 0.72, lens_rect.top())
    glare.lineTo(lens_rect.left() + e * 0.36, lens_rect.bottom())
    glare.closeSubpath()
    p.drawPath(glare)
    p.setBrush(QColor(255, 255, 255, 36))
    p.drawEllipse(QRectF(lens_rect.right() - e * 0.50, lens_rect.top() + e * 0.04, e * 0.40, e * 0.16))
    p.restore()


# ------------------------------------------------------------ nello schermo
def _ring_arc(painter: QPainter, size: float, sw: float, front: bool) -> None:
    """Salvagente a spicchi: meta' dietro al cane, meta' davanti."""
    rx, ry, thick = sw * 0.60, size * 0.115, size * 0.135
    rect = QRectF(-rx, -size * 0.185 - ry, rx * 2, ry * 2)
    start = 180 if front else 0
    seg = 22.5
    for k in range(8):
        color = QColor("#E8453C") if k % 2 == 0 else QColor("#FAFAFA")
        painter.setPen(QPen(color, thick, Qt.SolidLine, Qt.FlatCap))
        painter.drawArc(rect, int((start + k * seg) * 16), int((seg + 0.6) * 16))
    painter.setPen(QPen(QColor(255, 255, 255, 80), thick * 0.18, Qt.SolidLine, Qt.RoundCap))
    hi = rect.adjusted(0, -thick * 0.22, 0, -thick * 0.22)
    painter.drawArc(hi, int((start + 14) * 16), int(150 * 16))
    painter.setPen(QPen(QColor(0, 0, 0, 40), thick * 0.16, Qt.SolidLine, Qt.RoundCap))
    lo = rect.adjusted(0, thick * 0.30, 0, thick * 0.30)
    painter.drawArc(lo, int((start + 10) * 16), int(160 * 16))


def draw_behind(painter: QPainter, outfit: str, skin, size: float) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if outfit == "summer":
        _ring_arc(painter, size, skin.sw, front=False)
    elif outfit == "ski":
        for k, (dx, rot, col) in enumerate(((0.56, 5.0, "#E8453C"), (0.66, 9.0, "#2F6FD0"))):
            painter.save()
            painter.translate(skin.sw * dx, 0)
            painter.rotate(rot)
            w, h = size * 0.085, size * 1.22
            ski = QPainterPath(QPointF(-w / 2, 0))
            ski.lineTo(QPointF(-w / 2, -h * 0.90))
            ski.cubicTo(QPointF(-w / 2, -h), QPointF(w * 0.9, -h * 1.02), QPointF(w * 0.95, -h * 0.93))
            ski.cubicTo(QPointF(w * 0.7, -h * 0.95), QPointF(w / 2, -h * 0.93), QPointF(w / 2, -h * 0.86))
            ski.lineTo(QPointF(w / 2, 0))
            ski.closeSubpath()
            g = QLinearGradient(-w / 2, 0, w / 2, 0)
            g.setColorAt(0.0, QColor(col).darker(125))
            g.setColorAt(0.5, QColor(col).lighter(118))
            g.setColorAt(1.0, QColor(col).darker(140))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(g))
            painter.drawPath(ski)
            painter.setBrush(QColor(255, 255, 255, 200))
            painter.drawRect(QRectF(-w / 2, -h * 0.62, w, h * 0.035))
            painter.drawRect(QRectF(-w / 2, -h * 0.56, w, h * 0.018))
            painter.setBrush(QColor(30, 30, 36))
            painter.drawRoundedRect(QRectF(-w * 0.62, -h * 0.34, w * 1.24, h * 0.07), w * 0.2, w * 0.2)
            painter.restore()
    painter.restore()


def draw_front(painter: QPainter, prop: str, outfit: str, skin, size: float, prop_scale: float = 1.0) -> None:
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    if outfit == "summer":
        _ring_arc(painter, size, skin.sw, front=True)
    if prop == "keyboard":
        _keyboard(painter, skin.sw, size * prop_scale)
    painter.restore()


def _keyboard(painter: QPainter, sw: float, size: float) -> None:
    w, h = sw * 0.86, size * 0.19
    top_w = w * 0.90
    y1, y0 = -size * 0.012, -size * 0.012 - h
    body = QPainterPath(QPointF(-top_w / 2, y0))
    body.lineTo(QPointF(top_w / 2, y0))
    body.lineTo(QPointF(w / 2, y1))
    body.lineTo(QPointF(-w / 2, y1))
    body.closeSubpath()
    g = QLinearGradient(0, y0, 0, y1)
    g.setColorAt(0.0, QColor("#C9CDD4"))
    g.setColorAt(1.0, QColor("#9EA3AD"))
    painter.setPen(QPen(QColor("#7C818B"), size * 0.006))
    painter.setBrush(QBrush(g))
    painter.drawPath(body)
    painter.setPen(Qt.NoPen)
    rows, cols = 4, 13
    for r in range(rows):
        t0, t1 = (r + 0.16) / rows, (r + 0.90) / rows
        ya, yb = y0 + h * (0.06 + 0.88 * t0), y0 + h * (0.06 + 0.88 * t1)
        row_w = top_w + (w - top_w) * (r + 0.5) / rows
        n = cols if r < rows - 1 else 5
        for c in range(n):
            if r == rows - 1:                       # ultima riga: barra spaziatrice larga
                spans = ((0.03, 0.14), (0.16, 0.27), (0.29, 0.71), (0.73, 0.84), (0.86, 0.97))
                fa, fb = spans[c]
            else:
                fa, fb = (c + 0.10) / n * 0.94 + 0.03, (c + 0.90) / n * 0.94 + 0.03
            key = QRectF(-row_w / 2 + row_w * fa, ya, row_w * (fb - fa), yb - ya)
            painter.setBrush(QColor("#2C2F36"))
            painter.drawRoundedRect(key, size * 0.006, size * 0.006)
            painter.setBrush(QColor(255, 255, 255, 26))
            painter.drawRoundedRect(key.adjusted(0, 0, 0, -(yb - ya) * 0.55), size * 0.006, size * 0.006)
