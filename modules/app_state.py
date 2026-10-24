"""
Estado persistente de la app de escritorio (sin dependencias gráficas, para poder probarlo).

- Ajustes no secretos → <carpeta de datos>/ajustes.json
- Secretos (contraseña SGVA, claves de API, token de Telegram) → almacén de credenciales
  del sistema operativo vía `keyring`:
      Windows: Administrador de credenciales (cifrado con tu usuario de Windows)
      macOS:   Llavero · Linux: Secret Service
  Si no hay almacén disponible, los secretos solo se guardan en memoria durante la sesión.
- Perfil del aprendiz → <carpeta de datos>/data/perfil_aprendiz.json
"""

from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any

from config import DATA_HOME, Settings, build_settings

log = logging.getLogger(__name__)

SERVICIO_KEYRING = "SGVA-Matchmaker"
SECRETOS = ("sena_password", "gemini_api_key", "openai_api_key", "telegram_token")
VERSION_AVISO = 1  # súbelo si cambia el texto del descargo: se vuelve a pedir aceptación

PROGRAMAS_SENA = [
    "Análisis y Desarrollo de Software",
    "Programación de Software",
    "Desarrollo de Videojuegos",
    "Gestión de Redes de Datos",
    "Mantenimiento de Equipos de Cómputo",
    "Producción de Multimedia",
    "Animación Digital",
    "Gestión Empresarial",
    "Gestión Administrativa",
    "Contabilidad y Finanzas",
    "Gestión del Talento Humano",
    "Asistencia Administrativa",
]

PALABRAS_POR_PROGRAMA = {
    "Análisis y Desarrollo de Software": "ADSO,software,desarrollo,programación,sistemas,desarrollador",
    "Programación de Software": "software,programación,desarrollo,sistemas,desarrollador",
    "Gestión de Redes de Datos": "redes,telecomunicaciones,infraestructura,sistemas,soporte",
    "Mantenimiento de Equipos de Cómputo": "mantenimiento,soporte,equipos de cómputo,sistemas,hardware",
}

_STOP = {"de", "del", "la", "el", "y", "en", "para", "los", "las"}


def palabras_sugeridas(programa: str) -> str:
    if programa in PALABRAS_POR_PROGRAMA:
        return PALABRAS_POR_PROGRAMA[programa]
    palabras = [p for p in programa.lower().replace(",", " ").split() if p not in _STOP and len(p) > 3]
    return ",".join(dict.fromkeys(palabras))


# =============================================================================
# Ajustes
# =============================================================================
@dataclass
class AjustesApp:
    sena_user: str = ""
    sgva_vacantes_url: str = ""
    programa_formacion: str = "Análisis y Desarrollo de Software"
    palabras_clave: str = PALABRAS_POR_PROGRAMA["Análisis y Desarrollo de Software"]
    navegador: str = "auto"  # auto | msedge | chrome | brave | vivaldi (modules/navegadores.py)
    mostrar_navegador: bool = False
    llm_provider: str = "ninguno"  # ninguno | gemini | openai
    telegram_chat_id: str = ""
    recordar_secretos: bool = True
    aviso_aceptado: int = 0
    # Secretos: viven en memoria; se persisten en keyring, nunca en ajustes.json
    sena_password: str = field(default="", repr=False)
    gemini_api_key: str = field(default="", repr=False)
    openai_api_key: str = field(default="", repr=False)
    telegram_token: str = field(default="", repr=False)

    @staticmethod
    def ruta(home: Path = DATA_HOME) -> Path:
        return home / "ajustes.json"

    @classmethod
    def cargar(cls, home: Path = DATA_HOME, almacen: AlmacenSecretos | None = None) -> AjustesApp:
        datos: dict[str, Any] = {}
        ruta = cls.ruta(home)
        if ruta.exists():
            try:
                datos = json.loads(ruta.read_text("utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                log.warning("ajustes.json ilegible (%s); se usan valores por defecto.", exc)
        validos = {f.name for f in fields(cls)} - set(SECRETOS)
        ajustes = cls(**{k: v for k, v in datos.items() if k in validos})
        almacen = almacen or AlmacenSecretos()
        for nombre in SECRETOS:
            setattr(ajustes, nombre, almacen.leer(nombre))
        return ajustes

    def guardar(self, home: Path = DATA_HOME, almacen: AlmacenSecretos | None = None) -> bool:
        """Guarda ajustes y secretos. Devuelve False si los secretos no pudieron persistirse."""
        home.mkdir(parents=True, exist_ok=True)
        publicos = {k: v for k, v in asdict(self).items() if k not in SECRETOS}
        self.ruta(home).write_text(json.dumps(publicos, ensure_ascii=False, indent=2), "utf-8")
        almacen = almacen or AlmacenSecretos()
        ok = True
        for nombre in SECRETOS:
            valor = getattr(self, nombre) if self.recordar_secretos else ""
            ok &= almacen.escribir(nombre, valor)
        return ok

    def a_settings(self) -> Settings:
        return build_settings(
            sena_user=self.sena_user.strip(),
            sena_password=self.sena_password,
            sgva_vacantes_url=self.sgva_vacantes_url.strip(),
            programa_formacion=self.programa_formacion.strip(),
            palabras_clave_area=[p.strip() for p in self.palabras_clave.split(",") if p.strip()],
            browser_channel=self.navegador,
            headless=not self.mostrar_navegador,
            llm_provider=self.llm_provider,
            gemini_api_key=self.gemini_api_key.strip(),
            openai_api_key=self.openai_api_key.strip(),
            telegram_token=self.telegram_token.strip(),
            telegram_chat_id=self.telegram_chat_id.strip(),
        )


class AlmacenSecretos:
    """Envoltorio de `keyring` que nunca lanza excepciones."""

    def __init__(self) -> None:
        self.disponible = False
        self._memoria: dict[str, str] = {}
        try:
            import keyring
            from keyring.backends import fail

            self._kr = keyring
            self.disponible = not isinstance(keyring.get_keyring(), fail.Keyring)
        except Exception as exc:  # noqa: BLE001
            log.warning("Almacén de credenciales no disponible: %s", exc)

    @property
    def nombre(self) -> str:
        if not self.disponible:
            return "solo en memoria (no se recordará al cerrar)"
        return type(self._kr.get_keyring()).__name__

    def leer(self, nombre: str) -> str:
        if self.disponible:
            try:
                return self._kr.get_password(SERVICIO_KEYRING, nombre) or ""
            except Exception as exc:  # noqa: BLE001
                log.warning("No se pudo leer '%s' del almacén: %s", nombre, exc)
        return self._memoria.get(nombre, "")

    def escribir(self, nombre: str, valor: str) -> bool:
        self._memoria[nombre] = valor
        if not self.disponible:
            return not valor
        try:
            if valor:
                self._kr.set_password(SERVICIO_KEYRING, nombre, valor)
            else:
                try:
                    self._kr.delete_password(SERVICIO_KEYRING, nombre)
                except Exception:  # noqa: BLE001 - no existía
                    pass
            return True
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo guardar '%s' en el almacén: %s", nombre, exc)
            return False


# =============================================================================
# Perfil ↔ formulario (listas de texto, una entrada por línea)
# =============================================================================
def lineas(texto: str) -> list[str]:
    return [ln.strip(" -•\t") for ln in texto.splitlines() if ln.strip(" -•\t")]


def lista_comas(texto: str) -> list[str]:
    """'Python, React; Git' → ['Python', 'React', 'Git'] (respeta paréntesis: 'Python (Django, FastAPI)')."""
    partes, actual, nivel = [], "", 0
    for ch in texto.replace("\n", ","):
        if ch == "(":
            nivel += 1
        elif ch == ")":
            nivel = max(0, nivel - 1)
        if ch in ",;" and nivel == 0:
            partes.append(actual)
            actual = ""
        else:
            actual += ch
    partes.append(actual)
    return [p.strip() for p in partes if p.strip()]


def parse_educacion(texto: str) -> list[dict[str, str]]:
    """Cada línea: 'Título | Institución | Periodo'."""
    salida = []
    for ln in lineas(texto):
        c = [x.strip() for x in ln.split("|")] + ["", ""]
        salida.append({"titulo": c[0], "institucion": c[1], "periodo": c[2]})
    return salida


def format_educacion(items: list[dict[str, Any]]) -> str:
    return "\n".join(
        " | ".join(x for x in (e.get("titulo", ""), e.get("institucion", ""), e.get("periodo", "")))
        .rstrip(" |") for e in items
    )


def parse_experiencia(texto: str) -> list[dict[str, Any]]:
    """Cada línea: 'Cargo | Empresa | Periodo | logro 1; logro 2'."""
    salida = []
    for ln in lineas(texto):
        c = [x.strip() for x in ln.split("|")] + ["", "", ""]
        salida.append({
            "cargo": c[0], "empresa": c[1], "periodo": c[2],
            "logros": [x.strip() for x in c[3].split(";") if x.strip()],
        })
    return salida


def format_experiencia(items: list[dict[str, Any]]) -> str:
    filas = []
    for e in items:
        partes = [e.get("cargo", ""), e.get("empresa", ""), e.get("periodo", ""),
                  "; ".join(e.get("logros", []))]
        filas.append(" | ".join(partes).rstrip(" |"))
    return "\n".join(filas)


def perfil_vacio() -> dict[str, Any]:
    return {
        "nombre": "", "titulo": "", "email": "", "telefono": "", "ciudad": "",
        "linkedin": "", "github": "", "portafolio": "", "programa_sena": "",
        "disponibilidad": "Inmediata", "resumen": "",
        "habilidades": {"tecnicas": [], "blandas": []},
        "proyectos": [], "experiencia": [], "educacion": [], "certificaciones": [], "idiomas": [],
    }


def cargar_perfil_o_vacio(ruta: Path) -> dict[str, Any]:
    base = perfil_vacio()
    if ruta.exists():
        try:
            base.update(json.loads(ruta.read_text("utf-8")))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("Perfil ilegible (%s); se empieza uno nuevo.", exc)
    if not isinstance(base.get("habilidades"), dict):
        base["habilidades"] = {"tecnicas": list(base.get("habilidades") or []), "blandas": []}
    return base


def problemas_perfil(perfil: dict[str, Any]) -> list[str]:
    """Lo mínimo para generar una hoja de vida útil."""
    faltan = []
    if not perfil.get("nombre", "").strip():
        faltan.append("tu nombre")
    if not perfil.get("email", "").strip():
        faltan.append("tu correo")
    if not perfil.get("programa_sena", "").strip():
        faltan.append("tu programa SENA")
    if not perfil.get("habilidades", {}).get("tecnicas"):
        faltan.append("al menos una habilidad técnica")
    return faltan


def guardar_perfil(perfil: dict[str, Any], ruta: Path) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(json.dumps(perfil, ensure_ascii=False, indent=2), "utf-8")
