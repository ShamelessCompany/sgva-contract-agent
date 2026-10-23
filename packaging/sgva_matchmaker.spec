# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller: genera la app de escritorio de SGVA-Matchmaker.

    pyinstaller --noconfirm --clean packaging/sgva_matchmaker.spec

Modo (variable de entorno SGVA_BUILD_MODE):
    onefile (por defecto) → dist/SGVA-Matchmaker.exe          · un solo archivo para compartir
    onedir                → dist/SGVA-Matchmaker/…exe          · arranca más rápido, menos
                                                                 falsos positivos de antivirus

El ejecutable NO incluye navegador: usa Microsoft Edge (preinstalado en Windows 10/11) o
Google Chrome. Tampoco incluye WeasyPrint: los PDF se imprimen con ese mismo navegador.
"""

import os
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

RAIZ = Path(SPECPATH).parent  # noqa: F821 - SPECPATH lo define PyInstaller
MODO = os.getenv("SGVA_BUILD_MODE", "onefile").lower()
NOMBRE = "Patronix"
ICONO = str(RAIZ / "assets" / ("icon.ico" if sys.platform == "win32" else "icon.png"))

datas = [
    (str(RAIZ / "config" / "selectors.json"), "config"),
    (str(RAIZ / "data" / "perfil_aprendiz.example.json"), "data"),
    (str(RAIZ / "assets" / "icon.ico"), "assets"),
    (str(RAIZ / "assets" / "icon.png"), "assets"),
    (str(RAIZ / "LICENSE"), "."),
]
datas += collect_data_files("customtkinter")

hiddenimports = (
    collect_submodules("ddgs")              # motores de búsqueda cargados dinámicamente
    + collect_submodules("keyring.backends")  # Administrador de credenciales de Windows
    + collect_submodules("modules")
    + ["telegram.ext"]
    + (["win32ctypes.core", "keyring.backends.Windows"] if sys.platform == "win32" else [])
)

a = Analysis(  # noqa: F821
    [str(RAIZ / "app_gui.py")],
    pathex=[str(RAIZ)],
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=[
        "weasyprint", "pytest", "IPython", "matplotlib", "numpy", "pandas", "scipy", "PIL",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "tkinter.test", "lib2to3",
    ],
    noarchive=False,
)
pyz = PYZ(a.pure)  # noqa: F821

version = str(RAIZ / "packaging" / "version_info.txt") if sys.platform == "win32" else None
comunes = dict(
    name=NOMBRE,
    icon=ICONO,
    console=False,          # app de ventana: sin consola negra
    disable_windowed_traceback=False,
    upx=False,              # UPX dispara más falsos positivos de antivirus
    version=version,
)

if MODO == "onedir":
    exe = EXE(pyz, a.scripts, [], exclude_binaries=True, **comunes)  # noqa: F821
    coll = COLLECT(exe, a.binaries, a.datas, name=NOMBRE, upx=False)  # noqa: F821
else:
    exe = EXE(pyz, a.scripts, a.binaries, a.datas, [], runtime_tmpdir=None, **comunes)  # noqa: F821
