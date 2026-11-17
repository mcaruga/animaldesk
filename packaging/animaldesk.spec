# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller: eseguibile singolo, senza console."""

import sys
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parent
icon = str(ROOT / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png"))

a = Analysis(
    [str(ROOT / "packaging" / "entry.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=[(str(ROOT / "assets" / "skins"), "assets/skins")],
    hiddenimports=["PySide6.QtCore", "PySide6.QtGui", "PySide6.QtWidgets",
                   "animaldesk.tools.auto_skin", "animaldesk.ui_skin", "cv2", "numpy", "anthropic"],
    # pymatting/numba restano fuori: pesano >100 MB; senza, il ritaglio usa la sfumatura semplice
    excludes=["PySide6.QtWebEngineCore", "PySide6.QtQuick", "PySide6.Qt3DCore",
              "PySide6.QtMultimedia", "PySide6.QtNetwork", "tkinter",
              "pymatting", "numba", "llvmlite", "scipy", "matplotlib", "PIL", "pytest"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name="AnimalDesk",
    console=False,
    icon=icon,
    upx=False,
)

if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name="AnimalDesk.app",
        icon=icon,
        bundle_identifier="com.animaldesk.app",
        info_plist={"LSUIElement": True, "CFBundleShortVersionString": "1.4.0"},
    )
