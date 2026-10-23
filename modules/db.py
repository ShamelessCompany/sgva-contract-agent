"""Capa de persistencia SQLite (data/jobs.db).

Tablas:
- vacantes:   convocatorias extraídas (con fechas de primera/última vez vista).
- snapshots:  qué vacantes estaban activas en cada fecha (para comparar contra el día anterior).
- empresas:   ficha técnica generada por el enriquecedor.
- correos:    variantes de correo generadas por el LLM o la plantilla.
- alertas:    vacantes ya notificadas por Telegram (evita duplicados).
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime
from pathlib import Path
from typing import Iterator

from modules.models import CorreoGenerado, FichaEmpresa, Vacante

SCHEMA = """
CREATE TABLE IF NOT EXISTS vacantes (
    id              TEXT PRIMARY KEY,
    id_portal       TEXT,
    razon_social    TEXT NOT NULL,
    nit             TEXT,
    empresa_key     TEXT NOT NULL,
    ciudad          TEXT,
    fecha_limite    TEXT,
    perfil          TEXT,
    enlace          TEXT,
    programa        TEXT,
    content_hash    TEXT NOT NULL,
    activa          INTEGER NOT NULL DEFAULT 1,
    primera_vez     TEXT NOT NULL,
    ultima_vez      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_vacantes_empresa ON vacantes(empresa_key);

CREATE TABLE IF NOT EXISTS snapshots (
    fecha       TEXT NOT NULL,
    vacante_id  TEXT NOT NULL,
    PRIMARY KEY (fecha, vacante_id)
);

CREATE TABLE IF NOT EXISTS empresas (
    empresa_key      TEXT PRIMARY KEY,
    razon_social     TEXT NOT NULL,
    nit              TEXT,
    sitio_web        TEXT,
    sector           TEXT,
    problema_negocio TEXT,
    resumen          TEXT,
    tecnologias      TEXT,  -- JSON list
    tareas_aprendiz  TEXT,  -- JSON list
    fuentes          TEXT,  -- JSON list
    metodo           TEXT,
    enriquecido_en   TEXT
);

CREATE TABLE IF NOT EXISTS correos (
    vacante_id      TEXT PRIMARY KEY,
    asunto          TEXT,
    version_corta   TEXT,
    version_formal  TEXT,
    proveedor       TEXT,
    generado_en     TEXT
);

CREATE TABLE IF NOT EXISTS alertas (
    vacante_id    TEXT PRIMARY KEY,
    content_hash  TEXT NOT NULL,
    enviada_en    TEXT NOT NULL
);
"""


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


class Database:
    """Repositorio ligero sobre sqlite3 (sin ORM, sin dependencias externas)."""

    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.conn() as cx:
            cx.executescript(SCHEMA)

    @contextmanager
    def conn(self) -> Iterator[sqlite3.Connection]:
        cx = sqlite3.connect(self.path)
        cx.row_factory = sqlite3.Row
        try:
            yield cx
            cx.commit()
        finally:
            cx.close()

    # ------------------------------------------------------------------ vacantes
    def guardar_vacantes(self, vacantes: list[Vacante], hoy: date | None = None) -> dict[str, int]:
        """Inserta/actualiza vacantes, registra el snapshot del día y marca inactivas las ausentes.

        Devuelve un resumen {"nuevas": n, "actualizadas": n, "inactivadas": n}.
        """
        hoy_iso = (hoy or date.today()).isoformat()
        ahora = _ahora()
        nuevas = actualizadas = 0
        ids_actuales = {v.id for v in vacantes}
        with self.conn() as cx:
            for v in vacantes:
                existe = cx.execute("SELECT 1 FROM vacantes WHERE id = ?", (v.id,)).fetchone()
                if existe:
                    cx.execute(
                        """UPDATE vacantes SET razon_social=?, nit=?, empresa_key=?, ciudad=?,
                           fecha_limite=?, perfil=?, enlace=?, programa=?, content_hash=?,
                           activa=1, ultima_vez=? WHERE id=?""",
                        (v.razon_social, v.nit, v.empresa_key, v.ciudad, v.fecha_limite,
                         v.perfil, v.enlace, v.programa, v.content_hash, ahora, v.id),
                    )
                    actualizadas += 1
                else:
                    cx.execute(
                        """INSERT INTO vacantes (id, id_portal, razon_social, nit, empresa_key,
                           ciudad, fecha_limite, perfil, enlace, programa, content_hash, activa,
                           primera_vez, ultima_vez) VALUES (?,?,?,?,?,?,?,?,?,?,?,1,?,?)""",
                        (v.id, v.id_portal, v.razon_social, v.nit, v.empresa_key, v.ciudad,
                         v.fecha_limite, v.perfil, v.enlace, v.programa, v.content_hash,
                         ahora, ahora),
                    )
                    nuevas += 1
                cx.execute(
                    "INSERT OR IGNORE INTO snapshots (fecha, vacante_id) VALUES (?, ?)",
                    (hoy_iso, v.id),
                )
            # Solo inactivar si el scraping trajo resultados (evita borrar todo por un fallo)
            inactivadas = 0
            if ids_actuales:
                marcadores = ",".join("?" * len(ids_actuales))
                cur = cx.execute(
                    f"UPDATE vacantes SET activa=0 WHERE activa=1 AND id NOT IN ({marcadores})",
                    tuple(ids_actuales),
                )
                inactivadas = cur.rowcount
        return {"nuevas": nuevas, "actualizadas": actualizadas, "inactivadas": inactivadas}

    def vacantes_activas(self) -> list[Vacante]:
        with self.conn() as cx:
            filas = cx.execute(
                "SELECT * FROM vacantes WHERE activa=1 ORDER BY fecha_limite, razon_social"
            ).fetchall()
        return [self._fila_a_vacante(f) for f in filas]

    def obtener_vacante(self, vacante_id: str) -> Vacante | None:
        with self.conn() as cx:
            fila = cx.execute("SELECT * FROM vacantes WHERE id=?", (vacante_id,)).fetchone()
        return self._fila_a_vacante(fila) if fila else None

    @staticmethod
    def _fila_a_vacante(fila: sqlite3.Row) -> Vacante:
        return Vacante(
            id=fila["id"], id_portal=fila["id_portal"] or "", razon_social=fila["razon_social"],
            nit=fila["nit"] or "", ciudad=fila["ciudad"] or "",
            fecha_limite=fila["fecha_limite"] or "", perfil=fila["perfil"] or "",
            enlace=fila["enlace"] or "", programa=fila["programa"] or "",
        )

    # ------------------------------------------------------------------ snapshots
    def fechas_snapshot(self) -> list[str]:
        with self.conn() as cx:
            filas = cx.execute("SELECT DISTINCT fecha FROM snapshots ORDER BY fecha").fetchall()
        return [f["fecha"] for f in filas]

    def ids_en_snapshot(self, fecha: str) -> set[str]:
        with self.conn() as cx:
            filas = cx.execute(
                "SELECT vacante_id FROM snapshots WHERE fecha=?", (fecha,)
            ).fetchall()
        return {f["vacante_id"] for f in filas}

    # ------------------------------------------------------------------ empresas
    def guardar_ficha(self, ficha: FichaEmpresa) -> None:
        with self.conn() as cx:
            cx.execute(
                """INSERT INTO empresas (empresa_key, razon_social, nit, sitio_web, sector,
                   problema_negocio, resumen, tecnologias, tareas_aprendiz, fuentes, metodo,
                   enriquecido_en) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(empresa_key) DO UPDATE SET
                     razon_social=excluded.razon_social, nit=excluded.nit,
                     sitio_web=excluded.sitio_web, sector=excluded.sector,
                     problema_negocio=excluded.problema_negocio, resumen=excluded.resumen,
                     tecnologias=excluded.tecnologias, tareas_aprendiz=excluded.tareas_aprendiz,
                     fuentes=excluded.fuentes, metodo=excluded.metodo,
                     enriquecido_en=excluded.enriquecido_en""",
                (ficha.empresa_key, ficha.razon_social, ficha.nit, ficha.sitio_web, ficha.sector,
                 ficha.problema_negocio, ficha.resumen,
                 json.dumps(ficha.tecnologias, ensure_ascii=False),
                 json.dumps(ficha.tareas_aprendiz, ensure_ascii=False),
                 json.dumps(ficha.fuentes, ensure_ascii=False), ficha.metodo, _ahora()),
            )

    def obtener_ficha(self, empresa_key: str) -> FichaEmpresa | None:
        with self.conn() as cx:
            f = cx.execute("SELECT * FROM empresas WHERE empresa_key=?", (empresa_key,)).fetchone()
        if not f:
            return None
        return FichaEmpresa(
            empresa_key=f["empresa_key"], razon_social=f["razon_social"], nit=f["nit"] or "",
            sitio_web=f["sitio_web"] or "", sector=f["sector"] or "",
            problema_negocio=f["problema_negocio"] or "", resumen=f["resumen"] or "",
            tecnologias=json.loads(f["tecnologias"] or "[]"),
            tareas_aprendiz=json.loads(f["tareas_aprendiz"] or "[]"),
            fuentes=json.loads(f["fuentes"] or "[]"), metodo=f["metodo"] or "heuristico",
        )

    def empresas_sin_enriquecer(self, max_dias: int = 30) -> list[Vacante]:
        """Una vacante representativa por empresa activa sin ficha (o con ficha vieja)."""
        with self.conn() as cx:
            filas = cx.execute(
                """SELECT v.* FROM vacantes v
                   LEFT JOIN empresas e ON e.empresa_key = v.empresa_key
                   WHERE v.activa = 1 AND (e.empresa_key IS NULL
                         OR julianday('now') - julianday(e.enriquecido_en) > ?)
                   GROUP BY v.empresa_key""",
                (max_dias,),
            ).fetchall()
        return [self._fila_a_vacante(f) for f in filas]

    # ------------------------------------------------------------------ correos
    def guardar_correo(self, correo: CorreoGenerado) -> None:
        with self.conn() as cx:
            cx.execute(
                """INSERT OR REPLACE INTO correos
                   (vacante_id, asunto, version_corta, version_formal, proveedor, generado_en)
                   VALUES (?,?,?,?,?,?)""",
                (correo.vacante_id, correo.asunto, correo.version_corta, correo.version_formal,
                 correo.proveedor, _ahora()),
            )

    def tiene_correo(self, vacante_id: str) -> bool:
        with self.conn() as cx:
            return cx.execute(
                "SELECT 1 FROM correos WHERE vacante_id=?", (vacante_id,)
            ).fetchone() is not None

    # ------------------------------------------------------------------ alertas
    def ya_alertada(self, vacante: Vacante) -> bool:
        """True si el ID de esta vacante ya fue notificado (se guarda también su hash de contenido)."""
        with self.conn() as cx:
            fila = cx.execute(
                "SELECT content_hash FROM alertas WHERE vacante_id=?", (vacante.id,)
            ).fetchone()
        return fila is not None

    def registrar_alerta(self, vacante: Vacante) -> None:
        with self.conn() as cx:
            cx.execute(
                "INSERT OR REPLACE INTO alertas (vacante_id, content_hash, enviada_en) VALUES (?,?,?)",
                (vacante.id, vacante.content_hash, _ahora()),
            )

    # ------------------------------------------------------------------ export
    def exportar_json(self, destino: Path) -> int:
        """Exporta las vacantes activas (con ficha de empresa si existe) a JSON."""
        salida = []
        for v in self.vacantes_activas():
            item = v.to_dict()
            ficha = self.obtener_ficha(v.empresa_key)
            item["empresa"] = ficha.to_dict() if ficha else None
            salida.append(item)
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text(
            json.dumps(
                {"generado_en": _ahora(), "total": len(salida), "vacantes": salida},
                ensure_ascii=False, indent=2,
            ),
            encoding="utf-8",
        )
        return len(salida)
