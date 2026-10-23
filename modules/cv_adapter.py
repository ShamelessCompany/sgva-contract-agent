"""
Módulo 4 — Adaptador de Hoja de Vida ATS.

1. Lee el perfil maestro desde `data/perfil_aprendiz.json`.
2. Extrae los requisitos de la vacante (perfil publicado + tecnologías/tareas de la ficha).
3. Calcula la afinidad de cada proyecto y habilidad, y los reordena por relevancia.
4. Genera un Markdown de UNA columna, sin tablas, imágenes ni íconos (amigable con ATS).
5. Compila a PDF limpio con WeasyPrint; si no está disponible, intenta con `pandoc`.

No inventa experiencia: solo reordena y resalta lo que ya está en tu perfil maestro.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from modules.models import FichaEmpresa, Vacante
from modules.utils import normalizar

log = logging.getLogger(__name__)

# Vocabulario canónico: término mostrado → sinónimos (normalizados) a buscar en el texto.
VOCABULARIO: dict[str, tuple[str, ...]] = {
    "Python": ("python",),
    "Java": ("java", "spring"),
    "JavaScript": ("javascript", "js", "ecmascript"),
    "TypeScript": ("typescript",),
    "HTML/CSS": ("html", "css", "maquetacion"),
    "React": ("react", "reactjs"),
    "Angular": ("angular",),
    "Vue.js": ("vue", "vuejs"),
    "Node.js": ("node", "nodejs", "express"),
    "PHP": ("php",),
    "Laravel": ("laravel",),
    "Django": ("django",),
    "Flask/FastAPI": ("flask", "fastapi"),
    "C#/.NET": ("c#", ".net", "dotnet", "asp.net"),
    "SQL": ("sql", "base de datos", "bases de datos", "consultas"),
    "MySQL": ("mysql", "mariadb"),
    "PostgreSQL": ("postgres", "postgresql"),
    "SQL Server": ("sql server",),
    "MongoDB": ("mongo", "mongodb", "nosql"),
    "Git": ("git", "github", "gitlab", "control de versiones"),
    "Docker": ("docker", "contenedores"),
    "Linux": ("linux", "ubuntu", "bash"),
    "APIs REST": ("api", "apis", "rest", "servicios web", "web services"),
    "Pruebas de software": ("pruebas", "testing", "qa", "pytest", "junit", "calidad de software"),
    "Scrum/Ágil": ("scrum", "agil", "agile", "kanban", "metodologias agiles"),
    "UML/Requerimientos": ("uml", "requerimientos", "levantamiento de requisitos", "casos de uso"),
    "Power BI": ("power bi", "powerbi", "tableros"),
    "Excel": ("excel",),
    "WordPress": ("wordpress",),
    "Soporte técnico": ("soporte", "mesa de ayuda", "help desk", "mantenimiento de equipos"),
    "Redes": ("redes de datos", "tcp/ip", "cableado", "networking"),
    "Cloud": ("aws", "azure", "gcp", "nube", "cloud"),
    "Flutter/Móvil": ("flutter", "android", "kotlin", "movil", "apps moviles"),
    "Documentación técnica": ("documentacion", "manuales"),
}


# Si el aprendiz domina el término de la izquierda, también cubre el de la derecha.
IMPLICA: dict[str, tuple[str, ...]] = {
    "MySQL": ("SQL",), "PostgreSQL": ("SQL",), "SQL Server": ("SQL",),
    "Django": ("Python",), "Flask/FastAPI": ("Python", "APIs REST"),
    "TypeScript": ("JavaScript",), "React": ("JavaScript", "HTML/CSS"),
    "Angular": ("TypeScript", "JavaScript"), "Vue.js": ("JavaScript",),
    "Node.js": ("JavaScript",), "Laravel": ("PHP",),
}


def expandir(terminos: set[str]) -> set[str]:
    """Agrega los términos implícitos (p. ej. PostgreSQL ⇒ SQL)."""
    resultado = set(terminos)
    for t in terminos:
        resultado.update(IMPLICA.get(t, ()))
    return resultado


@dataclass
class Afinidad:
    puntaje: float  # 0–100
    requisitos: list[str] = field(default_factory=list)
    coincidencias: list[str] = field(default_factory=list)
    faltantes: list[str] = field(default_factory=list)


# =============================================================================
# Análisis de requisitos
# =============================================================================
def _contiene(texto_norm: str, sinonimo: str) -> bool:
    patron = r"(?<![a-z0-9])" + re.escape(sinonimo) + r"(?![a-z0-9])"
    return re.search(patron, texto_norm) is not None


def terminos_en(texto: str) -> set[str]:
    """Términos canónicos del vocabulario presentes en un texto."""
    t = normalizar(texto)
    return {canon for canon, sins in VOCABULARIO.items() if any(_contiene(t, s) for s in sins)}


def requisitos_vacante(vacante: Vacante, ficha: FichaEmpresa | None) -> set[str]:
    """Requisitos "duros": lo que pide el perfil publicado en la vacante.

    Las tecnologías de la ficha empresarial son inferidas, así que solo se usan como
    requisito cuando el perfil publicado es demasiado escueto (< 3 términos).
    """
    duros = terminos_en(vacante.perfil)
    if len(duros) < 3:
        duros |= requisitos_contexto(ficha)
    return duros


def requisitos_contexto(ficha: FichaEmpresa | None) -> set[str]:
    """Requisitos "blandos": tecnologías y tareas probables según la ficha de la empresa."""
    if not ficha:
        return set()
    return terminos_en(" ".join(ficha.tecnologias) + " " + " ".join(ficha.tareas_aprendiz))


def texto_proyecto(p: dict[str, Any]) -> str:
    return " ".join([
        p.get("nombre", ""), p.get("descripcion", ""), " ".join(p.get("tecnologias", [])),
        " ".join(p.get("logros", [])),
    ])


def puntuar_proyecto(proyecto: dict[str, Any], requisitos: set[str],
                     contexto: set[str] | None = None) -> float:
    """Tecnologías declaradas que piden la vacante (×2), mencionadas en la prosa (×1)
    y que encajan con el contexto de la empresa (×0.5)."""
    declaradas = expandir(terminos_en(" ".join(proyecto.get("tecnologias", []))))
    en_texto = expandir(terminos_en(texto_proyecto(proyecto))) - declaradas
    contexto = (contexto or set()) - requisitos
    return (2.0 * len(declaradas & requisitos) + 1.0 * len(en_texto & requisitos)
            + 0.5 * len((declaradas | en_texto) & contexto))


def ordenar_proyectos(proyectos: list[dict[str, Any]], requisitos: set[str],
                      contexto: set[str] | None = None) -> list[dict[str, Any]]:
    # sorted es estable: a igual puntaje se conserva el orden del perfil maestro
    return sorted(proyectos, key=lambda p: puntuar_proyecto(p, requisitos, contexto),
                  reverse=True)


def ordenar_habilidades(habilidades: list[str], requisitos: set[str]) -> list[str]:
    def relevante(h: str) -> bool:
        return bool(expandir(terminos_en(h)) & requisitos)
    return sorted(habilidades, key=lambda h: not relevante(h))


def calcular_afinidad(perfil: dict[str, Any], requisitos: set[str]) -> Afinidad:
    hab = perfil.get("habilidades", {})
    tecnicas = hab.get("tecnicas", []) if isinstance(hab, dict) else list(hab)
    texto_total = " ".join(tecnicas) + " " + " ".join(
        texto_proyecto(p) for p in perfil.get("proyectos", [])
    ) + " " + " ".join(perfil.get("certificaciones", []))
    del_aprendiz = expandir(terminos_en(texto_total))
    coinciden = sorted(requisitos & del_aprendiz)
    faltan = sorted(requisitos - del_aprendiz)
    puntaje = round(100 * len(coinciden) / len(requisitos), 1) if requisitos else 0.0
    return Afinidad(puntaje, sorted(requisitos), coinciden, faltan)


# =============================================================================
# Render Markdown ATS
# =============================================================================
def _linea_contacto(perfil: dict[str, Any]) -> str:
    campos = ("ciudad", "telefono", "email", "linkedin", "github", "portafolio")
    return " | ".join(str(perfil[c]) for c in campos if perfil.get(c))


def resumen_dirigido(perfil: dict[str, Any], vacante: Vacante, ficha: FichaEmpresa | None,
                     afinidad: Afinidad) -> str:
    base = perfil.get("resumen", "").strip()
    fuertes = ", ".join(afinidad.coincidencias[:4])
    sector = ficha.sector.lower() if ficha and ficha.sector and ficha.sector != "No determinado" else ""
    extra = ""
    if fuertes:
        extra = f" Experiencia práctica en {fuertes}"
        extra += f", con interés en aportar al sector de {sector}." if sector else "."
    disp = perfil.get("disponibilidad")
    if disp:
        extra += f" Disponibilidad: {disp.lower()}."
    return (base + extra).strip()


def generar_markdown(perfil: dict[str, Any], vacante: Vacante,
                     ficha: FichaEmpresa | None) -> tuple[str, Afinidad]:
    req = requisitos_vacante(vacante, ficha)
    afinidad = calcular_afinidad(perfil, req)
    hab = perfil.get("habilidades", {})
    tecnicas = hab.get("tecnicas", []) if isinstance(hab, dict) else list(hab)
    blandas = hab.get("blandas", []) if isinstance(hab, dict) else []

    md: list[str] = [f"# {perfil.get('nombre', '')}", ""]
    titulo = perfil.get("titulo") or f"Aprendiz {perfil.get('programa_sena', '')}"
    md += [f"**{titulo}**", "", _linea_contacto(perfil), ""]

    md += ["## Perfil profesional", "", resumen_dirigido(perfil, vacante, ficha, afinidad), ""]

    if tecnicas:
        md += ["## Habilidades técnicas", "", ", ".join(ordenar_habilidades(tecnicas, req)), ""]
    if blandas:
        md += ["## Habilidades blandas", "", ", ".join(blandas), ""]

    proyectos = ordenar_proyectos(perfil.get("proyectos", []), req, requisitos_contexto(ficha))
    if proyectos:
        md += ["## Proyectos", ""]
        for p in proyectos:
            md += [f"### {p.get('nombre', '')}", ""]
            if p.get("descripcion"):
                md += [p["descripcion"], ""]
            if p.get("tecnologias"):
                md += [f"Tecnologías: {', '.join(p['tecnologias'])}", ""]
            for logro in p.get("logros", []):
                md.append(f"- {logro}")
            if p.get("logros"):
                md.append("")
            if p.get("enlace"):
                md += [f"Enlace: {p['enlace']}", ""]

    if perfil.get("experiencia"):
        md += ["## Experiencia", ""]
        for e in perfil["experiencia"]:
            md += [f"### {e.get('cargo', '')} — {e.get('empresa', '')}", ""]
            if e.get("periodo"):
                md += [e["periodo"], ""]
            for logro in e.get("logros", []):
                md.append(f"- {logro}")
            md.append("")

    md += ["## Formación", ""]
    for ed in perfil.get("educacion", []):
        linea = f"- {ed.get('titulo', '')}, {ed.get('institucion', '')}"
        if ed.get("periodo"):
            linea += f" ({ed['periodo']})"
        md.append(linea)
    md.append("")

    if perfil.get("certificaciones"):
        md += ["## Certificaciones", ""] + [f"- {c}" for c in perfil["certificaciones"]] + [""]
    if perfil.get("idiomas"):
        md += ["## Idiomas", ""] + [f"- {i}" for i in perfil["idiomas"]] + [""]

    texto = "\n".join(md).strip() + "\n"
    return re.sub(r"\n{3,}", "\n\n", texto), afinidad


# =============================================================================
# PDF
# =============================================================================
CSS_ATS = """
@page { size: Letter; margin: 1.8cm 2cm; }
body { font-family: "Liberation Sans", Arial, Helvetica, sans-serif; font-size: 10.5pt;
       line-height: 1.38; color: #111; }
h1 { font-size: 20pt; margin: 0 0 2pt 0; }
h2 { font-size: 12pt; text-transform: uppercase; letter-spacing: .5pt; margin: 14pt 0 4pt;
     padding-bottom: 2pt; border-bottom: 1px solid #999; }
h3 { font-size: 11pt; margin: 8pt 0 2pt; }
p { margin: 0 0 5pt; } ul { margin: 0 0 6pt 16pt; padding: 0; } li { margin-bottom: 2pt; }
a { color: #111; text-decoration: none; }
"""


def html_cv(texto_md: str) -> str:
    import markdown as md_lib

    cuerpo = md_lib.markdown(texto_md, extensions=["sane_lists"])
    return (f"<!doctype html><html lang='es'><head><meta charset='utf-8'>"
            f"<style>{CSS_ATS}</style></head><body>{cuerpo}</body></html>")


class RenderizadorPDF:
    """Convierte HTML a PDF con el navegador (Edge/Chrome/Chromium) vía Playwright.

    No necesita GTK/Pango, así que es el motor que usa la app de escritorio en Windows.
    Reutiliza un único navegador mientras esté abierto: úsalo con `with`.
    """

    def __init__(self, canal: str = "") -> None:
        self.canal = canal
        self._pw: Any = None
        self._browser: Any = None

    def __enter__(self) -> RenderizadorPDF:
        return self

    def __exit__(self, *exc: object) -> None:
        self.cerrar()

    def _asegurar(self) -> None:
        if self._browser is not None:
            return
        from playwright.sync_api import sync_playwright

        self._pw = sync_playwright().start()
        candidatos = ([self.canal] if self.canal else []) + (["chrome"] if self.canal == "msedge" else [])
        for canal in candidatos + [None]:
            try:
                self._browser = self._pw.chromium.launch(channel=canal, headless=True)
                return
            except Exception as exc:  # noqa: BLE001
                log.debug("PDF: canal %s no disponible (%s)", canal or "chromium", exc)
        self.cerrar()
        raise RuntimeError("No hay navegador disponible para generar el PDF")

    def render(self, html: str, destino: Path) -> Path:
        self._asegurar()
        pagina = self._browser.new_page()
        try:
            pagina.set_content(html, wait_until="load")
            pagina.pdf(path=str(destino), prefer_css_page_size=True, print_background=False)
        finally:
            pagina.close()
        return destino

    def cerrar(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:  # noqa: BLE001
                pass
            self._browser = None
        if self._pw is not None:
            self._pw.stop()
            self._pw = None


def markdown_a_pdf(md_path: Path, pdf_path: Path | None = None,
                   renderizador: RenderizadorPDF | None = None, canal: str = "") -> Path | None:
    """Compila Markdown → PDF probando, en orden: WeasyPrint, el navegador (Playwright)
    y pandoc. Devuelve la ruta del PDF o None si ningún motor está disponible."""
    pdf_path = pdf_path or md_path.with_suffix(".pdf")
    html = html_cv(md_path.read_text(encoding="utf-8"))

    try:
        from weasyprint import HTML

        HTML(string=html).write_pdf(str(pdf_path))
        return pdf_path
    except (ImportError, OSError) as exc:
        log.debug("WeasyPrint no disponible (%s); probando con el navegador.", exc)

    try:
        if renderizador is not None:
            return renderizador.render(html, pdf_path)
        with RenderizadorPDF(canal) as r:
            return r.render(html, pdf_path)
    except Exception as exc:  # noqa: BLE001
        log.debug("PDF con navegador falló (%s); probando pandoc.", exc)

    if shutil.which("pandoc"):
        for motor in ("typst", "wkhtmltopdf", "xelatex"):
            if shutil.which(motor):
                r = subprocess.run(
                    ["pandoc", str(md_path), "-o", str(pdf_path), f"--pdf-engine={motor}"],
                    capture_output=True, text=True,
                )
                if r.returncode == 0:
                    return pdf_path
    log.warning(
        "No se pudo generar el PDF. Instala Microsoft Edge/Chrome, WeasyPrint "
        "(pip install weasyprint) o ejecuta: pandoc %s -o %s --pdf-engine=typst", md_path, pdf_path,
    )
    return None


# =============================================================================
# API pública
# =============================================================================
def cargar_perfil(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(
            f"No existe {path}. Completa tu perfil (en la app: pestaña «Mi perfil»; en la "
            "terminal: copia data/perfil_aprendiz.example.json a data/perfil_aprendiz.json)."
        )
    return json.loads(path.read_text(encoding="utf-8"))


def adaptar_cv(perfil: dict[str, Any], vacante: Vacante, ficha: FichaEmpresa | None,
               carpeta: Path, pdf: bool = True,
               renderizador: RenderizadorPDF | None = None) -> dict[str, Any]:
    """Genera CV.md (+ CV.pdf) y analisis.json en `carpeta`. Devuelve un resumen."""
    carpeta.mkdir(parents=True, exist_ok=True)
    texto, afinidad = generar_markdown(perfil, vacante, ficha)
    md_path = carpeta / "hoja_de_vida.md"
    md_path.write_text(texto, encoding="utf-8")
    pdf_path = markdown_a_pdf(md_path, renderizador=renderizador) if pdf else None
    proyectos = ordenar_proyectos(perfil.get("proyectos", []),
                                  requisitos_vacante(vacante, ficha), requisitos_contexto(ficha))
    analisis = {
        "empresa": vacante.razon_social,
        "afinidad": afinidad.puntaje,
        "requisitos_detectados": afinidad.requisitos,
        "coincidencias": afinidad.coincidencias,
        "brechas_a_reforzar": afinidad.faltantes,
        "orden_proyectos": [p.get("nombre") for p in proyectos],
    }
    (carpeta / "analisis.json").write_text(
        json.dumps(analisis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return {"markdown": md_path, "pdf": pdf_path, "afinidad": afinidad,
            "proyecto_top": proyectos[0] if proyectos else None}
