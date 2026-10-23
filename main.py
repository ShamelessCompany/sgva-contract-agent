#!/usr/bin/env python3
"""
SGVA-Matchmaker — Orquestador CLI (Shameless Company).

Proyecto independiente de código abierto. NO es un producto oficial del SENA ni está
avalado, patrocinado o certificado por el Servicio Nacional de Aprendizaje.

Ejemplos:
    python main.py --all              # scraping → enriquecimiento → CV + correos → alertas
    python main.py --scrape           # solo extraer vacantes del SGVA
    python main.py --enrich           # investigar empresas nuevas
    python main.py --generate-all     # CV ATS + correos para cada vacante activa
    python main.py --alert --dry-run  # ver qué alertas se enviarían, sin enviarlas
    python main.py --monitor          # daemon: repite el ciclo cada MONITOR_INTERVALO_MIN
    python main.py --monitor --once   # un solo ciclo (ideal para cron / Task Scheduler)
    python main.py --calibrar         # inspeccionar el portal para ajustar selectores
    python main.py --estado           # resumen de la base de datos local
"""

from __future__ import annotations

import argparse
import logging
import random
import sys
import time

from config import Settings, get_settings
from modules import __version__
from modules.db import Database
from modules.pipeline import paso_alertas, paso_enrich, paso_generar, paso_scrape
from modules.utils import setup_logging

log = logging.getLogger("main")

AVISO = (
    "SGVA-Matchmaker v{v} · Shameless Company · Software independiente, NO oficial del SENA.\n"
    "Úsalo de forma personal y responsable, respetando los términos del portal Caprendizaje."
)


# =============================================================================
# Pasos del pipeline (la lógica vive en modules/pipeline.py, compartida con la app)
# =============================================================================
def paso_generar_cli(s: Settings, db: Database, forzar: bool = False, pdf: bool = True,
                     solo_id: str | None = None) -> int:
    ranking = paso_generar(s, db, forzar=forzar, pdf=pdf, solo_id=solo_id)
    if ranking:
        print("\nTop vacantes por afinidad:")
        for r in ranking[:10]:
            print(f"  {r['afinidad']:5.1f}%  {r['empresa'][:45]:45}  "
                  f"cierra {r['fecha_limite'] or 'N/D'}")
        print(f"\nArchivos en: {s.output_dir}")
    else:
        log.info("No hay vacantes de tu área para generar.")
    return len(ranking)


def ciclo_monitor(s: Settings, db: Database, dry_run: bool) -> None:
    """Un ciclo de monitoreo: scraping → enriquecer nuevas → alertar."""
    paso_scrape(s, db)
    paso_enrich(s, db)
    paso_alertas(s, db, dry_run=dry_run)


def modo_monitor(s: Settings, db: Database, una_vez: bool, dry_run: bool) -> None:
    if una_vez:
        ciclo_monitor(s, db, dry_run)
        return
    log.info("Monitor activo: un ciclo cada ~%d min. Ctrl+C para detener.", s.monitor_intervalo_min)
    fallos_seguidos = 0
    while True:
        try:
            ciclo_monitor(s, db, dry_run)
            fallos_seguidos = 0
        except KeyboardInterrupt:
            raise
        except Exception:  # noqa: BLE001 - el daemon no debe morir por un ciclo fallido
            fallos_seguidos += 1
            log.exception("Ciclo de monitoreo fallido (%d seguidos).", fallos_seguidos)
        # Jitter ±10% y backoff si el portal falla repetidamente
        base = s.monitor_intervalo_min * 60 * min(2 ** fallos_seguidos, 8)
        espera = base * random.uniform(0.9, 1.1)
        log.info("Próximo ciclo en %.0f min.", espera / 60)
        time.sleep(espera)


def mostrar_estado(s: Settings, db: Database) -> None:
    activas = db.vacantes_activas()
    with db.conn() as cx:
        empresas = cx.execute("SELECT COUNT(*) FROM empresas").fetchone()[0]
        correos = cx.execute("SELECT COUNT(*) FROM correos").fetchone()[0]
        alertas = cx.execute("SELECT COUNT(*) FROM alertas").fetchone()[0]
    print(f"Base de datos: {s.db_path}")
    print(f"  Vacantes activas:     {len(activas)}")
    print(f"  Empresas con ficha:   {empresas}")
    print(f"  Correos generados:    {correos}")
    print(f"  Vacantes alertadas:   {alertas}")
    print(f"  Snapshots diarios:    {', '.join(db.fechas_snapshot()[-5:]) or 'ninguno'}")
    print(f"  Sesión guardada:      {'sí' if s.session_path.exists() else 'no'}")
    for v in activas[:15]:
        print(f"   - [{v.id}] {v.razon_social[:40]:40} {v.ciudad[:15]:15} cierra {v.fecha_limite}")


# =============================================================================
# CLI
# =============================================================================
def construir_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sgva-matchmaker",
        description="Automatiza la búsqueda de contratos de aprendizaje SENA, el análisis "
                    "empresarial y la postulación personalizada. (No oficial del SENA)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    acciones = p.add_argument_group("acciones (elige al menos una)")
    acciones.add_argument("--all", action="store_true", help="pipeline completo")
    acciones.add_argument("--scrape", action="store_true", help="extraer vacantes del SGVA")
    acciones.add_argument("--enrich", action="store_true", help="investigar empresas")
    acciones.add_argument("--generate-all", action="store_true",
                          help="generar CV ATS + correos para cada vacante activa")
    acciones.add_argument("--alert", action="store_true", help="enviar alertas pendientes")
    acciones.add_argument("--monitor", action="store_true",
                          help="modo daemon (scrape + enrich + alertas periódicas)")
    acciones.add_argument("--calibrar", action="store_true",
                          help="abrir el portal y volcar su estructura para ajustar selectores")
    acciones.add_argument("--estado", action="store_true", help="resumen de la base local")

    op = p.add_argument_group("opciones")
    op.add_argument("--once", action="store_true", help="con --monitor: un solo ciclo (cron)")
    op.add_argument("--dry-run", action="store_true", help="muestra las alertas sin enviarlas")
    op.add_argument("--forzar", action="store_true",
                    help="re-enriquecer / regenerar aunque ya existan resultados")
    op.add_argument("--sin-pdf", action="store_true", help="generar solo el CV en Markdown")
    op.add_argument("--vacante", metavar="ID", help="con --generate-all: solo esta vacante")
    op.add_argument("--visible", action="store_true", help="navegador visible (HEADLESS=false)")
    op.add_argument("-v", "--verbose", action="store_true", help="logs de depuración")
    op.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = construir_parser()
    args = parser.parse_args(argv)
    if not any([args.all, args.scrape, args.enrich, args.generate_all, args.alert,
                args.monitor, args.calibrar, args.estado]):
        parser.print_help()
        return 1

    s = get_settings()
    if args.visible:
        from config import build_settings

        s = build_settings(headless=False)
    setup_logging(s.logs_dir, logging.DEBUG if args.verbose else logging.INFO)
    print(AVISO.format(v=__version__) + "\n")
    db = Database(s.db_path)

    try:
        if args.estado:
            mostrar_estado(s, db)
        if args.calibrar:
            from modules.scraper import run_calibracion

            r = run_calibracion(s)
            print(f"\nURL actual: {r['url']}\nTablas encontradas:")
            for t in r["tablas"]:
                print(f"  #{t['indice']} id='{t['id']}' filas={t['filas']} → {t['encabezados']}")
                if r["columnas"].get(t["indice"]):
                    print(f"      columnas reconocidas: {r['columnas'][t['indice']]}")
            print(f"\nResumen guardado en: {r['resumen']}")
        if args.monitor:
            modo_monitor(s, db, una_vez=args.once, dry_run=args.dry_run)
            return 0
        if args.all or args.scrape:
            paso_scrape(s, db)
        if args.all or args.enrich:
            paso_enrich(s, db, forzar=args.forzar)
        if args.all or args.generate_all:
            paso_generar_cli(s, db, forzar=args.forzar, pdf=not args.sin_pdf,
                             solo_id=args.vacante)
        if args.all or args.alert:
            paso_alertas(s, db, dry_run=args.dry_run)
    except KeyboardInterrupt:
        print("\nInterrumpido por el usuario.")
        return 130
    except FileNotFoundError as exc:
        log.error("%s", exc)
        return 2
    except Exception:  # noqa: BLE001
        log.exception("Error no controlado")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
