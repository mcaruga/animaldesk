import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

QtGui = pytest.importorskip("PySide6.QtGui")

from animaldesk import render
from animaldesk.render import Pose

POSES = {
    "in_piedi": Pose(),
    "cammina": Pose(leg_swing=1.0, leg_phase=1.2, tail_wag=18),
    "seduto": Pose(sit=1.0),
    "dorme": Pose(lie=1.0, eye_open=0.0),
    "abbaia": Pose(mouth_open=1.0),
    "capriola": Pose(spin=180, lie=0.7),
}


@pytest.fixture(scope="module")
def app():
    return QtGui.QGuiApplication.instance() or QtGui.QGuiApplication([])


@pytest.mark.parametrize("name", list(POSES))
def test_ogni_posa_disegna_pixel(app, name):
    img = QtGui.QImage(160, 160, QtGui.QImage.Format_ARGB32)
    img.fill(0)
    painter = QtGui.QPainter(img)
    render.draw_dog(painter, POSES[name], 150)
    render.draw_ball(painter, 20, 150, 8)
    render.draw_bowl(painter, 140, 150, 30)
    painter.end()
    opaque = sum(1 for y in range(0, 160, 4) for x in range(0, 160, 4) if img.pixelColor(x, y).alpha() > 0)
    assert opaque > 40, f"posa {name} quasi vuota"


def test_icona_tray_non_e_vuota(app):
    pix = QtGui.QPixmap(64, 64)
    pix.fill(QtGui.QColor(0, 0, 0, 0))
    painter = QtGui.QPainter(pix)
    render.draw_head_icon(painter, 64)
    painter.end()
    img = pix.toImage()
    assert any(img.pixelColor(x, y).alpha() > 0 for x in range(0, 64, 2) for y in range(0, 64, 2))
