"""Disegno realistico del cane: gradienti, pelo, occhio con iride.

Tutto procedurale (QPainter), niente immagini: sfondo sempre trasparente e
qualita' identica a ogni risoluzione. La forma dipende dalla razza (breeds.py).
"""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPainterPath,
                           QPen, QRadialGradient)

from .breeds import GOLDEN, Breed
from .render_types import Pose

UNIT = 100.0
GROUND = 95.0

# rumore deterministico: il pelo non deve "sfarfallare" tra un frame e l'altro
_RNG = random.Random(20251116)
_NOISE = [_RNG.uniform(-1.0, 1.0) for _ in range(4096)]


def _n(i: int) -> float:
    return _NOISE[i % len(_NOISE)]


def _mix(a: QColor, b: QColor, t: float) -> QColor:
    t = max(0.0, min(1.0, t))
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _rot(point: QPointF, pivot: QPointF, deg: float) -> QPointF:
    rad = math.radians(deg)
    dx, dy = point.x() - pivot.x(), point.y() - pivot.y()
    return QPointF(pivot.x() + dx * math.cos(rad) - dy * math.sin(rad),
                   pivot.y() + dx * math.sin(rad) + dy * math.cos(rad))


# --------------------------------------------------------------- texture pelo
def _edge_fur(painter: QPainter, path: QPainterPath, breed: Breed, seed: int,
              length: float = 1.3, step: float = 0.03, t0: float = 0.0, t1: float = 1.0) -> None:
    """Ciuffi lungo il contorno: rompe la silhouette vettoriale."""
    if breed.coat == "curly":
        _edge_curls(painter, path, breed, seed, t0, t1)
        return
    painter.save()
    tip = _mix(breed.c("base"), breed.c("light"), 0.45)
    i = seed
    t = t0
    while t < t1:
        i += 1
        p = path.pointAtPercent(t)
        ang = math.radians(-path.angleAtPercent(t) - 90.0)
        ln = length * (0.5 + 0.8 * abs(_n(i)))
        skew = 0.95 + 0.35 * _n(i * 3)   # ciuffo coricato sul profilo
        col = QColor(tip if _n(i * 7) > 0 else breed.c("base"))
        col.setAlpha(190)
        painter.setPen(QPen(col, 0.7 + 0.4 * abs(_n(i * 5)), Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(p, QPointF(p.x() + math.cos(ang + skew) * ln,
                                    p.y() + math.sin(ang + skew) * ln))
        t += step * (0.75 + 0.5 * abs(_n(i * 11)))
    painter.restore()


def _edge_curls(painter: QPainter, path: QPainterPath, breed: Breed, seed: int,
                t0: float = 0.0, t1: float = 1.0) -> None:
    """Bordo a ricci per il barboncino."""
    painter.save()
    painter.setPen(Qt.NoPen)
    i = seed
    t = t0
    r = breed.curl_size
    while t < t1:
        i += 1
        p = path.pointAtPercent(t)
        ang = math.radians(-path.angleAtPercent(t) - 90.0)
        rr = r * (0.7 + 0.5 * abs(_n(i)))
        c = QPointF(p.x() + math.cos(ang) * rr * 0.45, p.y() + math.sin(ang) * rr * 0.45)
        painter.setBrush(_mix(breed.c("base"), breed.c("light"), 0.25 + 0.5 * abs(_n(i * 3))))
        painter.drawEllipse(c, rr, rr * 0.92)
        t += 0.028 * (0.8 + 0.4 * abs(_n(i * 5)))
    painter.restore()


def _texture(painter: QPainter, path: QPainterPath, breed: Breed, seed: int,
             angle: float = -20.0, count: int = 70) -> None:
    """Pelo interno: tratti chiari/scuri ritagliati dentro la sagoma."""
    rect = path.boundingRect()
    painter.save()
    painter.setClipPath(path)
    rad = math.radians(angle)
    for k in range(count):
        i = seed + k * 13
        x = rect.left() + rect.width() * (0.5 + 0.5 * _n(i))
        y = rect.top() + rect.height() * (0.5 + 0.5 * _n(i * 3))
        ln = rect.width() * 0.08 * (0.4 + abs(_n(i * 5)))
        light = _n(i * 7) > 0
        col = QColor(_mix(breed.c("base"), breed.c("light") if light else breed.c("dark"), 0.75))
        col.setAlpha(60 if light else 48)
        painter.setPen(QPen(col, 0.45 + 0.4 * abs(_n(i * 11)), Qt.SolidLine, Qt.RoundCap))
        a = rad + 0.25 * _n(i * 17)
        painter.drawLine(QPointF(x, y), QPointF(x + math.cos(a) * ln, y + math.sin(a) * ln))
    if breed.coat == "curly":
        painter.setPen(Qt.NoPen)
        for k in range(int(count * 0.9)):
            i = seed + 7 + k * 29
            x = rect.left() + rect.width() * (0.5 + 0.5 * _n(i))
            y = rect.top() + rect.height() * (0.5 + 0.5 * _n(i * 3))
            rr = breed.curl_size * (0.45 + 0.4 * abs(_n(i * 5)))
            col = QColor(_mix(breed.c("base"), breed.c("light"), 0.6 if _n(i * 7) > 0 else 0.0))
            col.setAlpha(90)
            painter.setBrush(col)
            painter.drawEllipse(QPointF(x, y), rr, rr)
    painter.restore()


def _volume(painter: QPainter, path: QPainterPath, breed: Breed,
            top_light: float = 1.0) -> None:
    """Riempie una sagoma con un gradiente che da' volume."""
    rect = path.boundingRect()
    grad = QLinearGradient(rect.center().x(), rect.top(), rect.center().x(), rect.bottom())
    grad.setColorAt(0.0, _mix(breed.c("base"), breed.c("light"), 0.75 * top_light))
    grad.setColorAt(0.42, breed.c("base"))
    grad.setColorAt(1.0, _mix(breed.c("base"), breed.c("dark"), 0.85))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawPath(path)


# ------------------------------------------------------------------- elementi
def _taper_path(a: QPointF, b: QPointF, w0: float, w1: float) -> QPainterPath:
    """Segmento rastremato (arto): piu' largo in alto, piu' stretto in basso."""
    dx, dy = b.x() - a.x(), b.y() - a.y()
    ln = max(1e-3, math.hypot(dx, dy))
    nx, ny = -dy / ln, dx / ln
    path = QPainterPath(QPointF(a.x() + nx * w0, a.y() + ny * w0))
    path.lineTo(QPointF(b.x() + nx * w1, b.y() + ny * w1))
    path.quadTo(QPointF(b.x(), b.y() + w1 * 0.9), QPointF(b.x() - nx * w1, b.y() - ny * w1))
    path.lineTo(QPointF(a.x() - nx * w0, a.y() - ny * w0))
    path.closeSubpath()
    return path


def _paw(painter: QPainter, p: QPointF, w: float, breed: Breed, dark: bool) -> None:
    painter.setPen(Qt.NoPen)
    col = breed.c("dark") if dark else _mix(breed.c("cream"), breed.c("base"), 0.35)
    painter.setBrush(col)
    painter.drawEllipse(QRectF(p.x() - w * 0.95, p.y() - w * 0.75, w * 1.9, w * 1.45))
    if not dark:
        painter.setPen(QPen(_mix(col, breed.c("dark"), 0.5), 0.7, Qt.SolidLine, Qt.RoundCap))
        for k in (-0.3, 0.25):
            painter.drawLine(QPointF(p.x() + w * k, p.y() + w * 0.1),
                             QPointF(p.x() + w * k - w * 0.1, p.y() + w * 0.6))
        painter.setPen(Qt.NoPen)


def _leg(painter: QPainter, breed: Breed, hip: QPointF, length: float,
         thigh_deg: float, shin_deg: float, width: float, far: bool,
         rear: bool, seed: int, feather: float = 1.0) -> None:
    knee = _rot(QPointF(hip.x(), hip.y() + length * 0.55), hip, thigh_deg)
    paw = _rot(QPointF(knee.x(), knee.y() + length * 0.45), knee, shin_deg)
    shade = QColor(breed.c("dark")) if far else breed.c("base")

    painter.save()
    painter.setPen(Qt.NoPen)
    if rear:  # massa della coscia
        thigh = QPainterPath()
        thigh.addEllipse(QRectF(hip.x() - width * 1.5, hip.y() - width * 1.25,
                                width * 3.0, width * 2.9))
        if far:
            painter.setBrush(shade)
            painter.drawPath(thigh)
        else:
            _volume(painter, thigh, breed)
            _texture(painter, thigh, breed, seed + 31, angle=70.0, count=22)

    upper = _taper_path(hip, knee, width * 0.95, width * 0.72)
    lower = _taper_path(knee, paw, width * 0.72, width * 0.52)
    for path in (upper, lower):
        if far:
            painter.setBrush(shade)
            painter.setPen(Qt.NoPen)
            painter.drawPath(path)
        else:
            _volume(painter, path, breed, top_light=0.6)
            _texture(painter, path, breed, seed + 17, angle=80.0, count=14)
    if not far and feather > 0.05:
        # frange dietro l'arto
        fr = QPainterPath(QPointF(hip.x() + width * 0.8, hip.y() + length * 0.1))
        fr.quadTo(QPointF(knee.x() + width * 1.5, knee.y()),
                  QPointF(paw.x() + width * 0.6, paw.y() - length * 0.18))
        _edge_fur(painter, fr, breed, seed + 61, length=3.0 * feather, step=0.08)
    _paw(painter, paw, width * 0.8, breed, far)
    painter.restore()


def _tail(painter: QPainter, breed: Breed, root: QPointF, angle: float, seed: int) -> None:
    rad = math.radians(angle)
    mid = QPointF(root.x() + 13 * math.cos(rad), root.y() + 13 * math.sin(rad))
    tip = QPointF(root.x() + 25 * math.cos(rad - 0.5), root.y() + 25 * math.sin(rad - 0.5))
    spine = QPainterPath(root)
    spine.quadTo(mid, tip)
    painter.save()
    painter.setPen(Qt.NoPen)
    if breed.tail == "pompom":
        painter.setPen(QPen(breed.c("base"), 4.0, Qt.SolidLine, Qt.RoundCap))
        painter.drawPath(spine)
        painter.setPen(Qt.NoPen)
        pom = QPainterPath()
        pom.addEllipse(tip, 8.0, 7.5)
        _volume(painter, pom, breed)
        _edge_curls(painter, pom, breed, seed + 5)
    else:
        body = QPainterPath(QPointF(root.x(), root.y() - 4))
        body.quadTo(QPointF(mid.x(), mid.y() - 7), QPointF(tip.x(), tip.y() - 3))
        body.quadTo(QPointF(mid.x() + 3, mid.y() + 7), QPointF(root.x(), root.y() + 4))
        body.closeSubpath()
        _volume(painter, body, breed)
        _texture(painter, body, breed, seed + 3, angle=math.degrees(rad), count=26)
        _edge_fur(painter, body, breed, seed + 9, length=3.0, step=0.022)
    painter.restore()


def _eye(painter: QPainter, breed: Breed, center: QPointF, open_amount: float) -> None:
    if open_amount <= 0.12:
        painter.setPen(QPen(breed.c("dark").darker(140), 1.2, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(QPointF(center.x() - 3.2, center.y()), QPointF(center.x() + 2.6, center.y() - 0.4))
        painter.setPen(Qt.NoPen)
        return
    h = 5.4 * open_amount
    almond = QPainterPath(QPointF(center.x() - 3.6, center.y()))
    almond.quadTo(QPointF(center.x() - 0.6, center.y() - h), QPointF(center.x() + 3.2, center.y() - h * 0.2))
    almond.quadTo(QPointF(center.x() - 0.2, center.y() + h * 0.75), QPointF(center.x() - 3.6, center.y()))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QColor("#17110C"))
    painter.drawPath(almond)
    painter.save()
    painter.setClipPath(almond)
    iris = QRadialGradient(center.x() - 0.2, center.y() - h * 0.1, 3.2)
    iris.setColorAt(0.0, QColor(breed.iris).lighter(145))
    iris.setColorAt(0.65, QColor(breed.iris))
    iris.setColorAt(1.0, QColor(breed.iris).darker(220))
    painter.setBrush(QBrush(iris))
    painter.drawEllipse(QPointF(center.x() - 0.2, center.y() - h * 0.1), 2.9, 2.9)
    painter.setBrush(QColor("#120C08"))
    painter.drawEllipse(QPointF(center.x() - 0.2, center.y() - h * 0.1), 1.35, 1.5)
    painter.setBrush(QColor(255, 255, 255, 235))
    painter.drawEllipse(QPointF(center.x() - 1.4, center.y() - h * 0.55), 0.85, 0.7)
    painter.setBrush(QColor(255, 255, 255, 90))
    painter.drawEllipse(QPointF(center.x() + 1.3, center.y() + h * 0.1), 0.45, 0.4)
    painter.restore()
    # palpebra
    lid = QPainterPath(QPointF(center.x() - 3.4, center.y() - h * 0.1))
    lid.quadTo(QPointF(center.x() - 0.6, center.y() - h * 1.05), QPointF(center.x() + 3.0, center.y() - h * 0.3))
    painter.setPen(QPen(QColor(60, 40, 26, 150), 0.55, Qt.SolidLine, Qt.RoundCap))
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(lid)
    painter.setPen(Qt.NoPen)


def _nose(painter: QPainter, breed: Breed, tip: QPointF) -> None:
    path = QPainterPath(QPointF(tip.x() + 0.4, tip.y() - 3.2))
    path.cubicTo(QPointF(tip.x() + 5.2, tip.y() - 3.6), QPointF(tip.x() + 5.6, tip.y() + 3.0),
                 QPointF(tip.x() + 1.4, tip.y() + 3.6))
    path.cubicTo(QPointF(tip.x() - 2.6, tip.y() + 3.8), QPointF(tip.x() - 3.2, tip.y() - 2.0),
                 QPointF(tip.x() + 0.4, tip.y() - 3.2))
    grad = QLinearGradient(tip.x(), tip.y() - 3.0, tip.x(), tip.y() + 3.2)
    grad.setColorAt(0.0, QColor(breed.nose).lighter(185))
    grad.setColorAt(0.45, QColor(breed.nose))
    grad.setColorAt(1.0, QColor(breed.nose).darker(160))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawPath(path)
    painter.setBrush(QColor(255, 255, 255, 120))
    painter.drawEllipse(QPointF(tip.x() + 1.6, tip.y() - 1.5), 1.1, 0.7)
    painter.setBrush(QColor(0, 0, 0, 170))
    painter.drawEllipse(QPointF(tip.x() + 0.5, tip.y() + 0.9), 0.75, 1.05)


def _ear(painter: QPainter, breed: Breed, flop: float, seed: int, behind: bool) -> None:
    painter.save()
    painter.translate(5.5 if behind else 3.0, -7.5)
    painter.rotate((10.0 if behind else 2.0) + flop * (16.0 if behind else 26.0))
    w, ln = breed.ear_width, breed.ear_len
    path = QPainterPath(QPointF(0, 0))
    path.cubicTo(QPointF(w * 0.95, ln * 0.18), QPointF(w * 0.9, ln * 0.82), QPointF(w * 0.1, ln))
    path.cubicTo(QPointF(-w * 0.55, ln * 0.78), QPointF(-w * 0.6, ln * 0.2), QPointF(0, 0))
    grad = QLinearGradient(0, 0, 0, ln)
    deep = QColor(breed.dark).darker(135 if behind else 112)
    grad.setColorAt(0.0, _mix(breed.c("base"), deep, 0.45))
    grad.setColorAt(1.0, deep)
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawPath(path)
    if not behind:  # piega interna
        inner = QPainterPath(QPointF(w * 0.12, ln * 0.12))
        inner.cubicTo(QPointF(w * 0.72, ln * 0.3), QPointF(w * 0.6, ln * 0.72), QPointF(w * 0.08, ln * 0.86))
        inner.cubicTo(QPointF(w * 0.3, ln * 0.6), QPointF(w * 0.34, ln * 0.34), QPointF(w * 0.12, ln * 0.12))
        shade = QColor(deep.darker(118))
        shade.setAlpha(150)
        painter.setBrush(shade)
        painter.drawPath(inner)
    if not behind:
        _texture(painter, path, breed, seed + 41, angle=85.0, count=26)
    _edge_fur(painter, path, breed, seed + 23, length=2.2, step=0.045, t0=0.25, t1=0.75)
    painter.restore()


def _head(painter: QPainter, pose: Pose, breed: Breed, anchor: QPointF, seed: int) -> None:
    painter.save()
    painter.translate(anchor)
    painter.rotate(pose.head_tilt + pose.head_drop * 30.0)

    _ear(painter, breed, pose.ear_flop, seed, behind=True)

    ml, md = breed.muzzle_len, breed.muzzle_depth
    # cranio
    skull = QPainterPath(QPointF(-6.0, -11.5))
    skull.cubicTo(QPointF(7.0, -14.5), QPointF(14.5, -5.0), QPointF(12.0, 6.0))
    skull.cubicTo(QPointF(9.5, 13.0), QPointF(-2.0, 14.5), QPointF(-7.5, 10.0))
    skull.cubicTo(QPointF(-12.0, 6.0), QPointF(-13.0, -7.0), QPointF(-6.0, -11.5))
    _volume(painter, skull, breed)

    # muso
    muzzle = QPainterPath(QPointF(-5.0, -3.5))
    muzzle.cubicTo(QPointF(-ml * 0.55, -md * 0.55), QPointF(-ml, -md * 0.3), QPointF(-ml - 1.0, md * 0.1))
    muzzle.cubicTo(QPointF(-ml - 1.5, md * 0.75), QPointF(-ml * 0.5, md * 1.05), QPointF(-2.0, md * 0.95))
    muzzle.cubicTo(QPointF(1.5, md * 0.6), QPointF(0.5, 0.0), QPointF(-5.0, -3.5))
    rect = muzzle.boundingRect()
    grad = QLinearGradient(rect.center().x(), rect.top(), rect.center().x(), rect.bottom())
    grad.setColorAt(0.0, _mix(breed.c("light"), breed.c("cream"), 0.55))
    grad.setColorAt(0.5, _mix(breed.c("base"), breed.c("light"), 0.8))
    grad.setColorAt(1.0, _mix(breed.c("base"), breed.c("dark"), 0.55))
    painter.setPen(Qt.NoPen)
    painter.setBrush(QBrush(grad))
    painter.drawPath(muzzle)
    _texture(painter, muzzle, breed, seed + 51, angle=200.0, count=20)

    # bocca
    if pose.mouth_open > 0.02:
        open_h = 2.0 + 7.5 * pose.mouth_open
        mouth = QPainterPath(QPointF(-ml * 0.92, md * 0.45))
        mouth.quadTo(QPointF(-ml * 0.45, md * 0.35 + open_h), QPointF(-3.0, md * 0.55 + open_h * 0.45))
        mouth.quadTo(QPointF(-ml * 0.5, md * 0.95), QPointF(-ml * 0.92, md * 0.45))
        painter.setBrush(QColor("#5E2A26"))
        painter.drawPath(mouth)
        painter.setBrush(QColor(255, 255, 255, 235))
        painter.drawEllipse(QRectF(-ml * 0.88, md * 0.42, 2.4, 1.9))
        if pose.tongue > 0.02:
            painter.setBrush(QColor("#E0697F"))
            painter.drawEllipse(QRectF(-ml * 0.8, md * 0.55 + open_h * 0.25,
                                       7.5, 3.0 + 4.5 * pose.tongue))
    else:
        lip = QPainterPath(QPointF(-ml * 0.9, md * 0.5))
        lip.quadTo(QPointF(-ml * 0.6, md * 0.92), QPointF(-ml * 0.22, md * 0.72))
        painter.setPen(QPen(QColor(70, 44, 30, 170), 0.55, Qt.SolidLine, Qt.RoundCap))
        painter.setBrush(Qt.NoBrush)
        painter.drawPath(lip)
        painter.setPen(Qt.NoPen)
        if pose.tongue > 0.02:
            painter.setBrush(QColor("#E0697F"))
            painter.drawEllipse(QRectF(-ml * 0.72, md * 0.7, 6.0, 2.0 + 4.0 * pose.tongue))

    if breed.topknot:  # ciuffo del barboncino, sopra la fronte
        knot = QPainterPath()
        knot.addEllipse(QRectF(-4.0, -19.0, 17.0, 12.5))
        _volume(painter, knot, breed)
        _edge_curls(painter, knot, breed, seed + 77)

    _nose(painter, breed, QPointF(-ml - 1.0, md * 0.1))
    _eye(painter, breed, QPointF(-4.6, -2.2), pose.eye_open)

    # sopracciglio chiaro
    painter.setBrush(QColor(255, 246, 225, 38))
    painter.drawEllipse(QRectF(-7.6, -8.6, 5.6, 2.0))

    if pose.blush > 0.02:
        painter.setBrush(QColor(224, 118, 118, int(120 * pose.blush)))
        painter.drawEllipse(QRectF(-10.0, 2.0, 7.0, 4.2))

    if breed.coat == "curly":
        _edge_curls(painter, skull, breed, seed + 13, 0.0, 0.42)
    else:
        _edge_fur(painter, skull, breed, seed + 13, length=1.6, step=0.07, t0=0.45, t1=0.95)
    _ear(painter, breed, pose.ear_flop, seed, behind=False)
    painter.restore()


# ---------------------------------------------------------------------- corpo
def _body_path(body_x: float, body_y: float, breed: Breed, lie: float) -> QPainterPath:
    d = breed.body_depth
    top = body_y - 17.0 * d + lie * 4.0
    bottom = body_y + 19.0 * d - lie * 6.0
    path = QPainterPath(QPointF(body_x - 26.0, body_y - 6.0))          # base collo
    path.cubicTo(QPointF(body_x - 18.0, top - 3.0), QPointF(body_x + 6.0, top - 1.0),
                 QPointF(body_x + 19.0, top + 1.5))                     # dorso
    path.cubicTo(QPointF(body_x + 27.0, top + 4.0), QPointF(body_x + 30.0, body_y + 2.0),
                 QPointF(body_x + 25.0, bottom - 3.0))                  # groppa
    path.cubicTo(QPointF(body_x + 16.0, bottom + 2.0), QPointF(body_x + 2.0, bottom + 1.0),
                 QPointF(body_x - 12.0, bottom - 1.0))                  # pancia
    path.cubicTo(QPointF(body_x - 22.0, bottom - 3.0), QPointF(body_x - 27.0, body_y + 4.0),
                 QPointF(body_x - 26.0, body_y - 6.0))                  # petto
    path.closeSubpath()
    return path


def draw_dog(painter: QPainter, pose: Pose, size: float, breed: Breed = GOLDEN) -> None:
    """Disegna il cane in un quadrato size x size, zampe appoggiate in basso."""
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing, True)
    painter.scale(size / UNIT, size / UNIT)
    seed = 101

    if pose.shadow > 0.01:
        grad = QRadialGradient(UNIT / 2, GROUND + 1.0, 30.0)
        grad.setColorAt(0.0, QColor(0, 0, 0, int(80 * pose.shadow)))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setPen(Qt.NoPen)
        painter.setBrush(QBrush(grad))
        painter.drawEllipse(QRectF(20.0, GROUND - 5.0, 60.0, 12.0))

    painter.translate(UNIT / 2, GROUND - 32.0 * min(1.0, abs(pose.spin) / 90.0))
    painter.rotate(pose.spin)
    painter.translate(0.0, 32.0 * min(1.0, abs(pose.spin) / 90.0))
    if pose.facing > 0:                      # il disegno base guarda a sinistra
        painter.scale(-1.0, 1.0)
    painter.scale(1.0 / max(pose.squash, 0.2) ** 0.5, pose.squash)
    painter.translate(-UNIT / 2, -GROUND)

    sit, lie = pose.sit, pose.lie
    body_y = 52.0 + pose.body_bob + sit * 13.0 + lie * 25.0
    body_x = 49.0 - sit * 2.0
    hip = QPointF(body_x + 15.0 - sit * 7.0, body_y + 11.0 + sit * 3.0)
    shoulder = QPointF(body_x - 15.0, body_y + 11.0)
    swing = pose.leg_swing * (1.0 - sit) * (1.0 - lie)
    flail = pose.flail
    rear_len = (27.0 - sit * 13.0 - lie * 20.0) * breed.leg_scale
    front_len = (26.0 - sit * 10.0 - lie * 19.0) * breed.leg_scale
    feather = 0.0 if breed.coat == "curly" else 1.0

    def rear_leg(phase: float, far: bool) -> None:
        a = math.sin(pose.leg_phase + phase) * swing * 34.0 + math.sin(pose.leg_phase * 3 + phase) * flail * 45.0
        _leg(painter, breed, QPointF(hip.x() - (3.0 if far else 0.0), hip.y()), rear_len,
             a + sit * 52.0 + lie * 82.0, -a * 0.55 - sit * 100.0 - lie * 40.0,
             5.2, far, True, seed + (1 if far else 2), feather)

    def front_leg(phase: float, far: bool) -> None:
        a = math.sin(pose.leg_phase + phase) * swing * 36.0 + math.sin(pose.leg_phase * 3 + phase + 1) * flail * 50.0
        _leg(painter, breed, QPointF(shoulder.x() + (3.0 if far else 0.0), shoulder.y()), front_len,
             a + lie * 74.0, -a * 0.45 - lie * 42.0,
             4.6, far, False, seed + (3 if far else 4), feather)

    painter.setPen(Qt.NoPen)
    _tail(painter, breed, QPointF(body_x + 22.0, body_y - 8.0 + sit * 6.0),
          pose.tail_angle + math.sin(pose.tail_phase) * pose.tail_wag, seed)

    rear_leg(0.0, True)
    front_leg(math.pi, True)

    body = _body_path(body_x, body_y, breed, lie)
    painter.save()
    painter.translate(body_x, body_y)
    painter.rotate(pose.body_tilt + sit * 25.0 + lie * 4.0)
    painter.translate(-body_x, -body_y)
    _volume(painter, body, breed)
    _texture(painter, body, breed, seed + 7, angle=-12.0, count=190)
    # pancia e petto chiari
    belly = QPainterPath()
    belly.addEllipse(QRectF(body_x - 22.0, body_y + 1.0, 42.0, 13.0 - lie * 4.0))
    painter.save()
    painter.setClipPath(body)
    cream = QColor(breed.cream)
    cream.setAlpha(170)
    painter.setBrush(cream)
    painter.setPen(Qt.NoPen)
    painter.drawPath(belly)
    painter.restore()
    _edge_fur(painter, body, breed, seed + 19, length=1.8, step=0.022)
    painter.restore()

    rear_leg(math.pi, False)
    front_leg(0.0, False)

    # collo
    neck_base = QPointF(body_x - 21.0 + lie * 2.0, body_y - 6.0 - sit * 4.0)
    head_anchor = QPointF(neck_base.x() - 9.0, neck_base.y() - 13.0 - sit * 5.0
                          + lie * 20.0 + pose.head_drop * 14.0)
    neck = _taper_path(neck_base, head_anchor, 8.5, 7.0)
    _volume(painter, neck, breed)
    _texture(painter, neck, breed, seed + 29, angle=250.0, count=26)
    _edge_fur(painter, neck, breed, seed + 37, length=1.5, step=0.09)

    _head(painter, pose, breed, head_anchor, seed)
    painter.restore()
