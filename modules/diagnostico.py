"""
Autodiagnóstico: verifica en el equipo del usuario que todo lo necesario funciona.

    SGVA-Matchmaker.exe --autoprueba      (escribe autoprueba.json en la carpeta de datos)
    python app_gui.py --autoprueba
    Botón «Diagnóstico» en la pestaña «Acerca de».

No envía ningún dato personal: solo abre el navegador en una página en blanco, genera un
PDF de prueba, consulta si el almacén de credenciales existe y comprueba que el portal del
SENA responda.
"""

from __future__ import annotations

import asyncio
import json
import platform
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from config import DATA_HOME, FROZEN, Settings


@dataclass
class Chequeo:
    nombre: str
    ok: bool
    detalle: str
    critico: bool = True


def _carpetas(s: Settings) -> Chequeo:
    try:
        for carpeta in (s.data_dir, s.output_dir):
            prueba = carpeta / ".escritura"
            prueba.write_text("ok", "utf-8")
            prueba.unlink()
        return Chequeo("Carpetas de trabajo", True, f"Datos: {DATA_HOME} · Postulaciones: {s.output_dir}")
    except OSError as exc:
        return Chequeo("Carpetas de trabajo", False, f"No se puede escribir: {exc}")


def _navegador(s: Settings) -> Chequeo:
    from playwright.async_api import async_playwright

    from modules.scraper import lanzar_navegador

    async def probar() -> str:
        async with async_playwright() as pw:
            nav = await lanzar_navegador(pw, s.browser_channel, headless=True)
            try:
                pagina = await nav.new_page()
                await pagina.goto("about:blank")
                return f"{getattr(nav, 'canal_sgva', '') or 'chromium'} {nav.version}"
            finally:
                await nav.close()

    try:
        return Chequeo("Navegador", True, asyncio.run(probar()))
    except Exception as exc:  # noqa: BLE001
        return Chequeo("Navegador", False, str(exc)[:400])


def _pdf(s: Settings) -> Chequeo:
    from modules.cv_adapter import RenderizadorPDF, html_cv

    destino = Path(tempfile.gettempdir()) / "sgva_autoprueba.pdf"
    try:
        with RenderizadorPDF(s.browser_channel) as r:
            r.render(html_cv("# Prueba\n\nHoja de vida de prueba."), destino)
        ok = destino.read_bytes()[:4] == b"%PDF"
        destino.unlink(missing_ok=True)
        return Chequeo("Generación de PDF", ok, "PDF generado con el navegador" if ok else "Archivo inválido")
    except Exception as exc:  # noqa: BLE001
        return Chequeo("Generación de PDF", False, str(exc)[:300])


def _credenciales() -> Chequeo:
    from modules.app_state import AlmacenSecretos

    a = AlmacenSecretos()
    return Chequeo("Almacén de contraseñas", a.disponible, a.nombre, critico=False)


def _busqueda() -> Chequeo:
    try:
        from ddgs import DDGS  # noqa: F401

        return Chequeo("Motor de búsqueda web", True, "ddgs disponible", critico=False)
    except Exception as exc:  # noqa: BLE001
        return Chequeo("Motor de búsqueda web", False, str(exc)[:200], critico=False)


def _portal(s: Settings) -> Chequeo:
    import requests

    try:
        r = requests.get(s.sgva_login_url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        return Chequeo("Portal Caprendizaje", r.status_code < 500,
                       f"HTTP {r.status_code} en {s.sgva_login_url}", critico=False)
    except requests.RequestException as exc:
        return Chequeo("Portal Caprendizaje", False,
                       f"Sin respuesta ({type(exc).__name__}). ¿Hay internet?", critico=False)


def ejecutar(s: Settings, red: bool = True) -> list[Chequeo]:
    chequeos = [_carpetas(s), _navegador(s), _pdf(s), _credenciales(), _busqueda()]
    if red:
        chequeos.append(_portal(s))
    return chequeos


def guardar_reporte(chequeos: list[Chequeo], destino: Path | None = None) -> Path:
    from modules import __version__

    destino = destino or DATA_HOME / "autoprueba.json"
    destino.parent.mkdir(parents=True, exist_ok=True)
    destino.write_text(json.dumps({
        "fecha": datetime.now().isoformat(timespec="seconds"),
        "version": __version__,
        "empaquetado": FROZEN,
        "sistema": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "python": sys.version.split()[0],
        "ok": all(c.ok for c in chequeos if c.critico),
        "chequeos": [asdict(c) for c in chequeos],
    }, ensure_ascii=False, indent=2), "utf-8")
    return destino
