"""
Módulo 5 — Monitor y Alertas por Telegram.

- Compara el snapshot de vacantes de hoy contra el del día anterior (nuevas / retiradas).
- Notifica por Telegram cada vacante activa del área del aprendiz que AÚN no haya sido
  alertada. La deduplicación se hace por ID de vacante en la tabla `alertas` de SQLite,
  así no se pierde una vacante aunque el monitor no haya corrido algún día, y nunca se
  repite una alerta aunque el monitor corra varias veces al día.
- Si hay muchas vacantes nuevas a la vez, se envía un único mensaje-resumen (anti-spam).

Configuración (.env): TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID.
"""

from __future__ import annotations

import asyncio
import html
import logging
from dataclasses import dataclass

from config import Settings
from modules.db import Database
from modules.models import FichaEmpresa, Vacante
from modules.scraper import coincide_area

log = logging.getLogger(__name__)

MAX_ALERTAS_INDIVIDUALES = 8
LIMITE_MENSAJE = 4000  # Telegram admite 4096 caracteres; dejamos margen


@dataclass
class DiffDiario:
    fecha_hoy: str | None
    fecha_anterior: str | None
    nuevas: set[str]
    retiradas: set[str]


# =============================================================================
# Lógica de comparación (pura sobre la BD)
# =============================================================================
def comparar_con_dia_anterior(db: Database) -> DiffDiario:
    fechas = db.fechas_snapshot()
    if not fechas:
        return DiffDiario(None, None, set(), set())
    hoy = fechas[-1]
    hoy_ids = db.ids_en_snapshot(hoy)
    if len(fechas) == 1:
        return DiffDiario(hoy, None, hoy_ids, set())
    anterior = fechas[-2]
    ant_ids = db.ids_en_snapshot(anterior)
    return DiffDiario(hoy, anterior, hoy_ids - ant_ids, ant_ids - hoy_ids)


def vacantes_por_alertar(db: Database, settings: Settings) -> list[Vacante]:
    """Vacantes activas, del área del aprendiz, que nunca se han notificado."""
    return [
        v for v in db.vacantes_activas()
        if not db.ya_alertada(v)
        and coincide_area(v, settings.palabras_clave_area, settings.programa_formacion)
    ]


# =============================================================================
# Formato de mensajes (HTML de Telegram)
# =============================================================================
def _e(texto: str) -> str:
    return html.escape(texto or "", quote=True)


def resumen_empresa(ficha: FichaEmpresa | None) -> str:
    if not ficha:
        return "Ficha de empresa pendiente (ejecuta --enrich)."
    partes = [ficha.resumen or ficha.problema_negocio]
    if ficha.sector and ficha.sector != "No determinado":
        partes.insert(0, f"[{ficha.sector}]")
    texto = " ".join(p for p in partes if p).strip()
    return (texto[:280] + "…") if len(texto) > 280 else (texto or "Sin información pública.")


def formatear_alerta(v: Vacante, ficha: FichaEmpresa | None) -> str:
    lineas = [
        "🆕 <b>Nueva vacante de contrato de aprendizaje</b>",
        "",
        f"🏢 <b>{_e(v.razon_social)}</b>",
        f"📍 {_e(v.ciudad or 'Ciudad no especificada')}",
        f"💼 {_e(resumen_empresa(ficha))}",
        f"🗓️ Fecha límite: <b>{_e(v.fecha_limite or 'No indicada')}</b>",
    ]
    if ficha and ficha.sitio_web:
        lineas.append(f'🌐 <a href="{_e(ficha.sitio_web)}">Sitio de la empresa</a>')
    if v.enlace:
        lineas.append(f'🔗 <a href="{_e(v.enlace)}">Ir a la postulación</a>')
    return "\n".join(lineas)


def formatear_resumen(vacantes: list[Vacante], db: Database) -> list[str]:
    """Mensaje-resumen dividido en trozos que respetan el límite de Telegram."""
    encabezado = f"📋 <b>{len(vacantes)} vacantes nuevas de aprendizaje</b>\n"
    bloques: list[str] = []
    for v in vacantes:
        ficha = db.obtener_ficha(v.empresa_key)
        sector = f" · {_e(ficha.sector)}" if ficha and ficha.sector else ""
        enlace = f' — <a href="{_e(v.enlace)}">postular</a>' if v.enlace else ""
        bloques.append(
            f"• <b>{_e(v.razon_social)}</b> ({_e(v.ciudad or 'N/D')}){sector}\n"
            f"   Cierra: {_e(v.fecha_limite or 'N/D')}{enlace}"
        )
    mensajes, actual = [], encabezado
    for b in bloques:
        if len(actual) + len(b) + 2 > LIMITE_MENSAJE:
            mensajes.append(actual)
            actual = ""
        actual += "\n" + b
    mensajes.append(actual)
    return mensajes


# =============================================================================
# Envío
# =============================================================================
class TelegramNotifier:
    def __init__(self, settings: Settings) -> None:
        if not settings.telegram_token or not settings.telegram_chat_id:
            raise ValueError("Configura TELEGRAM_BOT_TOKEN y TELEGRAM_CHAT_ID en .env")
        self.token = settings.telegram_token
        self.chat_id = settings.telegram_chat_id

    async def enviar_varios(self, mensajes: list[str]) -> list[bool]:
        """Envía en orden; devuelve qué mensajes se entregaron (mismo orden)."""
        from telegram import Bot, LinkPreviewOptions
        from telegram.constants import ParseMode
        from telegram.error import RetryAfter, TelegramError

        resultado: list[bool] = []
        async with Bot(self.token) as bot:
            for texto in mensajes:
                ok = False
                for _ in range(3):
                    try:
                        await bot.send_message(
                            chat_id=self.chat_id, text=texto, parse_mode=ParseMode.HTML,
                            link_preview_options=LinkPreviewOptions(is_disabled=True),
                        )
                        ok = True
                        break
                    except RetryAfter as exc:  # límite de tasa de Telegram
                        espera = float(getattr(exc, "retry_after", 5))
                        log.warning("Telegram pide esperar %.0fs", espera)
                        await asyncio.sleep(espera + 1)
                    except TelegramError as exc:
                        log.error("Error enviando a Telegram: %s", exc)
                        break
                resultado.append(ok)
                await asyncio.sleep(1.2)  # ~1 mensaje/segundo por chat
        return resultado

    def enviar(self, mensajes: list[str]) -> list[bool]:
        return asyncio.run(self.enviar_varios(mensajes))


def run_alertas(settings: Settings, db: Database, dry_run: bool = False) -> int:
    """Detecta vacantes no notificadas y envía las alertas. Devuelve cuántas se alertaron."""
    diff = comparar_con_dia_anterior(db)
    if diff.fecha_anterior:
        log.info("Snapshot %s vs %s: %d nuevas, %d retiradas",
                 diff.fecha_hoy, diff.fecha_anterior, len(diff.nuevas), len(diff.retiradas))
    else:
        log.info("Primer snapshot registrado (%s): %d vacantes", diff.fecha_hoy, len(diff.nuevas))

    pendientes = vacantes_por_alertar(db, settings)
    if not pendientes:
        log.info("Sin vacantes nuevas por alertar.")
        return 0

    resumen = len(pendientes) > MAX_ALERTAS_INDIVIDUALES
    if resumen:
        mensajes = formatear_resumen(pendientes, db)
    else:
        mensajes = [formatear_alerta(v, db.obtener_ficha(v.empresa_key)) for v in pendientes]

    if dry_run:
        for m in mensajes:
            print("-" * 60 + "\n" + m)
        log.info("[dry-run] %d mensajes NO enviados ni registrados.", len(mensajes))
        return len(pendientes)

    entregados = TelegramNotifier(settings).enviar(mensajes)
    if resumen:
        # El resumen es atómico: solo se registra si llegaron todos los trozos
        alertadas = pendientes if all(entregados) else []
    else:
        alertadas = [v for v, ok in zip(pendientes, entregados, strict=True) if ok]
    for v in alertadas:
        db.registrar_alerta(v)
    fallidos = len(entregados) - sum(entregados)
    if fallidos:
        log.error("%d mensajes no se entregaron; se reintentarán en la próxima ejecución.", fallidos)
    log.info("Alertadas %d de %d vacantes pendientes.", len(alertadas), len(pendientes))
    return len(alertadas)
