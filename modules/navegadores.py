"""Navegadores compatibles y opciones de lanzamiento compartidas (scraper, PDF, diagnóstico).

Playwright solo controla navegadores basados en Chromium: Edge y Chrome por canal oficial;
Brave y Vivaldi por ruta del ejecutable. Firefox/Opera no son compatibles.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

# Etiqueta visible en la app → canal guardado en ajustes
OPCIONES: dict[str, str] = {
    "Automático (el que tengas instalado)": "auto",
    "Microsoft Edge": "msedge",
    "Google Chrome": "chrome",
    "Brave": "brave",
    "Vivaldi": "vivaldi",
}
ORDEN_AUTO = ("msedge", "chrome", "brave", "vivaldi")

_RUTAS = {  # relativas a LOCALAPPDATA / ProgramFiles / ProgramFiles(x86)
    "brave": (r"BraveSoftware\Brave-Browser\Application\brave.exe",),
    "vivaldi": (r"Vivaldi\Application\vivaldi.exe",),
}

# Sin la bandera de automatización: el navegador se comporta como uno normal y los
# firewalls del portal no frenan el inicio de sesión que haces tú a mano.
ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--enable-features=HttpsFirstBalancedMode,HttpsUpgrades",
]
IGNORAR = ["--enable-automation"]


def ruta_ejecutable(canal: str) -> str | None:
    for base in ("LOCALAPPDATA", "PROGRAMFILES", "PROGRAMFILES(X86)"):
        raiz = os.environ.get(base)
        for rel in _RUTAS.get(canal, ()):
            if raiz and (Path(raiz) / rel).is_file():
                return str(Path(raiz) / rel)
    return None


def candidatos(canal: str, headless: bool) -> list[tuple[str, dict[str, Any]]]:
    """(nombre, kwargs para chromium.launch) en orden de preferencia; el elegido primero
    y luego los demás instalados, para no fallar si falta uno."""
    canal = canal or "auto"
    orden = [canal] + [c for c in ORDEN_AUTO if c != canal] if canal != "auto" else list(ORDEN_AUTO)
    base: dict[str, Any] = {
        "headless": headless,
        "args": ARGS + ([] if headless else ["--start-maximized"]),
        "ignore_default_args": IGNORAR,
    }
    salida: list[tuple[str, dict[str, Any]]] = []
    for c in orden:
        if c in ("msedge", "chrome"):
            salida.append((c, {**base, "channel": c}))
        elif ruta := ruta_ejecutable(c):
            salida.append((c, {**base, "executable_path": ruta}))
    salida.append(("chromium", base))  # Chromium descargado por Playwright (modo desarrollo)
    return salida


def opciones_contexto(headless: bool) -> dict[str, Any]:
    """Ventana visible: sin viewport fijo, la página ocupa toda la ventana (maximizable).
    Oculta: tamaño de escritorio estándar. Nunca se falsea el User-Agent."""
    base = {"locale": "es-CO", "timezone_id": "America/Bogota"}
    return {**base, "viewport": {"width": 1366, "height": 860}} if headless else {**base, "no_viewport": True}


if __name__ == "__main__":  # autocomprobación rápida
    vis = candidatos("brave", headless=False)
    assert vis[-1][0] == "chromium" and "--start-maximized" in vis[0][1]["args"]
    assert all(n != "brave" for n, _ in vis) or vis[0][0] == "brave"
    assert candidatos("auto", True)[0] == ("msedge", candidatos("auto", True)[0][1])
    assert opciones_contexto(False)["no_viewport"] is True
    print("ok", [n for n, _ in candidatos("auto", False)])
