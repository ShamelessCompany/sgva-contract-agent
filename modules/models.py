"""Modelos de dominio tipados que circulan entre los módulos del pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from modules.utils import normalizar, stable_hash


@dataclass
class Vacante:
    """Una convocatoria de contrato de aprendizaje extraída del SGVA."""

    razon_social: str
    nit: str = ""
    ciudad: str = ""
    fecha_limite: str = ""  # ISO 8601 (AAAA-MM-DD) cuando se puede interpretar
    perfil: str = ""
    enlace: str = ""
    programa: str = ""
    id_portal: str = ""  # ID propio del SGVA si la tabla lo expone
    id: str = ""  # ID estable usado en SQLite

    def __post_init__(self) -> None:
        if not self.id:
            self.id = self.calcular_id()

    def calcular_id(self) -> str:
        """El ID del portal es la fuente de verdad; si no existe, se usa un hash estable."""
        if self.id_portal:
            return f"sgva-{normalizar(self.id_portal).replace(' ', '')}"
        return "h-" + stable_hash(self.nit or self.razon_social, self.ciudad, self.perfil[:200])

    @property
    def empresa_key(self) -> str:
        """Clave de empresa: NIT sin dígito de verificación, o la razón social normalizada."""
        nit = "".join(ch for ch in self.nit.split("-")[0] if ch.isdigit())
        return nit or normalizar(self.razon_social)

    @property
    def content_hash(self) -> str:
        """Huella del contenido; cambia si el SGVA edita la vacante."""
        return stable_hash(self.razon_social, self.ciudad, self.fecha_limite, self.perfil)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class FichaEmpresa:
    """Ficha técnica de una empresa construida por el enriquecedor."""

    empresa_key: str
    razon_social: str
    nit: str = ""
    sitio_web: str = ""
    sector: str = ""
    problema_negocio: str = ""
    resumen: str = ""
    tecnologias: list[str] = field(default_factory=list)
    tareas_aprendiz: list[str] = field(default_factory=list)
    fuentes: list[str] = field(default_factory=list)
    metodo: str = "heuristico"  # "heuristico" | "llm"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CorreoGenerado:
    """Par de variantes de correo para una vacante."""

    vacante_id: str
    asunto: str
    version_corta: str
    version_formal: str
    proveedor: str = "plantilla"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
