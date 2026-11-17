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
from .props import DEFAULT_TTL, Ball, Bowl, Item, Particles, fade
from .skin import SkinSet

MAX_ITEMS = 8             # biscotti + ricordini a terra nello stesso momento

FPS = 30


class PetOverlay(QWidget):
    """Overlay click-through: riceve i click solo dove c'e' il cane o la palla."""

    context_requested = Signal(QPoint)

    def __init__(self, screen, size: int, speed: float, stats: Stats, follow: bool = False,
                 skin: SkinSet | None = None, breed: str = "golden", props_ttl: float = DEFAULT_TTL) -> None:
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
        self.pet = self._make_pet(stats, speed, skin)
        self.particles = Particles()
        self.ball: Ball | None = None
        self.bowl: Bowl | None = None
        self.items: list[Item] = []           # biscotti e ricordini
        self.props_ttl = float(props_ttl)     # dopo quanti secondi spariscono gli oggetti a terra
        self._clock = 0.0
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

    @staticmethod
    def _make_pet(stats: Stats, speed: float, skin: SkinSet | None) -> Pet:
        if skin is None:
            return Pet(stats=stats, speed=speed)
        return Pet(stats=stats, speed=speed, bust=True, full=skin.full,
                   views=tuple(skin.views), species=skin.species, legs=skin.full and skin.legged)

    def dog_rect(self) -> QRectF:
        """Rettangolo cliccabile del cane (per la pelle: solo la parte visibile)."""
        h = self.size_px
        if self.skin:
            return self.skin.rect(h).translated(self.pet.x, self.pet.y)
        return QRectF(self.pet.x - h / 2, self.pet.y - h, h, h)

    def paint_rect(self) -> QRectF:
        """Tutta l'area che il cane puo' sporcare (cappelli, sci, zampe)."""
        if not self.skin:
            return self.dog_rect().adjusted(-4, -4, 4, 6)
        if not self.skin.visible:
            return QRectF(self.pet.x, self.pet.y - 2, 1, 1)      # e' via: niente da cliccare
        r = self.skin.bounds(self.size_px).translated(self.pet.x, self.pet.y)
        if self.skin.outfit == "ski":
            r.setRight(r.right() + self.size_px * 0.5)
        if self.skin.outfit == "summer":
            r.adjust(-self.size_px * 0.12, 0, self.size_px * 0.12, 0)
        return r

    def set_skin(self, skin: SkinSet | None) -> None:
        self.skin = skin
        self._sync_pet()

    def set_framing(self, framing: str) -> None:
        """'intera' o 'busto' (primo piano affacciato dal bordo)."""
        if self.skin:
            self.skin.set_framing(framing)
            self._sync_pet()

    def _sync_pet(self) -> None:
        skin, pet = self.skin, self.pet
        pet.bust = skin is not None
        pet.full = bool(skin and skin.full)
        pet.legs = bool(skin and skin.full and skin.legged)
        pet.views = set(skin.views) if skin else set()
        pet.species = skin.species if skin else "cane"
        pet.carrying_ball = False
        pet.y = self.ground()
        pet.set_state("idle", 1.0)

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
            ball=self.ball,
            bowl_x=self.bowl.x if self.bowl else self.width() * 0.8,
            has_bowl=bool(self.bowl and self.bowl.full > 0.05),
            treat=min((i for i in self.items if i.kind == "treat" and i.resting),
                      key=lambda i: abs(i.x - self.pet.x), default=None),
            scale=self.size_px / 100.0,
        )

    # ----------------------------------------------------------------- azioni
    def command(self, action: str) -> None:
        """Comandi dal menu / tray."""
        if action == "ball":
            self.throw_ball()
        elif action == "feed":
            self.put_bowl()
        elif action == "treat":
            self.throw_treat()
        elif action == "clean":
            self.clean()
        elif action == "follow":
            self.follow_cursor = not self.follow_cursor
            if self.follow_cursor:
                self.pet.set_state("chase", 8.0)
        elif action == "wake":
            self.pet.set_state("idle", 0.6)
        else:
            pet = self.pet
            # stanco morto? A volte risponde che non ne ha voglia
            if (self.skin and action not in ("nope", "sleep", "leave", "poop", "sit")
                    and pet.stats.energia < 30 and random.random() < 0.35):
                action = "nope"
            pet.set_state(action, None)

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
        reach = 0.95 if self.pet.full else 2.2          # la figura intera non cammina: ciotola vicina
        x = min(max(self.size_px, self.pet.x + random.choice((-1, 1)) * self.size_px * reach),
                self.width() - self.size_px)
        self.bowl = Bowl(x=x, y=self.ground(), width=max(26.0, self.size_px * 0.3))
        self.pet.set_state("eat", 5.0)

    def throw_treat(self) -> None:
        """Un biscotto cade vicino al cane: appena tocca terra va a mangiarlo."""
        side = random.choice((-1, 1))
        x = self.pet.x + side * self.size_px * random.uniform(0.75, 1.15)
        x = min(max(self.size_px * 0.3, x), self.width() - self.size_px * 0.3)
        self._add_item(Item("treat", x - side * self.size_px * 0.3, self.ground() - self.size_px * 1.6,
                            vx=side * self.size_px * 0.5, vy=-120.0, size=max(13.0, self.size_px * 0.16)))
        if self.pet.state not in ("dragged", "leave", "poop", "sleep"):
            self.pet.set_state("treat")

    def _add_item(self, item: Item) -> None:
        self.items.append(item)
        while len(self.items) > MAX_ITEMS:
            self.items.pop(0)

    def clean(self) -> None:
        """Raccoglie tutto quello che c'e' a terra."""
        for item in self.items:
            self.particles.spawn("star", item.x, item.y - item.size * 0.5)
        self.items.clear()
        if self.ball and self.ball.resting and not self.pet.carrying_ball:
            self.ball = None
        if self.bowl and self.pet.state != "eat":
            self.bowl = None

    def _expire(self, dt: float) -> None:
        """Palla, ciotola, biscotti e ricordini spariscono da soli dopo `props_ttl` secondi."""
        ttl = self.props_ttl
        w, g = float(self.width()), self.ground()
        for item in self.items:
            item.update(dt, 0.0, w, g)
        if ttl > 0:
            self.items = [i for i in self.items if i.age < ttl]
            if self.ball and self.ball.age >= ttl and not self.pet.carrying_ball:
                self.ball = None
            if self.bowl:
                self.bowl.age += dt
                if self.bowl.age >= ttl and self.pet.state != "eat":
                    self.bowl = None

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

        self._clock += dt
        self.pet.update(dt, world)
        if self.skin:
            s = self.size_px
            eye_y = self.pet.y + self.skin.point("nose", s)[1]
            near = abs(world.cursor_x - self.pet.x) < s * 5 and world.cursor_y > self.pet.y - s * 4
            look = (0.0, 0.0)
            target = None
            falling = next((i for i in self.items if i.kind == "treat"), None)
            if self.pet.state == "fetch" and self.ball and not self.pet.carrying_ball:
                target = (self.ball.x, self.ball.y)                  # segue la palla che rimbalza
            elif self.pet.state == "treat" and falling is not None and not self.pet._moved:
                target = (falling.x, falling.y)                      # e il biscotto che cade
            elif near and self.pet.state in ("idle", "sit", "walk", "tilt", "boop", "squint"):
                target = (world.cursor_x, world.cursor_y)
            if target:
                look = (max(-1.0, min(1.0, (target[0] - self.pet.x) / (s * 2.2))),
                        max(-1.0, min(1.0, (target[1] - eye_y) / (s * 2.0))))
                if self.pet.pose.facing < 0:
                    look = (-look[0], look[1])
            self.skin.advance(dt, self.pet.pose, look)
        if self.ball:
            self.ball.update(dt, 0.0, float(self.width()), self.ground())
            if self.pet.carrying_ball:
                self.ball.x = self.pet.x - self.size_px * 0.42 * self.pet.facing * -1
                self.ball.y = self.pet.y - self.size_px * 0.52
                if self.skin:
                    mx, my = self.skin.point("mouth", self.size_px)
                    self.ball.x = self.pet.x + mx * self.pet.facing
                    self.ball.y = self.pet.y + my + self.ball.radius * 1.5
                self.ball.resting = False
                self.ball.age = 0.0
        self._expire(dt)
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
                    self.ball.vx = self.ball.vy = 0.0
                    self.ball.delivered = True
                    self.ball.age = 0.0
                    self.ball.y = self.ground()
            elif effect.kind == "poop":
                self._add_item(Item("poop", effect.x, self.ground(), size=max(12.0, self.size_px * 0.17),
                                    resting=True))
            elif effect.kind == "eat_treat":
                near = min((i for i in self.items if i.kind == "treat"),
                           key=lambda i: abs(i.x - self.pet.x), default=None)
                if near is not None:
                    self.items.remove(near)
            else:
                x, y = effect.x, effect.y
                if self.skin and effect.kind in ("zzz", "heart"):      # dalla testa, ovunque sia
                    hx, hy = self.skin.point("head", self.size_px)
                    x, y = self.pet.x + hx + random.uniform(-10, 10), self.pet.y + hy
                if effect.kind == "crumb" and self.bowl and self.pet.state == "eat":
                    self.bowl.full = max(0.0, self.bowl.full - 0.08)
                    x = self.bowl.x
                self.particles.spawn(effect.kind, x, y, effect.text)
        self.pet.effects.clear()

    # --------------------------------------------------------------- disegno
    def paintEvent(self, event) -> None:  # noqa: N802 (API Qt)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        scale = self.size_px / 100.0
        rects: list[QRect] = []

        ttl = self.props_ttl
        if self.bowl:
            painter.setOpacity(fade(self.bowl.age, ttl))
            render.draw_bowl(painter, self.bowl.x, self.bowl.y, self.bowl.width, self.bowl.full)
            rects.append(QRect(int(self.bowl.x - self.bowl.width), int(self.bowl.y - self.bowl.width),
                               int(self.bowl.width * 2), int(self.bowl.width * 1.5)))
        for item in self.items:
            painter.setOpacity(fade(item.age, ttl))
            if item.kind == "poop":
                render.draw_poop(painter, item.x, item.y, item.size, max(0.0, 1.0 - item.age / 25.0), self._clock)
            else:
                render.draw_treat(painter, item.x, item.y, item.size, item.spin)
            rects.append(self._item_rect(item))
        # in bocca al cane mentre e' di spalle o lontano: la palla non si vede
        hidden = self.pet.carrying_ball and self.skin is not None and (
            self.skin.away > 0.2 or not self.skin.rig.face)
        if self.ball and not hidden:
            painter.setOpacity(fade(self.ball.age, ttl))
            render.draw_ball(painter, self.ball.x, self.ball.y, self.ball.radius)
            r = self.ball.radius
            rects.append(QRect(int(self.ball.x - r * 2), int(self.ball.y - r * 3), int(r * 4), int(r * 5)))
        painter.setOpacity(1.0)

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

        if self.bubble and (self.skin is None or self.skin.visible):
            text, life = self.bubble
            rect = render.draw_bubble(painter, self.pet.x, max(34.0 * scale, dog.top() - 6), text,
                                      min(1.0, life / 0.4), scale)
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
    def _item_rect(self, item: Item) -> QRect:
        s = item.size
        tall = 1.7 if item.kind == "poop" else 1.0
        return QRect(int(item.x - s), int(item.y - s * tall), int(s * 2), int(s * tall + 4))

    def _hits_dog(self, pos) -> bool:
        if self.skin and not self.skin.visible:
            return False
        return self.dog_rect().adjusted(-6, -6, 6, 6).contains(pos)

    def _click_props(self, pos) -> bool:
        """Click su un ricordino: raccolto. Click sulla palla ferma: un calcetto."""
        point = pos.toPoint()
        for item in self.items:
            if item.kind == "poop" and self._item_rect(item).contains(point):
                self.items.remove(item)
                for _ in range(4):
                    self.particles.spawn("star", item.x, item.y - item.size * 0.6)
                self.pet.stats.felicita += 2
                self.pet.stats.clamp()
                return True
        ball = self.ball
        if ball and ball.resting and not self.pet.carrying_ball:
            r = ball.radius
            if QRectF(ball.x - r * 1.6, ball.y - r * 2.6, r * 3.2, r * 3.2).contains(pos):
                ball.resting = False
                ball.delivered = False
                ball.age = 0.0
                ball.vx = random.choice((-1, 1)) * random.uniform(200, 380)
                ball.vy = -random.uniform(260, 420)
                if self.pet.state in ("idle", "sit", "look", "tilt", "squint"):
                    self.pet.set_state("fetch", 25.0)
                return True
        return False

    def mousePressEvent(self, event) -> None:  # noqa: N802
        pos = event.position()
        if event.button() == Qt.LeftButton and not self._hits_dog(pos) and self._click_props(pos):
            event.accept()
            return
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
