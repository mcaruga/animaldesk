"""Finestra "Nuovo animale da foto": la pipeline automatica + correzione a mano dei punti."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPen
from PySide6.QtWidgets import (QApplication, QComboBox, QDialog, QDialogButtonBox,
                               QHBoxLayout, QLabel, QTabWidget, QVBoxLayout, QWidget)

from .config import config_dir

LABELS = {"eye_left": "occhio", "eye_right": "occhio", "nose": "naso", "mouth": "bocca",
          "head_top": "testa", "neck": "collo"}
VIEW_NAMES = {"busto": "Primo piano", "seduto": "Figura intera", "serio": "Serio", "dietro": "Di spalle"}
USED_FOR = {"busto": "tastiera, nascondino, leccata, nanna", "seduto": "la posa di tutti i giorni",
            "serio": "\"non ho voglia\"", "dietro": "\"me ne vado\""}
SPECIES = (("cane", "Cane"), ("gatto", "Gatto"))


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
    """Foto → pelle animata. L'AI (se c'e' una chiave) riconosce specie, inquadratura
    e punti del viso di ogni foto; qui si controllano e si ritoccano."""

    def __init__(self, photos: Path | list[Path], name: str, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Nuovo animale da foto")
        self.name = name
        from .tools.auto_skin import build_skin

        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            self.report = build_skin(photos, name, config_dir() / "skins")
        finally:
            QApplication.restoreOverrideCursor()
        self.folder = Path(self.report["folder"])
        rep = self.report
        how = {"ai": "L'AI ha riconosciuto le foto e trovato i punti del viso.",
               "pixel": "Punti stimati dai pixel (senza AI).",
               "manuale": "Non ho trovato occhi e naso: trascina i punti al posto giusto."}[rep["method"]]
        lines = [how, "Controlla ogni vista e, se serve, trascina: occhi, naso, bocca, testa, collo."]
        if rep["missing"]:
            lines.append("Foto che puoi ancora aggiungere: " + "; ".join(
                f"{VIEW_NAMES[k].lower()} ({USED_FOR[k]})" for k in rep["missing"]))
        lines += [f"Attenzione: {w}" for w in rep["warnings"]]

        layout = QVBoxLayout(self)
        note = QLabel("\n".join(lines))
        note.setWordWrap(True)
        layout.addWidget(note)

        row = QHBoxLayout()
        row.addWidget(QLabel("Che animale e'?"))
        self.species = QComboBox(self)
        for key, label in SPECIES:
            self.species.addItem(label, key)
        self.species.setCurrentIndex(max(0, self.species.findData(rep["species"])))
        row.addWidget(self.species)
        row.addStretch(1)
        layout.addLayout(row)

        self.canvases: dict[str, _Canvas] = {}
        tabs = QTabWidget(self)
        for kind, rig in rep["rigs"].items():
            if rig.get("face") is False:
                continue                                   # di spalle: nessun punto da sistemare
            points = {
                "eye_left": [rig["eyes"][0]["x"], rig["eyes"][0]["y"]],
                "eye_right": [rig["eyes"][1]["x"], rig["eyes"][1]["y"]],
                "nose": list(rig["nose"]), "mouth": list(rig["mouth"]),
                "head_top": list(rig["head_top"]), "neck": list(rig["neck"]),
            }
            canvas = _Canvas(QImage(str(self.folder / rig["sprite"])), points, self)
            self.canvases[kind] = canvas
            tabs.addTab(canvas, VIEW_NAMES.get(kind, kind))
        layout.addWidget(tabs)
        # per compatibilita': il primo foglio e' "il" canvas
        self.canvas = next(iter(self.canvases.values()), None)
        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, parent=self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        from .tools.auto_skin import update_view

        species = self.species.currentData()
        for kind, canvas in self.canvases.items():
            update_view(self.folder, kind, canvas.points, species)
        super().accept()
