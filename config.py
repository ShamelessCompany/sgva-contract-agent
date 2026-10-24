"""
Configuración centralizada de SGVA-Matchmaker.

Dos modos de ejecución:
- **Desarrollo / CLI** (`python main.py`): todo vive junto al código (data/, output/, .env).
- **App de escritorio** (`SGVA-Matchmaker.exe`, empaquetado con PyInstaller):
    · Datos privados (base SQLite, cookies `session.json`, ajustes) →
      %LOCALAPPDATA%\\SGVA-Matchmaker  (solo accesible por tu usuario de Windows).
    · Hojas de vida y correos generados → Documentos\\SGVA-Matchmaker.
    · Contraseñas y claves → Administrador de credenciales de Windows (ver app_gui.py).

Las credenciales del SGVA nunca se hardcodean ni se envían a servidores externos:
solo viajan al propio portal del SENA durante el login automatizado en tu equipo.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

APP_NAME = "Patronix"
FROZEN: bool = bool(getattr(sys, "frozen", False))

# Código / recursos de solo lectura (dentro del .exe: carpeta temporal de PyInstaller)
BASE_DIR: Path = Path(__file__).resolve().parent
RESOURCE_DIR: Path = Path(getattr(sys, "_MEIPASS", BASE_DIR))


def _carpeta_documentos() -> Path:
    """Carpeta Documentos real del usuario (respeta redirecciones de OneDrive en Windows)."""
    if sys.platform == "win32":
        try:
            import ctypes
            from ctypes import wintypes

            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            # CSIDL_PERSONAL = 5 (Mis documentos), SHGFP_TYPE_CURRENT = 0
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:
                return Path(buf.value)
        except Exception:  # noqa: BLE001
            pass
    return Path.home() / "Documents"


def _data_home() -> Path:
    if os.getenv("SGVA_HOME"):
        return Path(os.environ["SGVA_HOME"]).expanduser()
    if not FROZEN:
        return BASE_DIR
    if sys.platform == "win32":
        return Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    return Path.home() / f".{APP_NAME.lower()}"


def _output_home() -> Path:
    if os.getenv("SGVA_OUTPUT"):
        return Path(os.environ["SGVA_OUTPUT"]).expanduser()
    return _carpeta_documentos() / APP_NAME if FROZEN else BASE_DIR / "output"


DATA_HOME: Path = _data_home()
OUTPUT_HOME: Path = _output_home()

load_dotenv(DATA_HOME / ".env")
if DATA_HOME != BASE_DIR:
    load_dotenv(BASE_DIR / ".env")


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_int(name: str, default: int) -> int:
    try:
        return int(_env(name, str(default)))
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(_env(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = _env(name, "true" if default else "false").lower()
    return raw in {"1", "true", "yes", "si", "sí", "on"}


def _env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in _env(name, default).split(",") if item.strip()]


def _canal_por_defecto() -> str:
    """En el .exe se usa el navegador ya instalado (Edge viene con Windows 10/11)."""
    if _env("BROWSER_CHANNEL"):
        return _env("BROWSER_CHANNEL")
    return "msedge" if FROZEN else ""


@dataclass(frozen=True)
class Settings:
    """Parámetros de ejecución. Se construye con `get_settings()` o `build_settings()`."""

    # --- Rutas ---
    base_dir: Path = BASE_DIR
    data_dir: Path = DATA_HOME / "data"
    output_dir: Path = OUTPUT_HOME
    logs_dir: Path = DATA_HOME / "logs"
    db_path: Path = DATA_HOME / "data" / "jobs.db"
    json_path: Path = DATA_HOME / "data" / "vacantes_activas.json"
    session_path: Path = DATA_HOME / "session.json"
    perfil_path: Path = DATA_HOME / "data" / "perfil_aprendiz.json"
    selectors_path: Path = RESOURCE_DIR / "config" / "selectors.json"

    # --- SGVA / Caprendizaje ---
    sena_user: str = field(default_factory=lambda: _env("SENA_USER"))
    sena_password: str = field(default_factory=lambda: _env("SENA_PASSWORD"))
    sgva_login_url: str = field(
        default_factory=lambda: _env("SGVA_LOGIN_URL", "https://caprendizaje.sena.edu.co/sgva/SGVA_Diseno/pag/login.aspx")
    )
    sgva_vacantes_url: str = field(default_factory=lambda: _env("SGVA_VACANTES_URL"))
    programa_formacion: str = field(
        default_factory=lambda: _env(
            "PROGRAMA_FORMACION", "Análisis y Desarrollo de Software"
        )
    )
    palabras_clave_area: list[str] = field(
        default_factory=lambda: _env_list(
            "PALABRAS_CLAVE_AREA", "ADSO,software,desarrollo,programación,sistemas"
        )
    )
    max_paginas: int = field(default_factory=lambda: _env_int("MAX_PAGINAS", 20))
    headless: bool = field(default_factory=lambda: _env_bool("HEADLESS", True))
    # "" = Chromium de Playwright · "msedge" / "chrome" = navegador instalado en el PC
    browser_channel: str = field(default_factory=_canal_por_defecto)

    # --- Scraping ético ---
    delay_min: float = field(default_factory=lambda: _env_float("DELAY_MIN", 2.0))
    delay_max: float = field(default_factory=lambda: _env_float("DELAY_MAX", 5.0))
    max_reintentos: int = field(default_factory=lambda: _env_int("MAX_REINTENTOS", 3))
    timeout_ms: int = field(default_factory=lambda: _env_int("TIMEOUT_MS", 30000))

    # --- LLM ---
    llm_provider: str = field(default_factory=lambda: _env("LLM_PROVIDER", "gemini").lower())
    gemini_api_key: str = field(default_factory=lambda: _env("GEMINI_API_KEY"))
    gemini_model: str = field(default_factory=lambda: _env("GEMINI_MODEL", "gemini-2.5-flash"))
    openai_api_key: str = field(default_factory=lambda: _env("OPENAI_API_KEY"))
    openai_model: str = field(default_factory=lambda: _env("OPENAI_MODEL", "gpt-4o-mini"))

    # --- Telegram ---
    telegram_token: str = field(default_factory=lambda: _env("TELEGRAM_BOT_TOKEN"))
    telegram_chat_id: str = field(default_factory=lambda: _env("TELEGRAM_CHAT_ID"))
    monitor_intervalo_min: int = field(
        default_factory=lambda: _env_int("MONITOR_INTERVALO_MIN", 180)
    )

    # --- Enriquecimiento ---
    enrich_max_resultados: int = field(
        default_factory=lambda: _env_int("ENRICH_MAX_RESULTADOS", 6)
    )

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.output_dir, self.logs_dir, self.session_path.parent):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def selectors_usuario_path(self) -> Path:
        """Copia editable de los selectores en la carpeta de datos (tiene prioridad)."""
        return self.session_path.parent / "config" / "selectors.json"

    def load_selectors(self) -> dict[str, Any]:
        """Carga los selectores CSS del portal (editables sin tocar código)."""
        ruta = self.selectors_usuario_path
        if not ruta.exists() or ruta.resolve() == self.selectors_path.resolve():
            ruta = self.selectors_path
        with open(ruta, encoding="utf-8") as fh:
            return json.load(fh)

    @property
    def credenciales_configuradas(self) -> bool:
        return bool(self.sena_user and self.sena_password)


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
        _settings.ensure_dirs()
    return _settings


def build_settings(**overrides: Any) -> Settings:
    """Settings con valores sobrescritos (los usa la app de escritorio)."""
    s = replace(Settings(), **{k: v for k, v in overrides.items() if v is not None})
    s.ensure_dirs()
    return s
