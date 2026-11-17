"""Pelle fotografica: la foto vera del cane, animata con un rig a mesh.

Niente rotazioni rigide dell'intera foto: la testa e' una griglia di vertici
con pesi (testa, profondita' del muso, orecchie, sopracciglia, mandibola).
Girare la testa sposta di piu' cio' che e' piu' vicino (naso) e di meno cio'
che e' lontano: parallasse, quindi sembra tridimensionale. Gli spostamenti
sono volutamente piccoli: il viso non deve mai deformarsi.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QImage, QLinearGradient, QPainter,
                           QPainterPath, QPen, QPolygonF, QRadialGradient, QTransform)

from .render_types import Pose

PAD_HEAD = 0.474    # spazio sopra la testa (cappelli), in "teste" (distanza cima-collo)
PAD_SIDE = 0.14     # spazio ai lati, frazione della larghezza
MARGIN = 10         # px attorno al buffer per gli spostamenti
AWAY_SHRINK = 0.45  # quanto rimpicciolisce quando si allontana del tutto
LEG_LIFT = 0.30     # zampa sollevata al massimo: frazione della lunghezza della gamba
LEG_SWING = 0.62    # oscillazione al massimo, in radianti (circa 35 gradi)
MORPH_TIME = 0.55   # durata del morph tra due viste, secondi

# Tutte le misure del rig sono in "teste": cosi' lo stesso codice anima un primo
# piano (la testa riempie lo sprite) e una figura intera (la testa e' un quarto).


def _smooth(a: float, b: float, x: float) -> float:
    t = max(0.0, min(1.0, (x - a) / (b - a)))
    return t * t * (3.0 - 2.0 * t)


def _gauss(u: float, v: float, cu: float, cv: float, su: float, sv: float) -> float:
    return math.exp(-(((u - cu) / su) ** 2 + ((v - cv) / sv) ** 2))


@dataclass
class Eye:
    x: float
    y: float
    rx: float
    ry: float
    angle: float = 0.0
    lid: str = "#C8A47C"


@dataclass
class Rig:
    """Punti di riferimento sullo sprite, normalizzati 0..1."""

    eyes: list[Eye] = field(default_factory=list)
    nose: tuple[float, float] = (0.6, 0.45)
    mouth: tuple[float, float] = (0.6, 0.63)
    head_top: tuple[float, float] = (0.5, 0.02)
    neck: tuple[float, float] = (0.5, 0.78)
    ear_l: tuple[float, float, float, float] = (0.15, 0.46, 0.24, 0.20)   # centro u,v + base u,v
    ear_r: tuple[float, float, float, float] = (0.93, 0.34, 0.84, 0.17)
    feet: float = 1.03                # quanto lo sprite scende sotto il bordo (nasconde il taglio)
    tongue: str = "#D8748A"
    face: bool = True                 # False = vista di spalle: nessun viso da animare
    full: bool = False                # figura intera appoggiata sul bordo (non un busto affacciato)
    height: float = 1.0               # altezza di disegno rispetto alla taglia scelta
    open_mouth: bool = False          # nella foto la bocca e' gia' aperta (lingua vera in vista)
    # zampe animabili: (u_attacco, v_attacco, u_piede, v_piede, larghezza) normalizzati, da sinistra a destra
    legs: list[tuple[float, float, float, float, float]] = field(default_factory=list)

    @property
    def head(self) -> float:
        """Altezza della testa (cima-collo) come frazione dell'altezza dello sprite."""
        return max(0.06, self.neck[1] - self.head_top[1])

    @classmethod
    def from_dict(cls, data: dict) -> "Rig":
        rig = cls(eyes=[Eye(**e) for e in data.get("eyes", [])])
        for key in ("nose", "mouth", "head_top", "neck", "ear_l", "ear_r"):
            if key in data:
                setattr(rig, key, tuple(data[key]))
        rig.feet = float(data.get("feet", rig.feet))
        rig.tongue = data.get("tongue", rig.tongue)
        rig.face = bool(data.get("face", True)) and len(rig.eyes) >= 2
        rig.full = bool(data.get("full", False))
        rig.height = float(data.get("height", 1.0))
        rig.open_mouth = bool(data.get("open_mouth", False))
        rig.legs = sorted((tuple(float(x) for x in leg) for leg in data.get("legs", []) if len(leg) == 5),
                          key=lambda g: g[2])[:2]
        return rig


class Skin:
    def __init__(self, name: str, image: QImage, rig: Rig, paw: QImage | None = None) -> None:
        self.name = name
        self.image = image.convertToFormat(QImage.Format_ARGB32_Premultiplied)
        self.rig = rig
        self.paw = paw.convertToFormat(QImage.Format_ARGB32_Premultiplied) if paw is not None else None
        self.outfit = ""
        # stato dinamico (inseguimento morbido + molle delle orecchie)
        self.yaw = self.pitch = self.roll = 0.0
        self.brow = self.jaw = self.sink = 0.0
        self.ear = [0.0, 0.0]
        self.ear_v = [0.0, 0.0]
        self.lift = [0.0, 0.0]          # zampe (figura intera): sollevamento inseguito con inerzia
        self.swing = [0.0, 0.0]
        self.clock = 0.0
        self._prev = (0.0, 0.0)
        self._m = MARGIN                # margine del buffer dell'ultimo render (cresce durante il morph)
        self._ext: tuple[float, float] | None = None
        self._fields: dict = {}
        # cache dipendenti dalla taglia
        self._size = -1.0
        self._tex: QImage | None = None
        self._static: QImage | None = None
        self._cells: list[bool] = []
        self._weights: list[tuple] = []

    # ------------------------------------------------------------- caricamento
    @property
    def aspect(self) -> float:
        return self.image.width() / max(1, self.image.height())

    @classmethod
    def load(cls, folder: str | Path) -> "Skin":
        """Una sola vista della cartella (il primo piano se c'e'). Tutte: SkinSet.load()."""
        views = SkinSet.load(folder).views
        return views.get("busto") or next(iter(views.values()))

    def set_outfit(self, outfit: str) -> None:
        if outfit != self.outfit:
            self.outfit = outfit
            self._size = -1.0          # rigenera lo strato statico

    # ------------------------------------------------------------- geometria
    def _prepare(self, size: float) -> None:
        """Texture alla taglia di disegno + pesi dei vertici (una volta per taglia)."""
        if abs(size - self._size) < 0.5 and self._tex is not None:
            return
        self._size = size
        img = self.image
        s = size / img.height()
        self.s = s
        self.sw, self.sh = img.width() * s, img.height() * s
        r = self.rig
        H = r.head
        hs = self.hs = H * self.sh                 # la "testa" in pixel
        wd = hs / self.sw                          # una testa, in unita' u
        self.px, self.py = self.sw * PAD_SIDE, hs * PAD_HEAD
        tw, th = int(self.sw + 2 * self.px) + 1, int(self.sh + self.py) + 1
        self.tw, self.th = tw, th

        tex = QImage(tw, th, QImage.Format_ARGB32_Premultiplied)
        tex.fill(0)
        p = QPainter(tex)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawImage(QRectF(self.px, self.py, self.sw, self.sh), img)
        p.end()
        self._tex = tex

        # strato statico: sprite + accessori che seguono la testa
        static = tex.copy()
        if self.outfit:
            from . import outfits

            p = QPainter(static)
            p.setRenderHint(QPainter.Antialiasing, True)
            outfits.draw_on_head(p, self.outfit, self)
            p.end()
        self._static = static

        # griglia: fitta sulla testa (dove si deforma), larga sul corpo
        step = hs / 10.0
        fine_y = self.py + (r.neck[1] + 0.35 * H) * self.sh
        # zampe: geometria in pixel della texture (attacco, asse unitario, normale, lunghezza, larghezza)
        self._legs = []
        leg_y0, leg_x = th + 1.0, []
        for pu, pv, fu, fv, wu in r.legs:
            pxv, pyv = self.px + pu * self.sw, self.py + pv * self.sh
            ax, ay = (fu - pu) * self.sw, (fv - pv) * self.sh
            ln = math.hypot(ax, ay) or 1.0
            side = 1.0 if fu < r.neck[0] else -1.0
            self._legs.append((pxv, pyv, ax / ln, ay / ln, -ay / ln, ax / ln, ln, wu * self.sw, side))
            leg_y0 = min(leg_y0, pyv - 0.05 * self.sh)
            leg_x.append((min(pxv, self.px + fu * self.sw) - wu * self.sw * 0.9,
                          max(pxv, self.px + fu * self.sw) + wu * self.sw * 0.9))
        ys = [0.0]
        while ys[-1] < th - 0.5:
            sy = step if ys[-1] < fine_y else (step * 1.6 if ys[-1] >= leg_y0 else step * 3.0)
            ys.append(min(float(th), ys[-1] + sy))
        if len(ys) > 2 and ys[-1] - ys[-2] < step * 0.35:
            ys.pop(-2)
        cx = self.px + r.neck[0] * self.sw
        xs = [0.0]
        while xs[-1] < tw - 0.5:
            near = abs(xs[-1] + step * 0.55 - cx) < hs * 1.25
            in_leg = any(a <= xs[-1] <= b for a, b in leg_x)
            sx = step * (1.1 if near else (1.5 if in_leg else 2.6))
            xs.append(min(float(tw), xs[-1] + sx))
        if len(xs) > 2 and xs[-1] - xs[-2] < step * 0.35:
            xs.pop(-2)
        self._xs, self._ys = xs, ys

        # pesi per vertice
        top = r.head_top[1]
        hx, hy = (r.head_top[0] + r.neck[0]) / 2, top + 0.5 * H
        radius = 0.80 * hs
        self._weights = []
        self._src = []
        for y in ys:
            for x in xs:
                u, v = (x - self.px) / self.sw, (y - self.py) / self.sh
                wh = wb = wj = we_l = we_r = depth = 0.0
                if r.face:
                    dist = math.hypot((u - hx) * self.sw, (v - hy) * self.sh)
                    wh = (1.0 - _smooth(top + 0.842 * H, top + 1.184 * H, v)) \
                        * (1.0 - _smooth(radius, radius * 1.6, dist))
                    depth = (0.80 * _gauss(u, v, r.nose[0], r.nose[1], 0.288 * wd, 0.29 * H)
                             + 0.30 * _gauss(u, v, hx + 0.036 * wd, top + 0.42 * H, 0.60 * wd, 0.605 * H))
                    we_l = _gauss(u, v, r.ear_l[0], r.ear_l[1], 0.114 * wd, 0.26 * H)
                    we_r = _gauss(u, v, r.ear_r[0], r.ear_r[1], 0.114 * wd, 0.26 * H)
                    for eye in r.eyes:
                        wb = max(wb, _gauss(u, v, eye.x, eye.y - 0.0855 * H, 0.132 * wd, 0.066 * H))
                    wj = _gauss(u, v, r.mouth[0], r.mouth[1] + 0.072 * H, 0.204 * wd, 0.0855 * H)
                wc = _smooth(r.neck[1] - 0.08 * H, r.neck[1] + 0.29 * H, v) \
                    * (1.0 - _smooth(r.neck[1] + 0.9 * H, r.neck[1] + 1.7 * H, v))
                self._src.append((x, y))
                self._weights.append((u, v, wh, depth, we_l, we_r, wb, wj, wc, self._leg_weights(x, y)))

        # celle completamente vuote: non si disegnano
        self._cells = []
        for j in range(len(ys) - 1):
            for i in range(len(xs) - 1):
                hit = False
                for fy in (0.06, 0.35, 0.65, 0.94):
                    for fx in (0.06, 0.35, 0.65, 0.94):
                        xx = min(tw - 1, int(xs[i] + (xs[i + 1] - xs[i]) * fx))
                        yy = min(th - 1, int(ys[j] + (ys[j + 1] - ys[j]) * fy))
                        if static.pixelColor(xx, yy).alpha() > 0:
                            hit = True
                            break
                    if hit:
                        break
                self._cells.append(hit)

    def _leg_weights(self, x: float, y: float) -> tuple[float, ...]:
        """Quanto ogni zampa trascina il vertice: 0 sul corpo, cresce lungo la gamba, 1 sul piede."""
        out = []
        for pxv, pyv, ax, ay, nx, ny, ln, wid, _side in self._legs:
            dx, dy = x - pxv, y - pyv
            t = (dx * ax + dy * ay) / ln
            lat = abs(dx * nx + dy * ny)
            w_axis = _smooth(0.05, 0.85, t) * (1.0 - _smooth(1.25, 1.55, t))
            w_lat = 1.0 - _smooth(0.40 * wid, 0.88 * wid, lat)
            out.append(w_axis * w_lat)
        return tuple(out)

    def uv(self, u: float, v: float) -> QPointF:
        """Da coordinate normalizzate dello sprite a pixel della texture."""
        return QPointF(self.px + u * self.sw, self.py + v * self.sh)

    def bounds(self, size: float) -> QRectF:
        """Ingombro attorno al punto d'appoggio (centro in basso), per la maschera."""
        w = size * self.aspect
        pad = PAD_HEAD * self.rig.head
        return QRectF(-w * (0.5 + PAD_SIDE) - MARGIN, -size * (1 + pad) - MARGIN,
                      w * (1 + 2 * PAD_SIDE) + 2 * MARGIN, size * (1 + pad) + 2 * MARGIN + size * 0.12)

    def point(self, u: float, v: float, size: float) -> tuple[float, float]:
        """Un punto dello sprite (0..1) rispetto al punto d'appoggio, alla taglia data."""
        w = size * self.aspect
        return (u - 0.5) * w, -(1.0 - v) * size + size * (self.rig.feet - 1.0) + self.sink * size * 1.02

    # --------------------------------------------------------------- dinamica
    def advance(self, dt: float, pose: Pose, look: tuple[float, float] = (0.0, 0.0)) -> None:
        """Insegue i bersagli della posa con inerzia: niente scatti."""
        self.clock += dt
        t = self.clock
        # micro-movimenti da vivo: mai perfettamente fermo
        idle_yaw = 0.10 * math.sin(t * 0.43) + 0.05 * math.sin(t * 1.13 + 1.0)
        idle_pitch = 0.07 * math.sin(t * 0.37 + 2.0)
        idle_roll = 0.9 * math.sin(t * 0.29 + 0.5)
        calm = 1.0 - min(1.0, pose.lie + pose.sink)

        tgt_yaw = max(-1.0, min(1.0, pose.yaw + look[0] * 0.75 * calm + idle_yaw * calm))
        tgt_pitch = max(-1.0, min(1.0, pose.pitch + look[1] * 0.6 * calm + idle_pitch * calm
                                  + pose.head_drop * 0.8))
        tgt_roll = pose.head_tilt + pose.lie * 9.0 + idle_roll * calm
        tgt_roll += math.sin(pose.leg_phase) * 2.2 * pose.leg_swing
        if pose.flail > 0.05:
            tgt_roll += math.sin(pose.leg_phase * 2.0) * 7.0 * pose.flail

        k = min(1.0, dt * 7.0)
        prev_yaw, prev_roll = self.yaw, self.roll
        self.yaw += (tgt_yaw - self.yaw) * k
        self.pitch += (tgt_pitch - self.pitch) * k
        self.roll += (tgt_roll - self.roll) * min(1.0, dt * 9.0)
        self.brow += (pose.brow - self.brow) * min(1.0, dt * 10.0)
        self.jaw += (pose.mouth_open - self.jaw) * min(1.0, dt * 16.0)
        self.sink += (pose.sink - self.sink) * min(1.0, dt * 6.5)
        kl = min(1.0, dt * 22.0)
        for n, (lf, sw) in enumerate(((pose.lift_l, pose.swing_l), (pose.lift_r, pose.swing_r))):
            self.lift[n] += (lf - self.lift[n]) * kl
            self.swing[n] += (sw - self.swing[n]) * kl

        # orecchie: molla smorzata eccitata dai movimenti della testa
        if dt > 0:
            push = (self.yaw - prev_yaw) / dt * 5.5 + (self.roll - prev_roll) / dt * 0.55
            push += math.sin(pose.leg_phase * 2.0) * 9.0 * pose.leg_swing + pose.ear_flop * 6.0
            for n, sign in ((0, 1.0), (1, -1.0)):
                target = sign * push
                acc = (target - self.ear[n]) * 90.0 - self.ear_v[n] * 11.0
                self.ear_v[n] += acc * dt
                self.ear[n] += self.ear_v[n] * dt
                self.ear[n] = max(-14.0, min(14.0, self.ear[n]))

    # ---------------------------------------------------------------- disegno
    def _work_texture(self, pose: Pose) -> QImage:
        """Sprite + palpebre + bocca/lingua, ancora NON deformato."""
        closed = 1.0 - max(0.0, min(1.0, pose.eye_open))
        drawn_mouth = not self.rig.open_mouth and (pose.tongue > 0.02 or self.jaw > 0.03)
        if not self.rig.face or (closed <= 0.02 and not drawn_mouth):
            return self._static
        work = self._static.copy()
        p = QPainter(work)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if drawn_mouth:
            self._mouth(p, pose)
        if closed > 0.02 and self.outfit not in ("ski",):      # la maschera da sci copre gli occhi
            self._lids(p, closed)
        p.end()
        return work

    def _lids(self, p: QPainter, closed: float) -> None:
        """Palpebra: pelo vero (preso appena sopra l'occhio) che scende, con bordi sfumati."""
        tex = self._tex
        for eye in self.rig.eyes:
            c = self.uv(eye.x, eye.y)
            rx, ry = eye.rx * self.sw, eye.ry * self.sh
            bw, bh = int(rx * 2.6) + 2, int(ry * 2.8) + 2
            lid = QImage(bw, bh, QImage.Format_ARGB32_Premultiplied)
            lid.fill(0)
            q = QPainter(lid)
            q.setRenderHint(QPainter.Antialiasing, True)
            q.setRenderHint(QPainter.SmoothPixmapTransform, True)
            lid_h = bh * closed
            dest = QRectF(0, 0, bw, lid_h)
            src = QRectF(c.x() - bw / 2, c.y() - ry * 2.9, bw, ry * 1.7 * max(0.25, closed))
            q.drawImage(dest, tex, src)
            q.setPen(Qt.NoPen)
            q.setBrush(QColor(74, 50, 32, 70))             # resta nell'ombra dell'orbita
            q.drawRect(dest)
            # fessura dell'occhio chiuso: arco morbido verso il basso
            y_edge = min(lid_h, bh * 0.66)
            slit = QPainterPath(QPointF(bw * 0.14, y_edge - bh * 0.08))
            slit.quadTo(QPointF(bw * 0.5, y_edge + bh * 0.10), QPointF(bw * 0.86, y_edge - bh * 0.10))
            pen = QPen(QColor(36, 22, 14, int(110 + 120 * closed)), max(1.0, ry * 0.24))
            pen.setCapStyle(Qt.RoundCap)
            q.setPen(pen)
            q.setBrush(Qt.NoBrush)
            q.drawPath(slit)
            # maschera a sfumare: niente bordo netto attorno all'occhio
            q.setCompositionMode(QPainter.CompositionMode_DestinationIn)
            mask = QRadialGradient(bw / 2, bh / 2, bw / 2)
            mask.setColorAt(0.0, QColor(0, 0, 0, 255))
            mask.setColorAt(0.70, QColor(0, 0, 0, 255))
            mask.setColorAt(1.0, QColor(0, 0, 0, 0))
            q.setPen(Qt.NoPen)
            q.setBrush(QBrush(mask))
            q.scale(1.0, bh / bw)
            q.drawRect(QRectF(0, 0, bw, bw))
            q.end()
            p.save()
            p.translate(c)
            p.rotate(eye.angle)
            p.drawImage(QPointF(-bw / 2, -bh / 2), lid)
            p.restore()

    def _mouth(self, p: QPainter, pose: Pose) -> None:
        """Interno della bocca e lingua, disegnati prima della deformazione."""
        m = self.uv(*self.rig.mouth)
        w, h = self.hs * 1.2013, self.hs * 1.3158      # proporzioni tarate sul primo piano
        p.setPen(Qt.NoPen)
        if self.jaw > 0.03:
            gap = QRadialGradient(m.x(), m.y() + h * 0.008, w * 0.075)
            gap.setColorAt(0.0, QColor(34, 12, 14, 235))
            gap.setColorAt(0.7, QColor(40, 16, 16, 200))
            gap.setColorAt(1.0, QColor(40, 16, 16, 0))
            p.setBrush(QBrush(gap))
            p.drawEllipse(QRectF(m.x() - w * 0.075, m.y() - h * 0.004,
                                 w * 0.15, h * (0.012 + 0.03 * self.jaw)))
        t = max(0.0, min(1.0, pose.tongue))
        if t > 0.02:
            tw_, tl = w * 0.074, h * (0.018 + 0.085 * t)
            top = m.y() - h * 0.004
            path = QPainterPath(QPointF(m.x() - tw_ * 0.5, top))
            path.cubicTo(QPointF(m.x() - tw_ * 0.56, top + tl * 0.55),
                         QPointF(m.x() - tw_ * 0.40, top + tl), QPointF(m.x(), top + tl))
            path.cubicTo(QPointF(m.x() + tw_ * 0.40, top + tl),
                         QPointF(m.x() + tw_ * 0.56, top + tl * 0.55), QPointF(m.x() + tw_ * 0.5, top))
            path.closeSubpath()
            base = QColor(self.rig.tongue)
            grad = QLinearGradient(m.x() - tw_ * 0.5, top, m.x() + tw_ * 0.5, top)
            grad.setColorAt(0.0, base.darker(128))
            grad.setColorAt(0.35, base.lighter(108))
            grad.setColorAt(0.65, base)
            grad.setColorAt(1.0, base.darker(140))
            p.setBrush(QBrush(grad))
            p.drawPath(path)
            p.save()
            p.setClipPath(path)
            shade = QLinearGradient(0, top, 0, top + tl)          # ombra sotto il labbro
            shade.setColorAt(0.0, QColor(40, 10, 16, 190))
            shade.setColorAt(0.35, QColor(40, 10, 16, 0))
            p.setBrush(QBrush(shade))
            p.drawRect(QRectF(m.x() - tw_, top, tw_ * 2, tl))
            p.setBrush(QColor(120, 40, 60, 70))                   # solco centrale
            p.drawRoundedRect(QRectF(m.x() - tw_ * 0.035, top + tl * 0.12, tw_ * 0.07, tl * 0.62),
                              tw_ * 0.03, tw_ * 0.03)
            p.setBrush(QColor(255, 255, 255, 60))                 # riflesso umido
            p.drawEllipse(QRectF(m.x() - tw_ * 0.30, top + tl * 0.50, tw_ * 0.22, tl * 0.22))
            p.restore()

    def _displace(self) -> list[tuple[float, float]]:
        """Posizione di ogni vertice dopo la deformazione."""
        r = self.rig
        sw, hs = self.sw, self.hs
        yaw, pitch = self.yaw, self.pitch
        roll = math.radians(self.roll)
        jaw = self.jaw * (1.7 if r.open_mouth else 1.0)
        mid = r.neck[0]
        breath = math.sin(self.clock * 1.7)
        piv = self.uv(*r.neck)
        bl, br = self.uv(r.ear_l[2], r.ear_l[3]), self.uv(r.ear_r[2], r.ear_r[3])
        ear_l, ear_r = math.radians(self.ear[0]), math.radians(self.ear[1])
        out = []
        legs_on = bool(self._legs) and (any(abs(a) > 1e-3 for a in self.lift)
                                        or any(abs(a) > 1e-3 for a in self.swing))
        for (x, y), (u, v, wh, depth, we_l, we_r, wb, wj, wc, lw) in zip(self._src, self._weights):
            # zampe: il piede sale (le gambe si accorciano) e gira attorno all'attacco
            if legs_on:
                for n, w in enumerate(lw):
                    if w <= 0.004 or n > 1:
                        continue
                    pxv, pyv, ax, ay, _nx, _ny, ln, _wid, side = self._legs[n]
                    lf, sw = self.lift[n], self.swing[n]
                    if abs(lf) < 1e-3 and abs(sw) < 1e-3:
                        continue
                    x -= ax * lf * w * LEG_LIFT * ln
                    y -= ay * lf * w * LEG_LIFT * ln
                    a = side * (sw * LEG_SWING + lf * 0.12) * w
                    dx, dy = x - pxv, y - pyv
                    x, y = pxv + dx * math.cos(a) - dy * math.sin(a), pyv + dx * math.sin(a) + dy * math.cos(a)
            # orecchie (prima: ruotano attorno alla propria base)
            if we_l > 0.02 and ear_l:
                a = ear_l * we_l
                dx, dy = x - bl.x(), y - bl.y()
                x, y = bl.x() + dx * math.cos(a) - dy * math.sin(a), bl.y() + dx * math.sin(a) + dy * math.cos(a)
            if we_r > 0.02 and ear_r:
                a = ear_r * we_r
                dx, dy = x - br.x(), y - br.y()
                x, y = br.x() + dx * math.cos(a) - dy * math.sin(a), br.y() + dx * math.sin(a) + dy * math.cos(a)
            # parallasse: il muso (vicino) si sposta piu' del cranio (lontano)
            x += yaw * (0.060 * depth + 0.0168) * wh * hs
            y += pitch * (0.0605 * depth + 0.0158) * wh * hs
            y -= self.brow * 0.0171 * hs * wb
            y += jaw * 0.0263 * hs * wj
            # respiro
            x += (u - mid) * sw * 0.010 * breath * wc
            y -= breath * 0.0046 * hs * wh
            # inclinazione della testa attorno al collo
            if roll and wh > 0.0:
                a = roll * wh
                dx, dy = x - piv.x(), y - piv.y()
                x, y = piv.x() + dx * math.cos(a) - dy * math.sin(a), piv.y() + dx * math.sin(a) + dy * math.cos(a)
            out.append((x + self._m, y + self._m))
        return out

    def render(self, pose: Pose, size: float, warp: list | None = None, k: float = 0.0) -> QImage:
        """Il cane deformato su un buffer trasparente (grande quanto la texture + margine).

        `warp` = campo di spostamento verso un'altra vista, `k` quanto applicarlo (morph)."""
        self._prepare(size)
        work = self._work_texture(pose)
        tw, th = self.tw, self.th
        self._m = MARGIN
        if warp is not None and k > 1e-4:
            self._m = MARGIN + int(self._warp_reach(warp) * k) + 2
        m = self._m
        buf = QImage(tw + 2 * m, th + 2 * m, QImage.Format_ARGB32_Premultiplied)
        buf.fill(0)
        dst = self._displace()
        if warp is not None and k > 1e-4:
            dst = [(x + k * dx, y + k * dy) for (x, y), (dx, dy) in zip(dst, warp)]
        p = QPainter(buf)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setPen(Qt.NoPen)
        brush = QBrush(work)
        xs, ys = self._xs, self._ys
        nx, row = len(xs) - 1, len(xs)
        grow = 0.75
        for j in range(len(ys) - 1):
            y0, y1 = ys[j], ys[j + 1]
            ch = y1 - y0
            for i in range(nx):
                if not self._cells[j * nx + i]:
                    continue
                a = j * row + i
                d00, d10, d01, d11 = dst[a], dst[a + 1], dst[a + row], dst[a + row + 1]
                x0, x1 = xs[i], xs[i + 1]
                cw = x1 - x0
                # triangolo alto-sinistro
                m11, m12 = (d10[0] - d00[0]) / cw, (d10[1] - d00[1]) / cw
                m21, m22 = (d01[0] - d00[0]) / ch, (d01[1] - d00[1]) / ch
                brush.setTransform(QTransform(m11, m12, m21, m22,
                                              d00[0] - m11 * x0 - m21 * y0, d00[1] - m12 * x0 - m22 * y0))
                p.setBrush(brush)
                p.drawConvexPolygon(_grown((d00, d10, d01), grow))
                # triangolo basso-destro
                m11, m12 = (d11[0] - d01[0]) / cw, (d11[1] - d01[1]) / cw
                m21, m22 = (d11[0] - d10[0]) / ch, (d11[1] - d10[1]) / ch
                brush.setTransform(QTransform(m11, m12, m21, m22,
                                              d11[0] - m11 * x1 - m21 * y1, d11[1] - m12 * x1 - m22 * y1))
                p.setBrush(brush)
                p.drawConvexPolygon(_grown((d11, d01, d10), grow))
        p.end()
        return buf

    @staticmethod
    def _warp_reach(warp: list) -> float:
        return max((max(abs(dx), abs(dy)) for dx, dy in warp), default=0.0)

    def draw(self, painter: QPainter, pose: Pose, size: float, warp: list | None = None, k: float = 0.0) -> None:
        """Disegna con origine nel punto d'appoggio: (0,0) = centro, bordo inferiore."""
        buf = self.render(pose, size, warp, k)
        sw, sh = self.sw, self.sh
        osize = sw / 0.913 if self.rig.full else size      # accessori in proporzione alla larghezza
        hop = abs(math.sin(pose.leg_phase)) * size * 0.022 * pose.leg_swing
        painter.save()
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.setRenderHint(QPainter.Antialiasing, True)

        if pose.shadow > 0.01 and self.sink < 0.95:      # ombra di contatto sul bordo
            grad = QRadialGradient(0, 0, sw * 0.5)
            grad.setColorAt(0.0, QColor(0, 0, 0, int(70 * pose.shadow)))
            grad.setColorAt(1.0, QColor(0, 0, 0, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(grad))
            painter.drawEllipse(QRectF(-sw * 0.5, -size * 0.035, sw, size * 0.07))

        if self.outfit:
            from . import outfits

            outfits.draw_behind(painter, self.outfit, self, osize)

        painter.save()
        lift = sh * 0.5 * min(1.0, abs(pose.spin) / 90.0)
        painter.translate(0, -hop + pose.body_bob * 0.4 - lift + self.sink * sh * 1.02)
        painter.rotate(pose.spin + pose.body_tilt * 0.3)
        painter.translate(0, lift)
        painter.scale(1.0 / max(pose.squash, 0.2) ** 0.5, pose.squash)
        if pose.facing < 0:
            painter.scale(-1.0, 1.0)
        # buffer: lo sprite sta a (px+MARGIN, py+MARGIN); il suo centro-basso va nell'origine
        painter.drawImage(QPointF(-(self.px + sw / 2 + self._m),
                                  -(self.py + sh + self._m) + sh * (self.rig.feet - 1.0)), buf)
        painter.restore()

        if pose.prop or self.outfit:
            from . import outfits

            outfits.draw_front(painter, pose.prop, self.outfit, self, osize, 0.55 if self.rig.full else 1.0)
        self._paws(painter, pose, size)
        painter.restore()


    # ------------------------------------------------------------------ morph
    def _extent(self) -> tuple[float, float]:
        """Sinistra e destra della sagoma a meta' altezza (0..1), per ancorare il morph."""
        if self._ext is None:
            img = self.image
            lo, hi = 1.0, 0.0
            for yy in range(int(img.height() * 0.45), int(img.height() * 0.75), 6):
                for xx in range(0, img.width(), 4):
                    if img.pixelColor(xx, yy).alpha() > 60:
                        lo = min(lo, xx / img.width())
                        break
                for xx in range(img.width() - 1, -1, -4):
                    if img.pixelColor(xx, yy).alpha() > 60:
                        hi = max(hi, xx / img.width())
                        break
            self._ext = (lo, hi) if hi > lo else (0.1, 0.9)
        return self._ext

    def anchors(self, size: float) -> dict[str, tuple[float, float]]:
        """Parti del corpo riconoscibili, in coordinate di disegno (origine: punto d'appoggio).
        Due viste si "corrispondono" parte per parte: e' cio' che rende il morph credibile."""
        r = self.rig
        sw, sh = size * self.aspect, size

        def pt(u: float, v: float) -> tuple[float, float]:
            return (u - 0.5) * sw, (v - 1.0) * sh + sh * (r.feet - 1.0)

        out = {"head_top": pt(*r.head_top), "neck": pt(*r.neck), "nose": pt(*r.nose),
               "mouth": pt(*r.mouth), "ear_l": pt(*r.ear_l[:2]), "ear_r": pt(*r.ear_r[:2]),
               "foot": pt(0.5, 1.0)}
        eyes = sorted(r.eyes, key=lambda e: e.x)
        if len(eyes) >= 2:
            out["eye_l"], out["eye_r"] = pt(eyes[0].x, eyes[0].y), pt(eyes[-1].x, eyes[-1].y)
        if len(r.legs) >= 2:
            out["paw_l"], out["paw_r"] = pt(r.legs[0][2], r.legs[0][3]), pt(r.legs[-1][2], r.legs[-1][3])
        else:
            out["paw_l"], out["paw_r"] = pt(0.22, 1.0), pt(0.78, 1.0)
        lo, hi = self._extent()
        out["body_l"], out["body_r"] = pt(lo, 0.62), pt(hi, 0.62)
        out["belly"] = pt((lo + hi) / 2, 0.70)
        return out

    def field_to(self, other: "Skin", size: float, osize: float) -> list[tuple[float, float]]:
        """Per ogni vertice: di quanto va spostato per finire sulla vista `other` (interpolazione
        di Shepard sulle ancore corrispondenti). Calcolato una volta per coppia di viste."""
        key = (id(other), round(size), round(osize), self.outfit, other.outfit)
        cached = self._fields.get(key)
        if cached is not None:
            return cached
        self._prepare(size)
        a, b = self.anchors(size), other.anchors(osize)
        names = [n for n in a if n in b]
        pts = [(a[n][0], a[n][1], b[n][0] - a[n][0], b[n][1] - a[n][1]) for n in names]
        eps = (0.04 * size) ** 2
        off_x, off_y = self.px + self.sw / 2, self.py + self.sh - self.sh * (self.rig.feet - 1.0)
        out = []
        for x, y in self._src:
            qx, qy = x - off_x, y - off_y
            nx = ny = den = 0.0
            for ax, ay, dx, dy in pts:
                d2 = (qx - ax) ** 2 + (qy - ay) ** 2 + eps
                w = 1.0 / (d2 * math.sqrt(d2))          # 1 / distanza^3: le ancore vicine comandano
                nx += w * dx
                ny += w * dy
                den += w
            out.append((nx / den, ny / den))
        if len(self._fields) > 8:
            self._fields.clear()
        self._fields[key] = out
        return out

    def _paws(self, painter: QPainter, pose: Pose, size: float) -> None:
        """Zampe vere appoggiate al bordo: salgono da sotto, battono, si alzano."""
        if self.paw is None or self.rig.full or pose.paws <= 0.02:
            return
        ph = size * 0.38
        pw = ph * self.paw.width() / self.paw.height()
        spread = self.sw * 0.21
        for side, lift in ((-1, pose.paw_l), (1, pose.paw_r)):
            reach = pose.paw_reach if side > 0 else 0.0
            x = side * spread * (1.0 - 0.55 * reach)
            y = (1.0 - pose.paws) * ph * 1.05 - lift * size * 0.045 - reach * size * 0.20
            painter.save()
            painter.translate(x, y + ph * 0.10)
            shade = QRadialGradient(pw * 0.10, -ph * 0.42, pw * 0.85)
            shade.setColorAt(0.0, QColor(40, 22, 8, 70))
            shade.setColorAt(1.0, QColor(40, 22, 8, 0))
            painter.setPen(Qt.NoPen)
            painter.setBrush(QBrush(shade))
            painter.drawEllipse(QRectF(-pw * 0.75, -ph * 0.95, pw * 1.7, ph * 1.05))
            painter.rotate(-side * (4.0 + 16.0 * reach))
            if side < 0:
                painter.scale(-1.0, 1.0)
            painter.drawImage(QRectF(-pw / 2, -ph, pw, ph), self.paw)
            painter.restore()


# Se una vista manca si ripiega su quella piu' vicina (l'ultima scelta e' sempre "casa").
FALLBACK = {
    "serio": ("seduto",),
    "seduto": ("serio",),
    "sdraiato": ("seduto", "serio"),
    "dietro": (),
    "busto": (),
}


class SkinSet:
    """Tutte le viste di un animale (primo piano, seduto, serio, di spalle...).

    La posa chiede una vista (`pose.view`); qui si sceglie quella disponibile piu'
    vicina e si passa dall'una all'altra senza scatti. Verso l'esterno si comporta
    come una pelle sola: advance(), draw(), bounds().
    """

    def __init__(self, name: str, views: dict[str, Skin], home: str = "", species: str = "cane") -> None:
        if not views:
            raise ValueError("pelle senza viste")
        self.name = name
        self.views = views
        self.species = species
        self.default_home = home if home in views else next(iter(views))
        self.home = self.default_home
        self.cur = self.home
        self.prev: str | None = None
        self.mix = 1.0
        self.morph = False          # il passaggio in corso e' un morph (figura intera <-> figura intera)
        self.away = 0.0
        self.outfit = ""

    # ------------------------------------------------------------- caricamento
    @classmethod
    def load(cls, folder: str | Path) -> "SkinSet":
        folder = Path(folder)
        data = json.loads((folder / "rig.json").read_text(encoding="utf-8"))
        name = data.get("name", folder.name)
        paw = None
        if data.get("paw") and (folder / data["paw"]).exists():
            paw = QImage(str(folder / data["paw"]))
        specs: dict[str, dict] = {}
        if data.get("sprite") or "views" not in data:
            specs["busto"] = data
        specs.update(data.get("views", {}))
        views: dict[str, Skin] = {}
        for key, spec in specs.items():
            img = QImage(str(folder / spec.get("sprite", "sprite.png")))
            if img.isNull():
                if key == "busto" and "views" not in data:
                    raise FileNotFoundError(f"sprite non caricato: {folder}")
                continue
            rig = Rig.from_dict(spec)
            rig.tongue = spec.get("tongue", data.get("tongue", rig.tongue))
            views[key] = Skin(f"{name}/{key}", img, rig, None if rig.full else paw)
        if not views:
            raise FileNotFoundError(f"sprite non caricato: {folder}")
        return cls(name, views, data.get("home", ""), data.get("species", "cane"))

    # ---------------------------------------------------------------- vista
    @property
    def view(self) -> Skin:
        return self.views[self.cur]

    @property
    def full(self) -> bool:
        """La vista di casa e' una figura intera?"""
        return self.views[self.home].rig.full

    @property
    def legged(self) -> bool:
        """La vista di casa ha le zampe animabili (altrimenti le azioni da zampe usano il primo piano)."""
        return bool(self.views[self.home].rig.legs)

    def has(self, view: str) -> bool:
        return view in self.views

    def framings(self) -> list[str]:
        """Inquadrature tra cui l'utente puo' scegliere."""
        out = []
        if any(v.rig.full and v.rig.face for v in self.views.values()):
            out.append("intera")
        if any(not v.rig.full for v in self.views.values()):
            out.append("busto")
        return out

    def set_framing(self, framing: str) -> None:
        """'intera' = figura intera, 'busto' = primo piano affacciato dal bordo."""
        want_full = framing != "busto"
        if self.views[self.default_home].rig.full == want_full:
            self.home = self.default_home
            return
        for key, v in self.views.items():
            if v.rig.full == want_full and v.rig.face:
                self.home = key
                return

    def resolve(self, view: str) -> str:
        if not view:
            return self.home
        if view in self.views:
            return view
        for alt in FALLBACK.get(view, ()):
            if alt in self.views:
                return alt
        return self.home

    # per il codice che tratta la pelle come una sola
    @property
    def image(self) -> QImage:
        return self.view.image

    @property
    def rig(self) -> Rig:
        return self.view.rig

    @property
    def aspect(self) -> float:
        return self.view.aspect

    @property
    def sink(self) -> float:
        return self.view.sink

    def set_outfit(self, outfit: str) -> None:
        self.outfit = outfit
        for v in self.views.values():
            v.set_outfit(outfit)

    def _scale(self) -> float:
        return 1.0 - AWAY_SHRINK * self.away

    def height(self, size: float) -> float:
        return size * self.view.rig.height * self._scale()

    def rect(self, size: float) -> QRectF:
        """Parte visibile del cane attorno al punto d'appoggio (per click e fumetti)."""
        v = self.view
        h = self.height(size)
        w = h * v.aspect
        top = -h * max(0.12, 1.0 - v.sink)
        return QRectF(-w / 2, top, w, -top)

    def bounds(self, size: float) -> QRectF:
        r = self.view.bounds(size * self.view.rig.height)
        if self.prev and self.mix < 1.0:
            r = r.united(self.views[self.prev].bounds(size * self.views[self.prev].rig.height))
            if self.morph:
                r = r.adjusted(-size * 0.25, -size * 0.1, size * 0.25, size * 0.1)
        return r

    def point(self, what: str, size: float) -> tuple[float, float]:
        """Dove sono bocca / testa rispetto al punto d'appoggio (palla, zzz, cuori)."""
        v = self.view
        r = v.rig
        u, t = {"mouth": r.mouth, "nose": r.nose}.get(what, r.head_top) if r.face else r.head_top
        x, y = v.point(u, t, size * r.height)
        k = self._scale()
        return x * k, y * k

    @property
    def visible(self) -> bool:
        return self.away < 0.96

    # --------------------------------------------------------------- dinamica
    def advance(self, dt: float, pose: Pose, look: tuple[float, float] = (0.0, 0.0)) -> None:
        want = self.resolve(pose.view)
        if want != self.cur:
            old, new = self.views[self.cur], self.views[want]
            new.yaw, new.pitch, new.roll = old.yaw, old.pitch, old.roll
            new.brow, new.jaw, new.clock = old.brow, old.jaw, old.clock
            new.lift, new.swing = list(old.lift), list(old.swing)
            self.morph = old.rig.full and new.rig.full
            new.sink = old.sink if self.morph else (0.0 if new.rig.full else 1.0)   # primo piano: sale da sotto il bordo
            self.prev, self.cur, self.mix = self.cur, want, 0.0
        self.away += (max(0.0, min(1.0, pose.away)) - self.away) * min(1.0, dt * 14.0)
        if self.prev is not None:
            a, b = self.views[self.prev], self.views[self.cur]
            self.mix = min(1.0, self.mix + dt / (MORPH_TIME if self.morph else 0.42))
            if self.mix >= 1.0:
                self.prev = None
            else:
                gone = pose if a.rig.full else _with(pose, sink=1.0)   # il primo piano se ne va scendendo
                a.advance(dt, gone, look)
        self.view.advance(dt, pose, look)

    # ---------------------------------------------------------------- disegno
    def draw(self, painter: QPainter, pose: Pose, size: float) -> None:
        if not self.visible:
            return
        k = self._scale()
        fade = 1.0 - _smooth(0.55, 1.0, self.away)
        painter.save()
        painter.scale(k, k)
        new = self.view
        if self.prev is not None and self.mix < 1.0 and self.morph:
            # morph: ogni parte del vecchio scivola sulla parte corrispondente del nuovo (e viceversa);
            # i colori si fondono solo a cose gia' allineate, quindi non sembra una dissolvenza
            old = self.views[self.prev]
            e = _smooth(0.0, 1.0, self.mix)
            so, sn = size * old.rig.height, size * new.rig.height
            a_new = _smooth(0.12, 0.58, e)
            a_old = 1.0 - _smooth(0.60, 0.92, e)
            painter.setOpacity(fade * a_old)
            old.draw(painter, pose, so, old.field_to(new, so, sn), e)
            painter.setOpacity(fade * a_new)
            new.draw(painter, pose, sn, new.field_to(old, sn, so), 1.0 - e)
            painter.restore()
            return
        if self.prev is not None and self.mix < 1.0:
            old = self.views[self.prev]
            # il nuovo compare sopra il vecchio, poi il vecchio svanisce: mai "trasparente"
            a_old = 1.0 - _smooth(0.45, 1.0, self.mix)
            a_new = _smooth(0.0, 0.6, self.mix) if new.rig.full else 1.0
            painter.setOpacity(fade * a_old)
            old.draw(painter, pose, size * old.rig.height)
            painter.setOpacity(fade * a_new)
        else:
            painter.setOpacity(fade)
        new.draw(painter, pose, size * new.rig.height)
        painter.restore()


def _with(pose: Pose, **changes) -> Pose:
    from dataclasses import replace

    return replace(pose, **changes)


def _grown(tri, amount: float) -> QPolygonF:
    """Triangolo allargato di poco attorno al baricentro: niente fessure tra le celle."""
    cx = (tri[0][0] + tri[1][0] + tri[2][0]) / 3.0
    cy = (tri[0][1] + tri[1][1] + tri[2][1]) / 3.0
    pts = []
    for x, y in tri:
        dx, dy = x - cx, y - cy
        ln = math.hypot(dx, dy) or 1.0
        pts.append(QPointF(x + dx / ln * amount, y + dy / ln * amount))
    return QPolygonF(pts)
