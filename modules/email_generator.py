"""
Módulo 3 — Generador de Correos Directos.

Genera, para cada vacante, dos variantes de correo en JSON:
  - version_corta  (< 120 palabras): directa, resolución de problemas, disponibilidad inmediata.
  - version_formal (< 180 palabras): corporativa, con enlace al portafolio y alineada a la empresa.

Usa Gemini u OpenAI (según `.env`). Si no hay LLM configurado o la respuesta no cumple
las reglas (longitud, JSON válido), cae a una plantilla local determinista. El módulo
SOLO redacta: nunca envía correos por ti.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from config import Settings
from modules.cv_adapter import ordenar_habilidades, requisitos_vacante
from modules.db import Database
from modules.llm import LLMClient, crear_cliente_opcional
from modules.models import CorreoGenerado, FichaEmpresa, Vacante
from modules.utils import contar_palabras, limpiar, slugify

log = logging.getLogger(__name__)

LIMITE_CORTA = 120
LIMITE_FORMAL = 180

SYSTEM_PROMPT = (
    "Eres un coach de empleabilidad colombiano que redacta correos de postulación para "
    "aprendices SENA. Escribes en español de Colombia, con tono profesional y cercano, sin "
    "clichés ('me apasiona', 'soy proactivo'), sin exagerar ni inventar experiencia. "
    "Respondes únicamente con JSON válido."
)

PLANTILLA_PROMPT = """Redacta dos correos de postulación a un contrato de aprendizaje SENA.

## DATOS DEL APRENDIZ
Nombre: {nombre}
Programa SENA: {programa}
Habilidades técnicas: {habilidades}
Proyecto más relevante: {proyecto}
Disponibilidad: {disponibilidad}
Portafolio: {portafolio}
Contacto: {contacto}

## DATOS DE LA EMPRESA
Razón social: {empresa} — Ciudad: {ciudad}
Sector: {sector}
Problema de negocio que resuelve: {problema}
Qué hace: {resumen}
Tecnologías probables: {tecnologias}
Tareas esperadas del aprendiz: {tareas}
Perfil publicado en la vacante: {perfil}

## REGLAS
- "asunto": máx. 12 palabras; incluye "Contrato de aprendizaje" y el programa.
- "version_corta": MENOS de {lim_corta} palabras. Directa: qué problema concreto de la empresa
  puede ayudar a resolver, una evidencia (proyecto o habilidad) y disponibilidad inmediata.
- "version_formal": MENOS de {lim_formal} palabras. Corporativa: saludo formal, alineación con la
  actividad de la empresa, 2 habilidades relevantes, enlace al portafolio ({portafolio}),
  mención de la hoja de vida adjunta, cierre con datos de contacto.
- Ambas firmadas con el nombre del aprendiz. Sin marcadores tipo [Nombre] ni corchetes.
- No inventes datos que no estén arriba.

Responde SOLO con este JSON:
{{"asunto": "...", "version_corta": "...", "version_formal": "..."}}"""


# =============================================================================
# Construcción de contexto
# =============================================================================
def habilidades_tecnicas(perfil: dict[str, Any]) -> list[str]:
    hab = perfil.get("habilidades", [])
    return list(hab.get("tecnicas", [])) if isinstance(hab, dict) else list(hab)


def programa_corto(programa: str) -> str:
    """'Tecnólogo en Análisis y Desarrollo de Software (ADSO)' → 'ADSO'."""
    m = re.search(r"\(([A-ZÁÉÍÓÚÑ]{2,10})\)", programa)
    if m:
        return m.group(1)
    if len(programa) <= 45:
        return programa
    return programa[:45].rsplit(" ", 1)[0]


def enumerar(items: list[str]) -> str:
    """['a', 'b', 'c'] → 'a, b y c'."""
    items = [i for i in items if i]
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def contexto_prompt(
    perfil: dict[str, Any], vacante: Vacante, ficha: FichaEmpresa | None,
    proyecto_destacado: dict[str, Any] | None = None,
) -> dict[str, str]:
    proyectos = perfil.get("proyectos") or []
    proyecto = proyecto_destacado or (proyectos[0] if proyectos else None)
    proyecto_txt = (
        f"{proyecto.get('nombre', '')}: {proyecto.get('descripcion', '')} "
        f"({', '.join(proyecto.get('tecnologias', []))})"
        if proyecto else "N/D"
    )
    contacto = " | ".join(
        x for x in (perfil.get("email"), perfil.get("telefono"), perfil.get("linkedin")) if x
    )
    # Las habilidades que pide la vacante van primero (el LLM y la plantilla usan las primeras)
    habilidades = ordenar_habilidades(
        habilidades_tecnicas(perfil), requisitos_vacante(vacante, ficha)
    )
    return {
        "nombre": perfil.get("nombre", ""),
        "programa": perfil.get("programa_sena", ""),
        "habilidades": "; ".join(habilidades[:10]),
        "proyecto": proyecto_txt,
        "disponibilidad": perfil.get("disponibilidad", "Inmediata"),
        "portafolio": perfil.get("portafolio") or perfil.get("github") or "",
        "contacto": contacto,
        "empresa": vacante.razon_social,
        "ciudad": vacante.ciudad or "N/D",
        "sector": (ficha.sector if ficha else "") or "N/D",
        "problema": (ficha.problema_negocio if ficha else "") or "N/D",
        "resumen": (ficha.resumen if ficha else "") or "N/D",
        "tecnologias": ", ".join(ficha.tecnologias) if ficha and ficha.tecnologias else "N/D",
        "tareas": ", ".join(ficha.tareas_aprendiz) if ficha and ficha.tareas_aprendiz else "N/D",
        "perfil": (vacante.perfil or "N/D")[:700],
        "lim_corta": str(LIMITE_CORTA),
        "lim_formal": str(LIMITE_FORMAL),
    }


def validar_correo(data: dict[str, Any]) -> list[str]:
    """Devuelve la lista de problemas encontrados (vacía si el correo es válido)."""
    errores: list[str] = []
    for clave in ("asunto", "version_corta", "version_formal"):
        if not isinstance(data.get(clave), str) or not data[clave].strip():
            errores.append(f"falta '{clave}'")
    if errores:
        return errores
    if contar_palabras(data["version_corta"]) >= LIMITE_CORTA:
        errores.append(f"version_corta tiene {contar_palabras(data['version_corta'])} palabras")
    if contar_palabras(data["version_formal"]) >= LIMITE_FORMAL:
        errores.append(f"version_formal tiene {contar_palabras(data['version_formal'])} palabras")
    if "[" in data["version_corta"] + data["version_formal"]:
        errores.append("contiene marcadores entre corchetes")
    return errores


def correo_plantilla(ctx: dict[str, str]) -> dict[str, str]:
    """Correo determinista sin LLM. Siempre respeta los límites de palabras."""
    nombre = ctx["nombre"] or "Aprendiz SENA"
    habilidades = enumerar(ctx["habilidades"].split("; ")[:3])
    problema = ctx["problema"] if ctx["problema"] != "N/D" else "sus procesos tecnológicos"
    problema = problema.rstrip(".")
    primera_tarea = ctx["tareas"].split(", ")[0].lower() if ctx["tareas"] != "N/D" else (
        "el desarrollo y soporte de sus soluciones")
    portafolio = f" Pueden ver mis proyectos en {ctx['portafolio']}." if ctx["portafolio"] else ""
    proyecto = ctx["proyecto"].split(":")[0] if ctx["proyecto"] != "N/D" else ""

    corta = (
        f"Hola, equipo de {ctx['empresa']}:\n\n"
        f"Soy {nombre}, aprendiz del programa {ctx['programa']}. Vi su convocatoria de contrato de "
        f"aprendizaje y puedo aportar desde el primer día en {primera_tarea}, "
        f"trabajando con {habilidades}."
        + (f" En mi proyecto {proyecto} resolví un reto similar." if proyecto else "")
        + f"\n\nTengo disponibilidad {ctx['disponibilidad'].lower()}. Adjunto mi hoja de vida."
        f"{portafolio}\n\nQuedo atento(a),\n{nombre}\n{ctx['contacto']}"
    )
    formal = (
        f"Respetados señores de {ctx['empresa']}:\n\n"
        f"Reciban un cordial saludo. Mi nombre es {nombre} y curso el programa {ctx['programa']} "
        f"en el SENA. Me dirijo a ustedes con el fin de postularme a la convocatoria de contrato "
        f"de aprendizaje publicada para la ciudad de {ctx['ciudad']}.\n\n"
        f"Entiendo que su organización trabaja en {problema.lower()}, y considero que mi formación "
        f"puede contribuir en {primera_tarea}. Cuento con conocimientos en {habilidades}, "
        f"aplicados en proyectos formativos documentados."
        + (f" Mi portafolio está disponible en {ctx['portafolio']}." if ctx["portafolio"] else "")
        + f"\n\nAdjunto mi hoja de vida para su consideración y quedo a disposición para una "
        f"entrevista en el momento que ustedes estimen conveniente.\n\n"
        f"Atentamente,\n{nombre}\n{ctx['contacto']}"
    )
    return {
        "asunto": f"Contrato de aprendizaje {programa_corto(ctx['programa'])} – {nombre}",
        "version_corta": corta,
        "version_formal": formal,
    }


# =============================================================================
# Generador
# =============================================================================
class EmailGenerator:
    def __init__(self, settings: Settings, db: Database, llm: LLMClient | None = None) -> None:
        self.s = settings
        self.db = db
        self.llm = llm

    def generar(
        self, perfil: dict[str, Any], vacante: Vacante,
        proyecto_destacado: dict[str, Any] | None = None,
    ) -> CorreoGenerado:
        ficha = self.db.obtener_ficha(vacante.empresa_key)
        ctx = contexto_prompt(perfil, vacante, ficha, proyecto_destacado)
        data: dict[str, Any] | None = None
        proveedor = "plantilla"

        if self.llm:
            prompt = PLANTILLA_PROMPT.format(**ctx)
            for intento in range(2):
                try:
                    candidato = self.llm.generar_json(prompt, system=SYSTEM_PROMPT)
                except Exception as exc:  # noqa: BLE001
                    log.warning("LLM falló generando correo (%s): %s", vacante.razon_social, exc)
                    break
                errores = validar_correo(candidato)
                if not errores:
                    data, proveedor = candidato, self.llm.nombre
                    break
                log.info("Correo rechazado (%s); reintento %d", "; ".join(errores), intento + 1)
                prompt += (f"\n\nTu respuesta anterior no cumplió: {'; '.join(errores)}. "
                           "Corrígelo y sé más breve.")

        if data is None:
            data = correo_plantilla(ctx)

        return CorreoGenerado(
            vacante_id=vacante.id,
            asunto=limpiar(data["asunto"]),
            version_corta=data["version_corta"].strip(),
            version_formal=data["version_formal"].strip(),
            proveedor=proveedor,
        )

    def guardar(self, correo: CorreoGenerado, vacante: Vacante, carpeta: Path) -> Path:
        self.db.guardar_correo(correo)
        carpeta.mkdir(parents=True, exist_ok=True)
        destino = carpeta / "correos.json"
        payload = correo.to_dict() | {
            "empresa": vacante.razon_social,
            "enlace_vacante": vacante.enlace,
            "palabras": {
                "version_corta": contar_palabras(correo.version_corta),
                "version_formal": contar_palabras(correo.version_formal),
            },
        }
        destino.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return destino


def carpeta_vacante(settings: Settings, vacante: Vacante) -> Path:
    return settings.output_dir / f"{slugify(vacante.razon_social, 40)}_{vacante.id[-8:]}"


def crear_generador(settings: Settings, db: Database) -> EmailGenerator:
    return EmailGenerator(settings, db, crear_cliente_opcional(settings))
