"""Utilidades transversales: logging, retardos éticos, reintentos y normalización de texto."""

from __future__ import annotations

import asyncio
import functools
import hashlib
import logging
import random
import re
import sys
import threading
import time
import unicodedata
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar

T = TypeVar("T")

# Señal global de cancelación: la app de escritorio la activa con el botón "Detener".
# Todas las pausas del pipeline la revisan, así que el proceso se detiene en segundos.
CANCELAR = threading.Event()


class Cancelado(BaseException):
    """El usuario detuvo el proceso. Hereda de BaseException (como KeyboardInterrupt)
    para que ningún `except Exception` del pipeline lo silencie."""


def verificar_cancelacion() -> None:
    if CANCELAR.is_set():
        raise Cancelado("Proceso detenido por el usuario")


def dormir(segundos: float) -> None:
    """time.sleep cancelable."""
    if CANCELAR.wait(max(0.0, segundos)):
        raise Cancelado("Proceso detenido por el usuario")


async def dormir_async(segundos: float) -> None:
    """asyncio.sleep cancelable (revisa la señal cada 0,25 s)."""
    fin = time.monotonic() + max(0.0, segundos)
    while True:
        verificar_cancelacion()
        restante = fin - time.monotonic()
        if restante <= 0:
            return
        await asyncio.sleep(min(0.25, restante))

# User-Agents de navegadores de escritorio reales y vigentes. Se rota uno por sesión
# (no por petición) para que el comportamiento sea consistente y no sospechoso.
USER_AGENTS: tuple[str, ...] = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/139.0.0.0 Safari/537.36 Edg/139.0.0.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:143.0) Gecko/20100101 Firefox/143.0",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36",
)


def setup_logging(logs_dir: Path, level: int = logging.INFO) -> None:
    """Configura logging a consola y a archivo rotativo en `logs/`."""
    logs_dir.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s | %(levelname)-7s | %(name)s | %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    if root.handlers:  # evitar duplicados si se llama dos veces
        return
    archivo = RotatingFileHandler(
        logs_dir / "matchmaker.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    archivo.setFormatter(fmt)
    root.addHandler(archivo)
    if sys.stderr is not None:  # en el .exe sin consola, stderr es None
        consola = logging.StreamHandler()
        consola.setFormatter(fmt)
        root.addHandler(consola)
    # Silenciar librerías muy verbosas
    for ruidoso in ("httpx", "httpcore", "urllib3", "primp", "telegram", "fontTools", "ddgs"):
        logging.getLogger(ruidoso).setLevel(logging.WARNING)
    logging.getLogger("weasyprint").setLevel(logging.ERROR)


def random_user_agent() -> str:
    return random.choice(USER_AGENTS)


def polite_delay(min_s: float = 2.0, max_s: float = 5.0) -> float:
    """Pausa síncrona aleatoria entre `min_s` y `max_s` segundos. Devuelve la espera."""
    espera = random.uniform(min_s, max_s)
    dormir(espera)
    return espera


async def polite_delay_async(min_s: float = 2.0, max_s: float = 5.0) -> float:
    """Versión asíncrona de `polite_delay` para usar con Playwright async."""
    espera = random.uniform(min_s, max_s)
    await dormir_async(espera)
    return espera


def retry(
    intentos: int = 3,
    backoff_base: float = 4.0,
    excepciones: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorador de reintentos con backoff exponencial + jitter (funciones síncronas)."""

    def deco(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            log = logging.getLogger(func.__module__)
            for intento in range(1, intentos + 1):
                try:
                    return func(*args, **kwargs)
                except excepciones as exc:
                    if intento == intentos:
                        raise
                    espera = backoff_base * (2 ** (intento - 1)) + random.uniform(0, 1.5)
                    log.warning(
                        "%s falló (intento %d/%d): %s. Reintentando en %.1fs",
                        func.__name__, intento, intentos, exc, espera,
                    )
                    dormir(espera)
            raise RuntimeError("inalcanzable")

        return wrapper

    return deco


def retry_async(
    intentos: int = 3,
    backoff_base: float = 4.0,
    excepciones: tuple[type[BaseException], ...] = (Exception,),
) -> Callable[[Callable[..., Awaitable[T]]], Callable[..., Awaitable[T]]]:
    """Decorador de reintentos con backoff exponencial para corrutinas."""

    def deco(func: Callable[..., Awaitable[T]]) -> Callable[..., Awaitable[T]]:
        @functools.wraps(func)
        async def wrapper(*args: Any, **kwargs: Any) -> T:
            log = logging.getLogger(func.__module__)
            for intento in range(1, intentos + 1):
                try:
                    return await func(*args, **kwargs)
                except excepciones as exc:
                    if intento == intentos:
                        raise
                    espera = backoff_base * (2 ** (intento - 1)) + random.uniform(0, 1.5)
                    log.warning(
                        "%s falló (intento %d/%d): %s. Reintentando en %.1fs",
                        func.__name__, intento, intentos, exc, espera,
                    )
                    await dormir_async(espera)
            raise RuntimeError("inalcanzable")

        return wrapper

    return deco


def normalizar(texto: str | None) -> str:
    """Minúsculas, sin tildes y con espacios colapsados. Útil para comparar."""
    if not texto:
        return ""
    sin_tildes = "".join(
        c for c in unicodedata.normalize("NFD", texto) if unicodedata.category(c) != "Mn"
    )
    return re.sub(r"\s+", " ", sin_tildes).strip().lower()


def limpiar(texto: str | None) -> str:
    """Colapsa espacios y saltos de línea preservando mayúsculas y tildes."""
    if not texto:
        return ""
    return re.sub(r"\s+", " ", texto).strip()


def slugify(texto: str, max_len: int = 60) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", normalizar(texto)).strip("-")
    return (base or "sin-nombre")[:max_len].rstrip("-")


def stable_hash(*partes: str) -> str:
    """Hash SHA-1 estable de varios campos normalizados (para IDs y deduplicación)."""
    contenido = "|".join(normalizar(p) for p in partes)
    return hashlib.sha1(contenido.encode("utf-8")).hexdigest()[:16]


def contar_palabras(texto: str) -> int:
    return len(re.findall(r"\b[\wáéíóúñÁÉÍÓÚÑüÜ@.'-]+\b", texto or ""))
