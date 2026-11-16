"""Finestra trasparente a tutto schermo: ci vive dentro il cane."""

from __future__ import annotations

import math
import random

from PySide6.QtCore import QPoint, QRect, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QCursor, QPainter, QRegion
from PySide6.QtWidgets import QWidget

from . import render
from .breeds import get as get_breed
from .pet import Pet, Stats, World
from .props import Ball, Bowl, Particles
from .skin import Skin

FPS = 30


class PetOverlay(QWidget):
    """Overlay click-through: riceve i click solo dove c'e' il cane o la palla."""

    context_requested = Signal(QPoint)

    def __init__(self, screen, size: int, speed: float, stats: Stats, follow: bool = False,
                 skin: Skin | None = None, breed: str = "golden") -> None:
        super().__init__(None)
        self.setWindowFlags(
            Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.Tool
            | Qt.NoDropShadowWindowHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WA_AlwaysStackOnTop, True)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setMouseTracking(True)

        self._screen = screen
        self.size_px = float(size)
        self.pet = Pet(stats=stats, speed=speed, bust=skin is not None)
        self.particles = Particles()
        self.ball: Ball | None = None
        self.bowl: Bowl | None = None
        self.bubble: tuple[str, float] | None = None
        self.follow_cursor = follow
        self.skin = skin
        self.outfit = ""
        self.breed = get_breed(breed)
        self.dragging = False
        self._drag_dy = 0.0
        self._mask_rects: list[QRect] = []
        self._last_region = QRegion()

        self.apply_geometry()
        self.pet.x = self.width() * 0.5
        self.pet.y = self.ground()

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(int(1000 / FPS))

    # ------------------------------------------------------------- geometria
    def apply_geometry(self) -> None:
        geo = self._screen.availableGeometry()
        self.setGeometry(geo)

    def ground(self) -> float:
        return float(self.height()) - 2.0

    def dog_rect(self) -> QRectF:
        """Rettangolo cliccabile del cane (per la pelle: solo la parte fuori dal bordo)."""
        h = self.size_px
        if self.skin:
            w = h * self.skin.aspect
            top = self.pet.y - h * max(0.12, 1.0 - self.skin.sink)
            return QRectF(self.pet.x - w / 2, top, w, self.pet.y - top)
        return QRectF(self.pet.x - h / 2, self.pet.y - h, h, h)

    def paint_rect(self) -> QRectF:
        """Tutta l'area che il cane puo' sporcare (cappelli, sci, zampe)."""
        if not self.skin:
            return self.dog_rect().adjusted(-4, -4, 4, 6)
        r = self.skin.bounds(self.size_px).translated(self.pet.x, self.pet.y)
        if self.skin.outfit == "ski":
            r.setRight(r.right() + self.size_px * 0.5)
        if self.skin.outfit == "summer":
            r.adjust(-self.size_px * 0.12, 0, self.size_px * 0.12, 0)
        return r

    def set_skin(self, skin: Skin | None) -> None:
        self.skin = skin
        self.pet.bust = skin is not None
        self.pet.y = self.ground()
        self.pet.set_state("idle", 1.0)

    def set_outfit(self, outfit: str) -> None:
        self.outfit = outfit
        if self.skin:
            self.skin.set_outfit(outfit)

    def set_breed(self, key: str) -> None:
        self.breed = get_breed(key)

    def world(self) -> World:
        cursor = self.mapFromGlobal(QCursor.pos())
        return World(
            left=0.0,
            right=float(self.width()),
            ground=self.ground(),
            cursor_x=float(cursor.x()),
            cursor_y=float(cursor.y()),
            ball=self.ball if (self.ball and self.ball.resting and not self.pet.carrying_ball) else None,
            bowl_x=self.bowl.x if self.bowl else self.width() * 0.8,
            scale=self.size_px / 100.0,
        )

    # ----------------------------------------------------------------- azioni
    def command(self, action: str) -> None:
        """Comandi dal menu / tray."""
        if action == "ball":
            self.throw_ball()
        elif action == "feed":
            self.put_bowl()
        elif action == "follow":
            self.follow_cursor = not self.follow_cursor
            if self.follow_cursor:
                self.pet.set_state("chase", 8.0)
        elif action == "wake":
            self.pet.set_state("idle", 0.6)
        else:
            self.pet.set_state(action, None)

    def throw_ball(self) -> None:
        direction = -self.pet.facing if random.random() < 0.5 else self.pet.facing
        self.ball = Ball(
            x=self.pet.x + 20 * self.pet.facing,
            y=self.ground() - self.size_px * 0.8,
            vx=direction * random.uniform(220, 420),
            vy=-random.uniform(200, 420),
            radius=max(7.0, self.size_px * 0.09),
        )
        self.pet.carrying_ball = False
        self.pet.set_state("fetch", 25.0)

    def put_bowl(self) -> None:
        x = min(max(self.size_px, self.pet.x + random.choice((-1, 1)) * self.size_px * 2.2), self.width() - self.size_px)
        self.bowl = Bowl(x=x, y=self.ground(), width=max(26.0, self.size_px * 0.3))
        self.pet.set_state("eat", 5.0)

    def set_size(self, size: int) -> None:
        self.size_px = float(size)

    def set_speed(self, speed: float) -> None:
        self.pet.speed = speed

    # ------------------------------------------------------------------ loop
    def _tick(self) -> None:
        dt = 1.0 / FPS
        world = self.world()
        if self.dragging:
            cursor = self.mapFromGlobal(QCursor.pos())
            self.pet.x = float(cursor.x())
            # la pelle fotografica e' un busto: scorre lungo il bordo, non si solleva
            self.pet.y = self.ground() if self.skin else float(cursor.y()) + self._drag_dy
        elif self.follow_cursor and self.pet.state in ("idle", "walk", "sit"):
            self.pet.set_state("chase", 6.0)

        self.pet.update(dt, world)
        if self.skin:
            s = self.size_px
            near = abs(world.cursor_x - self.pet.x) < s * 5 and world.cursor_y > self.pet.y - s * 4
            look = (0.0, 0.0)
            if near and self.pet.state in ("idle", "sit", "walk", "tilt", "boop", "squint"):
                look = (max(-1.0, min(1.0, (world.cursor_x - self.pet.x) / (s * 2.2))),
                        max(-1.0, min(1.0, (world.cursor_y - (self.pet.y - s * 0.62)) / (s * 2.0))))
                if self.pet.pose.facing < 0:
                    look = (-look[0], look[1])
            self.skin.advance(dt, self.pet.pose, look)
        if self.ball:
            self.ball.update(dt, 0.0, float(self.width()), self.ground())
            if self.pet.carrying_ball:
                self.ball.x = self.pet.x - self.size_px * 0.42 * self.pet.facing * -1
                self.ball.y = self.pet.y - self.size_px * 0.52
                if self.skin:
                    self.ball.x = self.pet.x + self.size_px * 0.10 * self.pet.facing
                    self.ball.y = self.pet.y - self.size_px * 0.30
                self.ball.resting = False
        self.particles.update(dt)
        self._consume_effects()
        if self.bubble:
            text, life = self.bubble
            life -= dt
            self.bubble = (text, life) if life > 0 else None
        self.update()
        self._update_mask()

    def _consume_effects(self) -> None:
        for effect in self.pet.effects:
            if effect.kind == "bubble":
                self.bubble = (effect.text, 1.8)
            elif effect.kind == "drop_ball":
                if self.ball:
                    self.ball.resting = True
                    self.ball.y = self.ground()
            else:
                self.particles.spawn(effect.kind, effect.x, effect.y, effect.text)
        self.pet.effects.clear()

    # --------------------------------------------------------------- disegno
    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        scale = self.size_px / 100.0
        rects: list[QRect] = []

        if self.bowl:
            render.draw_bowl(painter, self.bowl.x, self.bowl.y, self.bowl.width)
            rects.append(QRect(int(self.bowl.x - self.bowl.width), int(self.bowl.y - self.bowl.width),
                               int(self.bowl.width * 2), int(self.bowl.width * 1.5)))
        if self.ball:
            render.draw_ball(painter, self.ball.x, self.ball.y, self.ball.radius)
            r = self.ball.radius
            rects.append(QRect(int(self.ball.x - r * 2), int(self.ball.y - r * 3), int(r * 4), int(r * 5)))

        dog = self.dog_rect()
        painter.save()
        if self.skin:
            painter.translate(self.pet.x, self.pet.y)
            self.skin.draw(painter, self.pet.pose, self.size_px)
        else:
            painter.translate(dog.left(), dog.top())
            render.draw_dog(painter, self.pet.pose, self.size_px, self.breed)
        painter.restore()
        rects.append(self.paint_rect().toRect())

        for p in self.particles.items:
            render.draw_particle(painter, p.kind, p.x, p.y, p.alpha, max(10.0, self.size_px * 0.22),
                                 p.text, p.spin)
            rects.append(QRect(int(p.x - 16), int(p.y - 20), 34, 36))

        if self.bubble:
            text, life = self.bubble
            rect = render.draw_bubble(painter, self.pet.x, dog.top() - 6, text, min(1.0, life / 0.4), scale)
            rects.append(rect.toRect())
        painter.end()
        self._mask_rects = rects

    def _update_mask(self) -> None:
        region = QRegion()
        for r in self._mask_rects:
            region = region.united(r.intersected(self.rect()))
        if region.isEmpty():
            region = QRegion(self.dog_rect().toRect())
        if region != self._last_region:
            self.setMask(region)
            self._last_region = region

    # ------------------------------------------------------------------ input
    def _hits_dog(self, pos) -> bool:
        return self.dog_rect().adjusted(-6, -6, 6, 6).contains(pos)

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if event.button() == Qt.LeftButton and self._hits_dog(pos):
            self.dragging = True
            self._drag_dy = self.pet.y - pos.y()
            self.pet.set_state("dragged", 999.0)
            event.accept()
            return
        event.ignore()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self.dragging:
            self.dragging = False
            self.pet.vy = 0.0
            if self.skin:
                self.pet.set_state("idle", 1.0)
            else:
                self.pet.on_ground = False
                self.pet.set_state("fall", 5.0)
            event.accept()

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.LeftButton and self._hits_dog(event.position()):
            self.dragging = False
            self.pet.set_state("pet", 2.4)
            event.accept()

    def contextMenuEvent(self, event) -> None:  # noqa: N802
        self.context_requested.emit(event.globalPos())
        event.accept()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if self._hits_dog(event.position()):
            step = 10 if event.angleDelta().y() > 0 else -10
            self.size_px = max(60.0, min(400.0, self.size_px + step))
            event.accept()
