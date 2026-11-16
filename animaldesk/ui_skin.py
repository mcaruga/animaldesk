"""Finestra "Nuovo animale da foto": la pipeline automatica + correzione a mano dei punti."""

from __future__ import annotations

import json
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QDialog, QDialogButtonBox, QLabel,
                               QVBoxLayout, QWidget)

from .config import config_dir

LABELS = {"eye_left": "occhio", "eye_right": "occhio", "nose": "naso", "mouth": "bocca",
          "head_top": "testa", "neck": "collo"}


class _Canvas(QWidget):
    """Sprite con i punti del viso: si trascinano per correggerli."""

    def __init__(self, image: QImage, points: dict[str, list[float]], parent=None) -> None:
        super().__init__(parent)
        self.image = image
        self.points = points
        self._drag: str | None = None
        scale = 460 / max(image.width(), image.height())
        self.setFixedSize(int(image.width() * scale), int(image.height() * scale))

    def _pos(self, key: str) -> QPointF:
        return QPointF(self.points[key][0] * self.width(), self.points[key][1] * self.height())

    def mousePressEvent(self, event) -> None:  # noqa: N802
        p = event.position()
        self._drag = min(self.points, key=lambda k: (self._pos(k) - p).manhattanLength())
        self.mouseMoveEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._drag:
            p = event.position()
            self.points[self._drag] = [min(1.0, max(0.0, p.x() / self.width())),
                                       min(1.0, max(0.0, p.y() / self.height()))]
            self.update()

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        self._drag = None

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)
        painter.fillRect(self.rect(), QColor("#2E3440"))
        painter.drawImage(QRectF(0, 0, self.width(), self.height()), self.image)
        for key in self.points:
            c = self._pos(key)
            painter.setPen(QPen(QColor("#00E5FF" if key.startswith("eye") else "#FF3B6B"), 2))
            painter.drawEllipse(c, 9, 9)
            painter.setPen(QColor("#FFFFFF"))
            painter.drawText(c + QPointF(12, 4), LABELS[key])
        painter.end()


class SkinWizard(QDialog):
    """Foto → pelle animata. L'AI (se c'e' una chiave) trova i punti; qui si possono ritoccare."""

    def __init__(self, photo: Path, name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nuovo animale da foto")
        self.name = name
        from .tools.auto_skin import build_skin

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.report = build_skin(photo, name, config_dir() / "skins")
        finally:
            QApplication.restoreOverrideCursor()
        self.folder = Path(self.report["folder"])
        rig = self.report["rig"]
        points = {
            "eye_left": [rig["eyes"][0]["x"], rig["eyes"][0]["y"]],
            "eye_right": [rig["eyes"][1]["x"], rig["eyes"][1]["y"]],
            "nose": list(rig["nose"]), "mouth": list(rig["mouth"]),
            "head_top": list(rig["head_top"]), "neck": list(rig["neck"]),
        }
        how = {"ai": "L'AI ha trovato i punti del viso.",
               "pixel": "Punti stimati dai pixel (senza AI).",
               "manuale": "Non ho trovato occhi e naso: trascina i punti al posto giusto."}[self.report["method"]]
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(how + "\nControlla e, se serve, trascinali: occhi, naso, bocca, testa, collo."))
        self.canvas = _Canvas(QImage(str(self.folder / "sprite.png")), points, self)
        layout.addWidget(self.canvas)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        import cv2

        from .tools.auto_skin import make_rig

        pts = self.canvas.points
        old = self.report["rig"]
        marks = {k: {"x": v[0], "y": v[1]} for k, v in pts.items()}
        for key, ear in (("ear_left", old["ear_l"]), ("ear_right", old["ear_r"])):
            marks[key] = {"base": {"x": ear[2], "y": ear[3]},
                          "tip": {"x": (ear[0] - 0.35 * ear[2]) / 0.65, "y": (ear[1] - 0.35 * ear[3]) / 0.65}}
        sprite = cv2.imread(str(self.folder / "sprite.png"), cv2.IMREAD_UNCHANGED)
        rig = make_rig(sprite, marks, self.name, has_paw=(self.folder / "paw.png").exists())
        (self.folder / "rig.json").write_text(json.dumps(rig, indent=2), encoding="utf-8")
        super().accept()
