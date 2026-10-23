"""
Módulo 2 — Investigador Empresarial.

Para cada empresa con vacantes activas construye una ficha técnica:
  1. Sitio web oficial o perfil comercial (búsqueda DuckDuckGo vía `ddgs`).
  2. Sector económico y problema de negocio que resuelve.
  3. Tecnologías probables y tareas esperadas para el aprendiz.

Estrategia en capas (cada una es opcional y se degrada con elegancia):
  a) Búsqueda web pública → títulos, snippets y URLs.
  b) Lectura ligera de la portada del sitio oficial → meta description + huellas técnicas
     (WordPress, React, Shopify...) detectadas en el HTML. Una sola petición por empresa.
  c) Si hay LLM configurado, sintetiza la ficha a partir SOLO de esa evidencia.
     Si no, se usa un clasificador heurístico por palabras clave.

Todas las consultas respetan retardos aleatorios de 2–5 s.
"""

from __future__ import annotations

import logging
import re
from typing import Any
from urllib.parse import urlparse

import requests

from config import Settings
from modules.db import Database
from modules.llm import LLMClient, crear_cliente_opcional
from modules.models import FichaEmpresa, Vacante
from modules.utils import (
    dormir,
    limpiar,
    normalizar,
    polite_delay,
    random_user_agent,
    verificar_cancelacion,
)

log = logging.getLogger(__name__)

# Dominios que NO son el sitio oficial, pero sirven como "perfil comercial".
DIRECTORIOS = (
    "einforma", "informacolombia", "dateas", "emis.com", "dnb.com", "rues.org",
    "empresite", "guiaempresas", "paginasamarillas", "datacreditoempresas", "opencorporates",
    "linkedin.com", "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "computrabajo", "elempleo", "indeed", "glassdoor", "magneto365", "wikipedia.org",
    "sena.edu.co", "gov.co", "tiktok.com", "infobel", "cylex", "zoominfo", "crunchbase",
    "registronit", "nit.com.co", "empresas.net.co", "colombiaempresas", "lasempresas",
)
PERFILES_PREFERIDOS = ("linkedin.com/company", "einforma", "informacolombia", "rues.org")

# Clasificador sectorial: palabras clave → (sector, problema, tecnologías, tareas)
SECTORES: list[dict[str, Any]] = [
    {
        "sector": "Tecnología y desarrollo de software",
        "claves": ("software", "desarrollo web", "aplicaciones", "tecnologia",
                   "tecnologias de la informacion", "cloud",
                   "nube", "saas", "digital", "transformacion digital", "consultoria ti", "erp"),
        "problema": "Digitalizar y automatizar procesos de sus clientes mediante soluciones de software.",
        "tecnologias": ["Git", "SQL", "APIs REST", "JavaScript/TypeScript", "Python o Java", "Docker"],
        "tareas": ["Desarrollo y mantenimiento de módulos web", "Pruebas y corrección de errores",
                   "Documentación técnica", "Consumo e integración de APIs"],
    },
    {
        "sector": "Servicios financieros y seguros",
        "claves": ("banco", "financier", "credito", "seguros", "fintech", "cooperativa",
                   "fondo de empleados", "pagos", "inversion", "cartera"),
        "problema": "Gestionar riesgo, cartera y operaciones financieras de forma segura y regulada.",
        "tecnologias": ["SQL Server/Oracle", "Java o .NET", "Power BI", "APIs seguras", "Excel avanzado"],
        "tareas": ["Soporte a aplicativos internos", "Consultas y reportes SQL",
                   "Automatización de reportes", "Pruebas funcionales"],
    },
    {
        "sector": "Salud",
        "claves": ("salud", "clinica", "hospital", "ips", "eps", "laboratorio", "medic",
                   "odontolog", "farmac", "droguer"),
        "problema": "Prestar servicios de salud con trazabilidad de pacientes y cumplimiento normativo.",
        "tecnologias": ["Sistemas HIS/historia clínica", "SQL", "Interoperabilidad (HL7/FHIR)", "Power BI"],
        "tareas": ["Soporte a usuarios y sistemas de información", "Reportes y RIPS",
                   "Mantenimiento de bases de datos", "Mesa de ayuda"],
    },
    {
        "sector": "Educación",
        "claves": ("colegio", "universidad", "educacion", "institucion educativa", "academia",
                   "escuela", "e-learning", "fundacion universitaria"),
        "problema": "Gestionar procesos académicos y experiencias de aprendizaje, cada vez más digitales.",
        "tecnologias": ["Moodle/LMS", "PHP", "WordPress", "Google Workspace", "SQL"],
        "tareas": ["Soporte de plataformas académicas", "Desarrollo web institucional",
                   "Gestión de usuarios y aulas virtuales"],
    },
    {
        "sector": "Comercio y retail",
        "claves": ("comercializadora", "tienda", "almacen", "distribuidora", "retail", "ventas",
                   "supermercado", "e-commerce", "comercio", "mayorista"),
        "problema": "Vender y abastecer eficientemente, controlando inventario y canales de venta.",
        "tecnologias": ["ERP/POS", "Shopify/WooCommerce", "SQL", "Excel/Power BI", "APIs de pago"],
        "tareas": ["Soporte a sistemas POS/ERP", "Mantenimiento de tienda en línea",
                   "Reportes de inventario y ventas"],
    },
    {
        "sector": "Manufactura e industria",
        "claves": ("industria", "manufactur", "fabrica", "planta", "produccion", "metalmecanic",
                   "plastico", "textil", "alimentos", "confeccion", "quimic"),
        "problema": "Producir con calidad y eficiencia, controlando costos y trazabilidad de planta.",
        "tecnologias": ["ERP (SAP/Siesa)", "SQL", "Power BI", "Automatización con Python", "IoT"],
        "tareas": ["Soporte a sistemas de producción", "Automatización de reportes",
                   "Inventario de equipos y redes"],
    },
    {
        "sector": "Construcción e inmobiliario",
        "claves": ("construc", "constructora", "inmobiliari", "arquitect", "obra", "ingenieria civil",
                   "vivienda", "proyectos inmobiliarios"),
        "problema": "Planear y ejecutar obras y proyectos inmobiliarios controlando presupuesto y tiempos.",
        "tecnologias": ["ERP de obra", "Excel/Power BI", "CRM inmobiliario", "WordPress"],
        "tareas": ["Soporte de sistemas y equipos", "Sitio web y CRM comercial", "Reportes de proyecto"],
    },
    {
        "sector": "Logística y transporte",
        "claves": ("logistic", "transporte", "carga", "mensajeria", "courier", "bodega",
                   "almacenamiento", "flota", "envios"),
        "problema": "Mover mercancía a tiempo optimizando rutas, flota y trazabilidad de envíos.",
        "tecnologias": ["TMS/WMS", "GPS y rastreo", "SQL", "APIs de integración", "Power BI"],
        "tareas": ["Soporte a sistemas de rastreo", "Integraciones y reportes", "Mesa de ayuda"],
    },
    {
        "sector": "Agroindustria",
        "claves": ("agro", "agricola", "cultivo", "ganader", "avicola", "cafe", "cacao", "palma",
                   "pecuari", "flores"),
        "problema": "Producir y comercializar productos agropecuarios con trazabilidad y eficiencia.",
        "tecnologias": ["ERP agrícola", "Excel/Power BI", "Apps móviles de campo", "SQL"],
        "tareas": ["Digitalización de registros de campo", "Reportes y tableros", "Soporte técnico"],
    },
    {
        "sector": "Energía, minería e hidrocarburos",
        "claves": ("energia", "electric", "petrole", "hidrocarburo", "mineria", "gas natural", "solar",
                   "oil", "refineria"),
        "problema": "Operar infraestructura crítica de forma segura, eficiente y regulada.",
        "tecnologias": ["SAP", "SCADA", "SQL", "Python para análisis de datos", "Power BI"],
        "tareas": ["Soporte de sistemas corporativos", "Análisis y visualización de datos",
                   "Gestión de inventario tecnológico"],
    },
    {
        "sector": "Telecomunicaciones",
        "claves": ("telecomunicacion", "internet", "fibra optica", "isp", "conectividad", "redes de datos",
                   "telefonia", "cableado"),
        "problema": "Ofrecer conectividad estable y soporte técnico a hogares y empresas.",
        "tecnologias": ["Redes TCP/IP", "Linux", "Mikrotik", "CRM/ticketing", "Bash/Python"],
        "tareas": ["Soporte técnico N1", "Monitoreo de red", "Automatización de tareas"],
    },
    {
        "sector": "Turismo, hotelería y alimentos",
        "claves": ("hotel", "turismo", "restaurante", "viajes", "agencia de viajes", "gastronom",
                   "eventos", "catering"),
        "problema": "Atraer y atender clientes con reservas, ventas y operación eficientes.",
        "tecnologias": ["Sistemas de reservas/PMS", "POS", "WordPress", "Redes sociales/Meta Ads"],
        "tareas": ["Soporte a sistemas de reservas", "Sitio web y canales digitales", "Reportes"],
    },
    {
        "sector": "Sector público y entidades sin ánimo de lucro",
        "claves": ("alcaldia", "gobernacion", "secretaria", "ministerio", "fundacion",
                   "corporacion", "asociacion", "camara de comercio", "empresa social del estado"),
        "problema": "Prestar servicios a la ciudadanía y gestionar recursos con transparencia.",
        "tecnologias": ["Sistemas de gestión documental", "PHP/Java", "SQL", "Office 365"],
        "tareas": ["Soporte técnico y mesa de ayuda", "Gestión documental digital",
                   "Actualización de portales web"],
    },
    {
        "sector": "Servicios profesionales y consultoría",
        "claves": ("consultor", "asesoria", "outsourcing", "auditor", "contable", "juridic",
                   "abogados", "servicios empresariales", "temporales", "bpo", "call center"),
        "problema": "Resolver necesidades especializadas de otras empresas (contables, legales, operativas).",
        "tecnologias": ["Office 365/Google Workspace", "CRM", "SQL", "Power Automate", "Python"],
        "tareas": ["Automatización de procesos internos", "Soporte a usuarios", "Reportes y tableros"],
    },
]

TAREAS_BASE_ADSO = [
    "Apoyo en análisis de requerimientos",
    "Desarrollo, pruebas y documentación de software",
    "Soporte técnico a usuarios internos",
]

# Huellas técnicas detectables en el HTML de la portada
HUELLAS_TECNICAS: dict[str, tuple[str, ...]] = {
    "WordPress": ("wp-content", "wp-includes"),
    "WooCommerce": ("woocommerce",),
    "Shopify": ("cdn.shopify.com", "shopify"),
    "Wix": ("wix.com", "wixstatic"),
    "React": ("data-reactroot", "react-dom", "__next"),
    "Next.js": ("__next_data__", "/_next/"),
    "Angular": ("ng-version", "ng-app"),
    "Vue.js": ("data-v-", "vue.js", "__vue__"),
    "Laravel": ("laravel_session", "laravel"),
    "Django": ("csrfmiddlewaretoken",),
    "ASP.NET": ("__viewstate", "asp.net"),
    "Bootstrap": ("bootstrap",),
    "jQuery": ("jquery",),
    "Google Analytics": ("googletagmanager", "google-analytics"),
    "HubSpot": ("hs-scripts", "hubspot"),
    "Odoo": ("odoo", "/web/assets"),
}


# =============================================================================
# Funciones puras
# =============================================================================
def dominio(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().removeprefix("www.")
    except ValueError:
        return ""


def es_directorio(url: str) -> bool:
    """True si la URL es un directorio, red social o portal de empleo (no el sitio oficial)."""
    d = dominio(url)
    for tag in DIRECTORIOS:
        if "." in tag:  # dominio: coincidencia exacta o subdominio
            if d == tag or d.endswith("." + tag):
                return True
        elif tag in d:  # marca: subcadena del dominio
            return True
    return False


def _tokens_nombre(razon_social: str) -> list[str]:
    ruido = {"sas", "s.a.s", "ltda", "sa", "s.a", "de", "la", "el", "y", "e", "los", "las",
             "cia", "compania", "sociedad", "grupo", "colombia", "s", "en", "c"}
    return [t for t in re.split(r"[^a-z0-9]+", normalizar(razon_social)) if len(t) > 2 and t not in ruido]


def elegir_sitio_oficial(razon_social: str, resultados: list[dict[str, str]]) -> tuple[str, str]:
    """Devuelve (sitio_oficial, perfil_comercial) según similitud dominio↔razón social."""
    tokens = _tokens_nombre(razon_social)
    mejor, mejor_puntaje = "", 0.0
    perfil = ""
    for r in resultados:
        url = r.get("href", "")
        if not url:
            continue
        if es_directorio(url):
            if any(p in url for p in PERFILES_PREFERIDOS) and not any(
                p in perfil for p in PERFILES_PREFERIDOS
            ):
                perfil = url  # perfil comercial preferido (LinkedIn, RUES, einforma…)
            elif not perfil and not dominio(url).endswith(("facebook.com", "instagram.com",
                                                            "tiktok.com", "youtube.com")):
                perfil = url  # cualquier otro directorio como respaldo
            continue
        d = dominio(url).replace("-", "")
        puntaje = sum(1.0 for t in tokens if t in d)
        texto = normalizar(r.get("title", "") + " " + r.get("body", ""))
        puntaje += 0.3 * sum(1 for t in tokens if t in texto)
        if puntaje > mejor_puntaje:
            mejor, mejor_puntaje = url, puntaje
    if mejor and mejor_puntaje >= 1.0:
        p = urlparse(mejor)
        return f"{p.scheme}://{p.netloc}", perfil
    return "", perfil


def clasificar_sector(texto: str) -> dict[str, Any] | None:
    """Elige el sector con más coincidencias de palabras clave."""
    t = normalizar(texto)
    mejor, max_hits = None, 0
    for s in SECTORES:
        # \b al inicio: las claves son prefijos de palabra ("financier" → financiera/o)
        hits = sum(len(re.findall(r"\b" + re.escape(normalizar(c)), t)) for c in s["claves"])
        if hits > max_hits:
            mejor, max_hits = s, hits
    return mejor


def detectar_tecnologias(html: str) -> list[str]:
    bajo = html.lower()
    return [tec for tec, huellas in HUELLAS_TECNICAS.items() if any(h in bajo for h in huellas)]


def extraer_meta(html: str) -> dict[str, str]:
    """Título y meta description de una página (sin BeautifulSoup para mantenerlo liviano)."""
    def buscar(patron: str) -> str:
        m = re.search(patron, html, re.I | re.S)
        return limpiar(re.sub(r"<[^>]+>", " ", m.group(1))) if m else ""

    return {
        "titulo": buscar(r"<title[^>]*>(.*?)</title>"),
        "descripcion": buscar(
            r'<meta[^>]+name=["\'](?:description|og:description)["\'][^>]+content=["\'](.*?)["\']'
        ) or buscar(r'<meta[^>]+property=["\']og:description["\'][^>]+content=["\'](.*?)["\']'),
    }


SUFIJOS_LEGALES = re.compile(
    r"\b(s\.?\s?a\.?\s?s\.?|s\.?\s?a\.?|ltda\.?|limitada|e\.?\s?u\.?|s\.?\s?c\.?\s?a\.?|"
    r"y\s+c[ií]a\.?|sociedad por acciones simplificada|sucursal colombia)(?=\s|$|,)",
    re.I,
)


def nombre_comercial(razon_social: str) -> str:
    """'Sistemas y Computadores S.A.' → 'Sistemas y Computadores'."""
    return limpiar(SUFIJOS_LEGALES.sub(" ", razon_social).replace(",", " ")).strip(" .-")


def consultas_empresa(vacante: Vacante) -> list[str]:
    """Consultas de lo más específico a lo más amplio (se detiene en la primera con resultados)."""
    nombre = nombre_comercial(vacante.razon_social) or vacante.razon_social
    consultas = [f'"{nombre}" {vacante.ciudad}'.strip(), f"{nombre} Colombia empresa"]
    if vacante.nit:
        consultas.append(f"NIT {vacante.nit.split('-')[0]}")
    return list(dict.fromkeys(consultas))


def ficha_heuristica(
    vacante: Vacante, resultados: list[dict[str, str]], meta: dict[str, str], tecs_web: list[str]
) -> FichaEmpresa:
    sitio, perfil = elegir_sitio_oficial(vacante.razon_social, resultados)
    # El perfil de la vacante NO entra en la evidencia del sector: describe al aprendiz
    # (casi siempre dice "software"), no a la empresa, y sesgaría la clasificación.
    evidencia = " ".join(
        [vacante.razon_social, meta.get("titulo", ""), meta.get("descripcion", "")]
        + [r.get("title", "") + " " + r.get("body", "") for r in resultados[:5]]
    )
    sector = clasificar_sector(evidencia)
    resumen = meta.get("descripcion") or next(
        (limpiar(r.get("body", "")) for r in resultados if r.get("body")), ""
    )
    tecnologias = list(dict.fromkeys(tecs_web + (sector["tecnologias"] if sector else [])))
    tareas = list(dict.fromkeys((sector["tareas"] if sector else []) + TAREAS_BASE_ADSO))
    return FichaEmpresa(
        empresa_key=vacante.empresa_key,
        razon_social=vacante.razon_social,
        nit=vacante.nit,
        sitio_web=sitio or perfil,
        sector=sector["sector"] if sector else "No determinado",
        problema_negocio=sector["problema"] if sector else "",
        resumen=resumen[:400],
        tecnologias=tecnologias[:8],
        tareas_aprendiz=tareas[:6],
        fuentes=[r["href"] for r in resultados[:5] if r.get("href")],
        metodo="heuristico",
    )


# =============================================================================
# Investigador
# =============================================================================
class Enricher:
    def __init__(self, settings: Settings, db: Database, llm: LLMClient | None = None) -> None:
        self.s = settings
        self.db = db
        self.llm = llm
        self._ddgs: Any = None

    def _cliente_busqueda(self) -> Any:
        if self._ddgs is None:
            try:
                from ddgs import DDGS  # nombre actual del paquete
            except ImportError:  # compatibilidad con el nombre antiguo
                from duckduckgo_search import DDGS  # type: ignore[no-redef]
            self._ddgs = DDGS()
        return self._ddgs

    def buscar(self, consulta: str) -> list[dict[str, str]]:
        """Búsqueda pública con reintentos. "Sin resultados" devuelve [] sin reintentar."""
        for intento in range(1, self.s.max_reintentos + 1):
            try:
                resultados = self._cliente_busqueda().text(
                    consulta, region="co-es", max_results=self.s.enrich_max_resultados
                )
                return list(resultados or [])
            except Exception as exc:  # noqa: BLE001
                if "no results" in str(exc).lower():
                    return []
                if intento == self.s.max_reintentos:
                    raise
                espera = 6.0 * 2 ** (intento - 1)
                log.warning("Búsqueda falló (%s). Reintento en %.0fs", exc, espera)
                dormir(espera)
        return []

    def leer_portada(self, url: str) -> tuple[dict[str, str], list[str]]:
        """Una única petición GET a la portada pública del sitio (timeout corto)."""
        try:
            r = requests.get(
                url, timeout=12, headers={"User-Agent": random_user_agent(),
                                          "Accept-Language": "es-CO,es;q=0.9"},
            )
            if r.status_code >= 400 or "text/html" not in r.headers.get("content-type", ""):
                return {}, []
            html = r.text[:600_000]
            return extraer_meta(html), detectar_tecnologias(html)
        except requests.RequestException as exc:
            log.debug("Portada no accesible %s: %s", url, exc)
            return {}, []

    def _ficha_llm(self, vacante: Vacante, base: FichaEmpresa,
                   resultados: list[dict[str, str]], meta: dict[str, str],
                   tecs_web: list[str]) -> FichaEmpresa:
        assert self.llm is not None
        evidencia = "\n".join(
            f"- {r.get('title', '')} | {r.get('href', '')} | {r.get('body', '')[:300]}"
            for r in resultados[:6]
        )
        prompt = f"""Construye la ficha técnica de una empresa colombiana usando SOLO la evidencia.
Si un dato no está respaldado, deja el campo vacío o infiérelo con prudencia a partir del sector.

EMPRESA: {vacante.razon_social} (NIT: {vacante.nit or 'N/D'}) — Ciudad: {vacante.ciudad or 'N/D'}
PERFIL SOLICITADO AL APRENDIZ: {vacante.perfil[:800] or 'N/D'}
SITIO CANDIDATO: {base.sitio_web or 'N/D'}
META DEL SITIO: {meta.get('titulo', '')} — {meta.get('descripcion', '')}
TECNOLOGÍAS DETECTADAS EN EL HTML: {', '.join(tecs_web) or 'ninguna'}
RESULTADOS DE BÚSQUEDA:
{evidencia or '(sin resultados)'}

Responde SOLO con JSON con estas claves:
{{"sitio_web": str, "sector": str, "problema_negocio": str (1 frase),
  "resumen": str (máx 50 palabras, qué hace la empresa),
  "tecnologias": [str] (máx 8, probables para el área de sistemas),
  "tareas_aprendiz": [str] (máx 6, tareas concretas esperadas para un aprendiz
                      de {self.s.programa_formacion})}}"""
        data = self.llm.generar_json(
            prompt,
            system="Eres un analista de inteligencia empresarial en Colombia. No inventes URLs.",
            temperatura=0.2,
        )

        def lista(v: Any) -> list[str]:
            return [limpiar(str(x)) for x in v][:8] if isinstance(v, list) else []

        sitio = str(data.get("sitio_web") or "")
        # Solo se acepta un sitio que aparezca en la evidencia (anti-alucinación)
        if sitio and dominio(sitio) not in {dominio(r.get("href", "")) for r in resultados} | {
            dominio(base.sitio_web)
        }:
            sitio = base.sitio_web
        return FichaEmpresa(
            empresa_key=base.empresa_key,
            razon_social=base.razon_social,
            nit=base.nit,
            sitio_web=sitio or base.sitio_web,
            sector=limpiar(str(data.get("sector") or base.sector)),
            problema_negocio=limpiar(str(data.get("problema_negocio") or base.problema_negocio)),
            resumen=limpiar(str(data.get("resumen") or base.resumen))[:400],
            tecnologias=lista(data.get("tecnologias")) or base.tecnologias,
            tareas_aprendiz=lista(data.get("tareas_aprendiz"))[:6] or base.tareas_aprendiz,
            fuentes=base.fuentes,
            metodo="llm",
        )

    def enriquecer(self, vacante: Vacante) -> FichaEmpresa:
        # Se acumulan resultados de consultas cada vez más amplias y se para en cuanto
        # aparece un candidato a sitio oficial (los directorios solos no bastan).
        resultados: list[dict[str, str]] = []
        for i, consulta in enumerate(consultas_empresa(vacante)):
            if i:
                polite_delay(self.s.delay_min, self.s.delay_max)
            try:
                nuevos = self.buscar(consulta)
            except Exception as exc:  # noqa: BLE001 - la búsqueda nunca debe tumbar el pipeline
                log.warning("Búsqueda fallida para %s: %s", vacante.razon_social, exc)
                break
            vistos = {r.get("href") for r in resultados}
            resultados += [r for r in nuevos if r.get("href") not in vistos]
            if elegir_sitio_oficial(vacante.razon_social, resultados)[0]:
                break

        sitio, _ = elegir_sitio_oficial(vacante.razon_social, resultados)
        meta, tecs = ({}, [])
        if sitio:
            polite_delay(self.s.delay_min, self.s.delay_max)
            meta, tecs = self.leer_portada(sitio)

        ficha = ficha_heuristica(vacante, resultados, meta, tecs)
        if self.llm:
            try:
                ficha = self._ficha_llm(vacante, ficha, resultados, meta, tecs)
            except Exception as exc:  # noqa: BLE001
                log.warning("LLM no pudo sintetizar la ficha de %s: %s", vacante.razon_social, exc)
        return ficha

    def run(self, forzar: bool = False) -> int:
        pendientes = self.db.vacantes_activas() if forzar else self.db.empresas_sin_enriquecer()
        if forzar:  # una vacante por empresa
            pendientes = list({v.empresa_key: v for v in pendientes}.values())
        log.info("Empresas por enriquecer: %d", len(pendientes))
        for i, vacante in enumerate(pendientes, 1):
            verificar_cancelacion()
            ficha = self.enriquecer(vacante)
            self.db.guardar_ficha(ficha)
            log.info("[%d/%d] %s → %s | %s", i, len(pendientes), vacante.razon_social,
                     ficha.sector, ficha.sitio_web or "sin sitio")
            if i < len(pendientes):
                polite_delay(self.s.delay_min, self.s.delay_max)
        self.db.exportar_json(self.s.json_path)
        return len(pendientes)


def run_enricher(settings: Settings, db: Database, forzar: bool = False) -> int:
    return Enricher(settings, db, crear_cliente_opcional(settings)).run(forzar=forzar)
