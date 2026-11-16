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

PAD_TOP = 0.36      # spazio sopra la testa (cappelli), frazione dell'altezza
PAD_SIDE = 0.14     # spazio ai lati, frazione della larghezza
NX, NY = 14, 18     # celle della griglia
MARGIN = 10         # px attorno al buffer per gli spostamenti


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
        self.clock = 0.0
        self._prev = (0.0, 0.0)
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
        folder = Path(folder)
        data = json.loads((folder / "rig.json").read_text(encoding="utf-8"))
        img = QImage(str(folder / data.get("sprite", "sprite.png")))
        if img.isNull():
            raise FileNotFoundError(f"sprite non caricato: {folder}")
        rig = Rig(eyes=[Eye(**e) for e in data.get("eyes", [])])
        for key in ("nose", "mouth", "head_top", "neck", "ear_l", "ear_r"):
            if key in data:
                setattr(rig, key, tuple(data[key]))
        rig.feet = float(data.get("feet", rig.feet))
        rig.tongue = data.get("tongue", rig.tongue)
        paw = None
        if data.get("paw") and (folder / data["paw"]).exists():
            paw = QImage(str(folder / data["paw"]))
        return cls(data.get("name", folder.name), img, rig, paw)

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
        self.px, self.py = self.sw * PAD_SIDE, self.sh * PAD_TOP
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

        # pesi per vertice
        r = self.rig
        self._weights = []
        self._src = []
        for j in range(NY + 1):
            for i in range(NX + 1):
                x, y = i / NX * tw, j / NY * th
                u, v = (x - self.px) / self.sw, (y - self.py) / self.sh
                wh = 1.0 - _smooth(0.66, 0.92, v)
                depth = (0.80 * _gauss(u, v, r.nose[0], r.nose[1], 0.24, 0.22)
                         + 0.30 * _gauss(u, v, 0.55, 0.34, 0.50, 0.46))
                we_l = _gauss(u, v, r.ear_l[0], r.ear_l[1], 0.10, 0.22)
                we_r = _gauss(u, v, r.ear_r[0], r.ear_r[1], 0.09, 0.18)
                wb = 0.0
                for eye in r.eyes:
                    wb = max(wb, _gauss(u, v, eye.x, eye.y - 0.065, 0.11, 0.05))
                wj = _gauss(u, v, r.mouth[0], r.mouth[1] + 0.055, 0.17, 0.065)
                wc = _smooth(0.72, 1.0, v)
                self._src.append((x, y))
                self._weights.append((u, v, wh, depth, we_l, we_r, wb, wj, wc))

        # celle completamente vuote: non si disegnano
        self._cells = []
        cw, ch = tw / NX, th / NY
        for j in range(NY):
            for i in range(NX):
                hit = False
                for fy in (0.1, 0.5, 0.9):
                    for fx in (0.1, 0.5, 0.9):
                        xx = min(tw - 1, int((i + fx) * cw))
                        yy = min(th - 1, int((j + fy) * ch))
                        if static.pixelColor(xx, yy).alpha() > 0:
                            hit = True
                            break
                    if hit:
                        break
                self._cells.append(hit)

    def uv(self, u: float, v: float) -> QPointF:
        """Da coordinate normalizzate dello sprite a pixel della texture."""
        return QPointF(self.px + u * self.sw, self.py + v * self.sh)

    def bounds(self, size: float) -> QRectF:
        """Ingombro attorno al punto d'appoggio (centro in basso), per la maschera."""
        w = size * self.aspect
        return QRectF(-w * (0.5 + PAD_SIDE) - MARGIN, -size * (1 + PAD_TOP) - MARGIN,
                      w * (1 + 2 * PAD_SIDE) + 2 * MARGIN, size * (1 + PAD_TOP) + 2 * MARGIN + size * 0.12)

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
        if closed <= 0.02 and pose.tongue <= 0.02 and self.jaw <= 0.03:
            return self._static
        work = self._static.copy()
        p = QPainter(work)
        p.setRenderHint(QPainter.Antialiasing, True)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        if self.jaw > 0.03 or pose.tongue > 0.02:
            self._mouth(p, pose)
        if closed > 0.02 and self.outfit not in ("ski",):
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
        w, h = self.sw, self.sh
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
        sw, sh = self.sw, self.sh
        yaw, pitch = self.yaw, self.pitch
        roll = math.radians(self.roll)
        breath = math.sin(self.clock * 1.7)
        piv = self.uv(*r.neck)
        bl, br = self.uv(r.ear_l[2], r.ear_l[3]), self.uv(r.ear_r[2], r.ear_r[3])
        ear_l, ear_r = math.radians(self.ear[0]), math.radians(self.ear[1])
        out = []
        for (x, y), (u, v, wh, depth, we_l, we_r, wb, wj, wc) in zip(self._src, self._weights):
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
            x += yaw * (0.050 * depth + 0.014) * wh * sw
            y += pitch * (0.046 * depth + 0.012) * wh * sh
            y -= self.brow * 0.013 * sh * wb
            y += self.jaw * 0.020 * sh * wj
            # respiro
            x += (u - 0.5) * sw * 0.010 * breath * wc
            y -= breath * 0.0035 * sh * wh
            # inclinazione della testa attorno al collo
            if roll and wh > 0.0:
                a = roll * wh
                dx, dy = x - piv.x(), y - piv.y()
                x, y = piv.x() + dx * math.cos(a) - dy * math.sin(a), piv.y() + dx * math.sin(a) + dy * math.cos(a)
            out.append((x + MARGIN, y + MARGIN))
        return out

    def render(self, pose: Pose, size: float) -> QImage:
        """Il cane deformato su un buffer trasparente (grande quanto la texture + margine)."""
        self._prepare(size)
        work = self._work_texture(pose)
        tw, th = self.tw, self.th
        buf = QImage(tw + 2 * MARGIN, th + 2 * MARGIN, QImage.Format_ARGB32_Premultiplied)
        buf.fill(0)
        dst = self._displace()
        p = QPainter(buf)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.setPen(Qt.NoPen)
        brush = QBrush(work)
        cw, ch = tw / NX, th / NY
        row = NX + 1
        grow = 0.75
        for j in range(NY):
            for i in range(NX):
                if not self._cells[j * NX + i]:
                    continue
                a = j * row + i
                d00, d10, d01, d11 = dst[a], dst[a + 1], dst[a + row], dst[a + row + 1]
                x0, y0 = i * cw, j * ch
                # triangolo alto-sinistro
                m11, m12 = (d10[0] - d00[0]) / cw, (d10[1] - d00[1]) / cw
                m21, m22 = (d01[0] - d00[0]) / ch, (d01[1] - d00[1]) / ch
                brush.setTransform(QTransform(m11, m12, m21, m22,
                                              d00[0] - m11 * x0 - m21 * y0, d00[1] - m12 * x0 - m22 * y0))
                p.setBrush(brush)
                p.drawConvexPolygon(_grown((d00, d10, d01), grow))
                # triangolo basso-destro
                x1, y1 = x0 + cw, y0 + ch
                m11, m12 = (d11[0] - d01[0]) / cw, (d11[1] - d01[1]) / cw
                m21, m22 = (d11[0] - d10[0]) / ch, (d11[1] - d10[1]) / ch
                brush.setTransform(QTransform(m11, m12, m21, m22,
                                              d11[0] - m11 * x1 - m21 * y1, d11[1] - m12 * x1 - m22 * y1))
                p.setBrush(brush)
                p.drawConvexPolygon(_grown((d11, d01, d10), grow))
        p.end()
        return buf

    def draw(self, painter: QPainter, pose: Pose, size: float) -> None:
        """Disegna con origine nel punto d'appoggio: (0,0) = centro, bordo inferiore."""
        buf = self.render(pose, size)
        sw, sh = self.sw, self.sh
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

            outfits.draw_behind(painter, self.outfit, self, size)

        painter.save()
        lift = sh * 0.5 * min(1.0, abs(pose.spin) / 90.0)
        painter.translate(0, -hop + pose.body_bob * 0.4 - lift + self.sink * sh * 1.02)
        painter.rotate(pose.spin + pose.body_tilt * 0.3)
        painter.translate(0, lift)
        painter.scale(1.0 / max(pose.squash, 0.2) ** 0.5, pose.squash)
        if pose.facing < 0:
            painter.scale(-1.0, 1.0)
        # buffer: lo sprite sta a (px+MARGIN, py+MARGIN); il suo centro-basso va nell'origine
        painter.drawImage(QPointF(-(self.px + sw / 2 + MARGIN),
                                  -(self.py + sh + MARGIN) + sh * (self.rig.feet - 1.0)), buf)
        painter.restore()

        if pose.prop or self.outfit:
            from . import outfits

            outfits.draw_front(painter, pose.prop, self.outfit, self, size)
        self._paws(painter, pose, size)
        painter.restore()

    def _paws(self, painter: QPainter, pose: Pose, size: float) -> None:
        """Zampe vere appoggiate al bordo: salgono da sotto, battono, si alzano."""
        if self.paw is None or pose.paws <= 0.02:
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
