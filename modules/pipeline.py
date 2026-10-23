"""
Pasos del pipeline, compartidos por la CLI (`main.py`) y la app de escritorio (`app_gui.py`).

    scraping → enriquecimiento → hoja de vida + correos → alertas
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Callable

from config import Settings
from modules.db import Database
from modules.utils import verificar_cancelacion

log = logging.getLogger(__name__)

Progreso = Callable[[str, float], None]  # (etapa, fracción 0–1)
Aviso = Callable[[str], None]


def _sin_progreso(_etapa: str, _fraccion: float) -> None:
    pass


def paso_scrape(s: Settings, db: Database, aviso: Aviso | None = None) -> int:
    from modules.scraper import run_scraper

    return len(run_scraper(s, db, aviso))


def paso_enrich(s: Settings, db: Database, forzar: bool = False) -> int:
    from modules.enricher import run_enricher

    return run_enricher(s, db, forzar=forzar)


def paso_generar(s: Settings, db: Database, forzar: bool = False, pdf: bool = True,
                 solo_id: str | None = None, progreso: Progreso = _sin_progreso) -> list[dict]:
    """Genera hoja de vida + correos por vacante. Devuelve el ranking completo y vigente."""
    from modules.cv_adapter import RenderizadorPDF, adaptar_cv, cargar_perfil
    from modules.email_generator import carpeta_vacante, crear_generador
    from modules.scraper import coincide_area

    perfil = cargar_perfil(s.perfil_path)
    generador = crear_generador(s, db)

    if solo_id:
        v = db.obtener_vacante(solo_id)
        if not v:
            log.error("No existe la vacante %s", solo_id)
            return leer_ranking(s, db)
        vacantes = [v]
    else:
        vacantes = [
            v for v in db.vacantes_activas()
            if coincide_area(v, s.palabras_clave_area, s.programa_formacion)
        ]

    existentes = {r["vacante_id"]: r for r in leer_ranking(s, db)}
    pendientes = [
        v for v in vacantes
        if forzar or solo_id or not db.tiene_correo(v.id) or v.id not in existentes
    ]
    log.info("Hojas de vida por generar: %d (de %d vacantes de tu área)",
             len(pendientes), len(vacantes))

    with RenderizadorPDF(s.browser_channel) as renderizador:
        for i, v in enumerate(pendientes, 1):
            verificar_cancelacion()
            progreso(f"Preparando postulación {i}/{len(pendientes)}: {v.razon_social}",
                     (i - 1) / max(len(pendientes), 1))
            carpeta = carpeta_vacante(s, v)
            ficha = db.obtener_ficha(v.empresa_key)
            cv = adaptar_cv(perfil, v, ficha, carpeta, pdf=pdf,
                            renderizador=renderizador if pdf else None)
            correo = generador.generar(perfil, v, proyecto_destacado=cv["proyecto_top"])
            generador.guardar(correo, v, carpeta)
            existentes[v.id] = {
                "vacante_id": v.id,
                "afinidad": cv["afinidad"].puntaje,
                "empresa": v.razon_social,
                "ciudad": v.ciudad,
                "fecha_limite": v.fecha_limite,
                "enlace": v.enlace,
                "carpeta": str(carpeta),
                "pdf": str(cv["pdf"]) if cv["pdf"] else "",
                "coincidencias": cv["afinidad"].coincidencias,
                "brechas": cv["afinidad"].faltantes,
                "sector": ficha.sector if ficha else "",
                "correo_por": correo.proveedor,
            }
            log.info("[%d/%d] %s → afinidad %.0f%%", i, len(pendientes), v.razon_social,
                     cv["afinidad"].puntaje)

    activas = {v.id for v in db.vacantes_activas()}
    ranking = sorted(
        (r for r in existentes.values() if r["vacante_id"] in activas),
        key=lambda r: r["afinidad"], reverse=True,
    )
    (s.output_dir / "ranking.json").write_text(
        json.dumps({"generado_en": datetime.now().isoformat(timespec="seconds"),
                    "vacantes": ranking}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return ranking


def leer_ranking(s: Settings, db: Database | None = None) -> list[dict]:
    """Ranking guardado (solo vacantes activas si se pasa `db`)."""
    ruta = s.output_dir / "ranking.json"
    if not ruta.exists():
        return []
    try:
        filas: list[dict[str, Any]] = json.loads(ruta.read_text("utf-8")).get("vacantes", [])
    except (json.JSONDecodeError, OSError):
        return []
    filas = [f for f in filas if f.get("vacante_id")]
    if db is not None:
        activas = {v.id for v in db.vacantes_activas()}
        filas = [f for f in filas if f["vacante_id"] in activas]
    return filas


def paso_alertas(s: Settings, db: Database, dry_run: bool = False) -> int:
    from modules.bot_telegram import run_alertas

    if not dry_run and not (s.telegram_token and s.telegram_chat_id):
        log.info("Telegram no configurado: se omiten las alertas.")
        return 0
    return run_alertas(s, db, dry_run=dry_run)


def busqueda_completa(s: Settings, db: Database, aviso: Aviso | None = None,
                      progreso: Progreso = _sin_progreso, pdf: bool = True) -> dict[str, Any]:
    """El botón «Buscar» de la app: todo el pipeline en orden, con progreso por etapa."""
    progreso("Conectando con el portal de Caprendizaje…", 0.02)
    encontradas = paso_scrape(s, db, aviso)

    verificar_cancelacion()
    progreso("Investigando las empresas…", 0.35)
    investigadas = paso_enrich(s, db)

    verificar_cancelacion()

    def progreso_generar(etapa: str, f: float) -> None:
        progreso(etapa, 0.6 + 0.35 * f)

    ranking = paso_generar(s, db, pdf=pdf, progreso=progreso_generar)

    alertadas = 0
    if s.telegram_token and s.telegram_chat_id:
        progreso("Enviando alertas a Telegram…", 0.97)
        alertadas = paso_alertas(s, db)

    progreso("Listo", 1.0)
    return {"encontradas": encontradas, "investigadas": investigadas,
            "ranking": ranking, "alertadas": alertadas}
