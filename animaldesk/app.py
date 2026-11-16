"""Applicazione AnimalDesk: tray, menu e ciclo di vita."""

from __future__ import annotations

import sys

from PySide6.QtCore import QPoint, Qt
from PySide6.QtGui import QAction, QActionGroup, QIcon, QPainter, QPixmap
from pathlib import Path

from PySide6.QtWidgets import (QApplication, QFileDialog, QMenu, QMessageBox,
                               QSystemTrayIcon)

from . import APP_NAME, __version__, autostart, outfits, render
from .breeds import BREEDS
from .config import SIZES, Config, find_skin, list_skins
from .pet import Stats
from .skin import Skin

ACTIONS = [            # disegno vettoriale (corpo intero)
    ("Siediti", "sit"),
    ("Sdraiati e dormi", "sleep"),
    ("Abbaia", "bark"),
    ("Scava", "dig"),
    ("Capriola", "roll"),
    ("Rincorri la coda", "spin"),
    ("Salta", "jump"),
    ("Grattati", "scratch"),
]

PHOTO_ACTIONS = [      # pelle fotografica (affacciato dal bordo)
    ("Seduto", "sit"),
    ("Dormi", "sleep"),
    ("Scrivi alla tastiera", "typing"),
    ("Nascondino", "hide"),
    ("Lecca la zampa", "lick"),
    ("Guardati intorno", "look"),
    ("Testa di lato", "tilt"),
    ("Grattati", "scratch"),
    ("Occhi felici", "squint"),
    ("Linguetta", "boop"),
    ("Dispetto", "tease"),
    ("Abbaia", "bark"),
]


def make_icon(size: int = 64) -> QIcon:
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    painter = QPainter(pix)
    render.draw_head_icon(painter, size)
    painter.end()
    return QIcon(pix)


class AnimalDeskApp:
    def __init__(self, argv: list[str]) -> None:
        self.qt = QApplication(argv)
        self.qt.setApplicationName(APP_NAME)
        self.qt.setQuitOnLastWindowClosed(False)
        self.config = Config.load()
        self.stats = Stats(**self.config.stats)

        from .overlay import PetOverlay  # import tardivo: serve QApplication viva

        screens = self.qt.screens()
        index = min(self.config.screen_index, len(screens) - 1)
        self.overlay = PetOverlay(screens[index], self.config.size, self.config.speed,
                                  self.stats, self.config.follow_cursor,
                                  skin=self.load_skin(self.config.skin), breed=self.config.breed)
        self.overlay.set_outfit(outfits.resolve(self.config.outfit))
        self.overlay.context_requested.connect(self.show_menu)
        self.overlay.show()

        self.tray = QSystemTrayIcon(make_icon(), self.qt)
        self.tray.setToolTip(f"{APP_NAME} - {self.config.name}")
        self.tray.activated.connect(self._tray_activated)
        self.menu = QMenu()
        self.tray.setContextMenu(self.menu)
        self.tray.show()
        self.qt.aboutToQuit.connect(self.save)

    # -------------------------------------------------------------------- menu
    def build_menu(self) -> QMenu:
        menu = QMenu()
        stats = self.stats
        header = menu.addAction(
            f"{self.config.name}  |  energia {stats.energia:.0f}%  fame {stats.fame:.0f}%  felicita {stats.felicita:.0f}%"
        )
        header.setEnabled(False)
        menu.addSeparator()

        for label, action in (PHOTO_ACTIONS if self.overlay.skin else ACTIONS):
            menu.addAction(label, lambda a=action: self.overlay.command(a))
        menu.addSeparator()
        menu.addAction("Lancia la palla", lambda: self.overlay.command("ball"))
        menu.addAction("Dai da mangiare", lambda: self.overlay.command("feed"))

        follow = menu.addAction("Insegui il mouse")
        follow.setCheckable(True)
        follow.setChecked(self.overlay.follow_cursor)
        follow.triggered.connect(lambda: self.overlay.command("follow"))
        menu.addSeparator()

        look = menu.addMenu("Aspetto")
        look_group = QActionGroup(look)
        for name in list_skins():
            act = look.addAction(f"Foto: {name}")
            act.setCheckable(True)
            act.setActionGroup(look_group)
            act.setChecked(self.config.skin == name)
            act.triggered.connect(lambda _=False, n=name: self.set_skin(n))
        look.addSeparator()
        for key, breed in BREEDS.items():
            act = look.addAction(f"Disegno: {breed.label}")
            act.setCheckable(True)
            act.setActionGroup(look_group)
            act.setChecked(not self.config.skin and self.config.breed == key)
            act.triggered.connect(lambda _=False, k=key: self.set_breed(k))
        look.addSeparator()
        look.addAction("Nuovo animale da foto...", self.new_skin_from_photo)

        if self.overlay.skin:
            wear = menu.addMenu("Costume")
            wear_group = QActionGroup(wear)
            today = outfits.OUTFITS.get(outfits.seasonal(), "nessuno").lower()
            for key, label in [("auto", f"Automatico (oggi: {today})")] + list(outfits.OUTFITS.items()):
                act = wear.addAction(label)
                act.setCheckable(True)
                act.setActionGroup(wear_group)
                act.setChecked(self.config.outfit == key)
                act.triggered.connect(lambda _=False, k=key: self.set_outfit(k))

        size_menu = menu.addMenu("Dimensione")
        group = QActionGroup(size_menu)
        for name, value in SIZES.items():
            act = size_menu.addAction(name.capitalize())
            act.setCheckable(True)
            act.setActionGroup(group)
            act.setChecked(abs(self.overlay.size_px - value) < 1)
            act.triggered.connect(lambda _=False, v=value: self.set_size(v))

        speed_menu = menu.addMenu("Vivacita")
        for name, value in (("Calmo", 0.6), ("Normale", 1.0), ("Scatenato", 1.8)):
            act = speed_menu.addAction(name)
            act.setCheckable(True)
            act.setChecked(abs(self.config.speed - value) < 0.01)
            act.triggered.connect(lambda _=False, v=value: self.set_speed(v))

        screens = self.qt.screens()
        if len(screens) > 1:
            screen_menu = menu.addMenu("Schermo")
            for i, screen in enumerate(screens):
                act = screen_menu.addAction(f"{i + 1}: {screen.name()}")
                act.setCheckable(True)
                act.setChecked(i == self.config.screen_index)
                act.triggered.connect(lambda _=False, idx=i: self.set_screen(idx))

        auto = menu.addAction("Avvia con il sistema")
        auto.setCheckable(True)
        auto.setChecked(autostart.is_enabled())
        auto.triggered.connect(self.toggle_autostart)

        menu.addSeparator()
        menu.addAction("Informazioni", self.about)
        menu.addAction("Esci", self.quit)
        return menu

    def show_menu(self, pos: QPoint) -> None:
        self.menu = self.build_menu()
        self.menu.exec(pos)

    def _tray_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.Context):
            self.menu = self.build_menu()
            self.tray.setContextMenu(self.menu)
            self.menu.exec(self.tray.geometry().center())

    # ----------------------------------------------------------------- aspetto
    @staticmethod
    def load_skin(name: str) -> Skin | None:
        folder = find_skin(name)
        if folder is None:
            return None
        try:
            return Skin.load(folder)
        except (OSError, ValueError, KeyError, TypeError):
            return None

    def set_skin(self, name: str) -> None:
        skin = self.load_skin(name)
        if skin is None:
            QMessageBox.warning(None, APP_NAME, f"Non trovo la pelle '{name}'.")
            return
        self.config.skin = name
        self.overlay.set_skin(skin)
        self.overlay.set_outfit(outfits.resolve(self.config.outfit))

    def set_outfit(self, key: str) -> None:
        self.config.outfit = key
        self.overlay.set_outfit(outfits.resolve(key))

    def set_breed(self, key: str) -> None:
        self.config.skin = ""
        self.config.breed = key
        self.overlay.set_skin(None)
        self.overlay.set_breed(key)

    def new_skin_from_photo(self) -> None:
        path, _ = QFileDialog.getOpenFileName(None, "Scegli una foto del tuo animale", "",
                                              "Immagini (*.jpg *.jpeg *.png *.webp)")
        if not path:
            return
        try:
            from .ui_skin import SkinWizard

            name = Path(path).stem.lower().replace(" ", "-")[:32] or "mio-cane"
            wizard = SkinWizard(Path(path), name)
        except ImportError:            # opencv mancante
            QMessageBox.warning(None, APP_NAME, "Per creare una pelle da foto serve:\n"
                                                "pip install \"animaldesk[foto]\"")
            return
        except ValueError as exc:      # foto non adatta o ritaglio fallito
            QMessageBox.warning(None, APP_NAME, f"Questa foto non va bene:\n{exc}")
            return
        if wizard.exec():
            self.set_skin(name)

    # ----------------------------------------------------------- impostazioni
    def set_size(self, value: int) -> None:
        self.config.size = value
        self.overlay.set_size(value)

    def set_speed(self, value: float) -> None:
        self.config.speed = value
        self.overlay.set_speed(value)

    def set_screen(self, index: int) -> None:
        screens = self.qt.screens()
        if not 0 <= index < len(screens):
            return
        self.config.screen_index = index
        self.overlay._screen = screens[index]
        self.overlay.apply_geometry()
        self.overlay.pet.x = self.overlay.width() / 2
        self.overlay.pet.y = self.overlay.ground()

    def toggle_autostart(self, checked: bool) -> None:
        ok = autostart.set_enabled(checked)
        self.config.autostart = checked and ok
        if not ok:
            QMessageBox.warning(None, APP_NAME, "Non sono riuscito a cambiare l'avvio automatico.")

    def about(self) -> None:
        QMessageBox.information(
            None,
            f"{APP_NAME} {__version__}",
            f"{APP_NAME}: un golden retriever che vive sul desktop.\n\n"
            "Trascinalo col mouse, doppio click per una carezza,\n"
            "tasto destro per il menu, rotellina per la taglia.\n\n"
            "Grafica vettoriale originale, nessun asset esterno.",
        )

    # ---------------------------------------------------------------- lifecycle
    def save(self) -> None:
        self.config.size = int(self.overlay.size_px)
        self.config.follow_cursor = self.overlay.follow_cursor
        self.config.stats = {
            "energia": self.stats.energia,
            "fame": self.stats.fame,
            "felicita": self.stats.felicita,
        }
        self.config.save()

    def quit(self) -> None:
        self.save()
        self.qt.quit()

    def run(self) -> int:
        return self.qt.exec()


def self_test() -> int:
    """Prova che il programma (anche impacchettato in .exe) parta e disegni davvero.

    La usa la CI sul .exe appena costruito: 0 = tutto bene. Il dettaglio finisce
    in animaldesk-selftest.log nella cartella temporanea.
    """
    import os
    import tempfile
    import traceback

    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    log = Path(tempfile.gettempdir()) / "animaldesk-selftest.log"
    lines: list[str] = [f"{APP_NAME} {__version__} frozen={getattr(sys, 'frozen', False)}"]
    code = 0
    try:
        app = AnimalDeskApp(["animaldesk"])
        ov = app.overlay
        ov._timer.stop()
        if ov.skin is None:
            raise RuntimeError("pelle fotografica di default non trovata nel pacchetto")
        lines.append(f"pelle: {ov.skin.name} {ov.skin.image.width()}x{ov.skin.image.height()}")
        for _, action in PHOTO_ACTIONS:
            ov.command(action)
            for _ in range(15):
                ov._tick()
            if ov.grab().isNull():
                raise RuntimeError(f"nessun frame per l'azione {action}")
        for outfit in ("santa", "summer", "ski", ""):
            ov.set_outfit(outfit)
            for _ in range(5):
                ov._tick()
            ov.grab()
        app.set_breed("barboncino")
        for _ in range(5):
            ov._tick()
        ov.grab()
        app.build_menu()
        lines.append("azioni, costumi, disegno e menu: ok")

        # "Nuovo animale da foto": la pipeline deve funzionare anche dentro l'eseguibile
        import cv2
        import numpy as np

        from .tools.auto_skin import build_skin

        img = np.full((420, 360, 3), (150, 120, 95), np.uint8)
        cv2.ellipse(img, (180, 230), (110, 150), 0, 0, 360, (150, 200, 235), -1)
        for cx, cy, rx, ry in ((140, 175, 15, 10), (220, 175, 15, 10), (180, 240, 25, 19)):
            cv2.ellipse(img, (cx, cy), (rx, ry), 0, 0, 360, (14, 14, 16), -1)
        with tempfile.TemporaryDirectory() as tmp:
            cv2.imwrite(str(Path(tmp) / "foto.png"), img)
            rep = build_skin(Path(tmp) / "foto.png", "prova", Path(tmp) / "skins", use_ai=False)
            Skin.load(rep["folder"])
        lines.append(f"da foto a pelle: ok ({rep['method']})")
        import anthropic

        lines.append(f"sdk visione: anthropic {anthropic.__version__}")
    except Exception:  # noqa: BLE001 - qui vogliamo proprio tutto nel log
        code = 1
        lines.append(traceback.format_exc())
    try:
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    print("\n".join(lines))
    return code


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv)
    if "--self-test" in args:
        return self_test()
    return AnimalDeskApp(args).run()
