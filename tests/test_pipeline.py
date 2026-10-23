"""Pruebas unitarias sin red ni navegador (python -m pytest -q)."""

from __future__ import annotations

from datetime import date

from modules import bot_telegram, cv_adapter, email_generator, enricher, scraper
from modules.models import Vacante
from modules.utils import contar_palabras, normalizar


# ----------------------------------------------------------------------------- scraper
def test_mapear_columnas_por_encabezado():
    enc = ["Código", "Razón Social", "NIT", "Municipio", "Perfil del aprendiz", "Fecha Cierre", ""]
    m = scraper.mapear_columnas(enc)
    assert m == {"razon_social": 1, "nit": 2, "ciudad": 3, "fecha_limite": 5,
                 "perfil": 4, "id_portal": 0}


def test_parsear_fecha_formatos():
    assert scraper.parsear_fecha("23/10/2026") == "2026-10-23"
    assert scraper.parsear_fecha("5-1-2027 11:59 p.m.") == "2027-01-05"
    assert scraper.parsear_fecha("2026-11-02") == "2026-11-02"
    assert scraper.parsear_fecha("15 de noviembre de 2026") == "2026-11-15"
    assert scraper.parsear_fecha("3-dic-2026") == "2026-12-03"
    assert scraper.parsear_fecha("Sin fecha") == "Sin fecha"


def test_fila_a_vacante_y_enlaces():
    mapa = {"razon_social": 0, "ciudad": 1, "fecha_limite": 2, "perfil": 3}
    v = scraper.fila_a_vacante(
        ["ACME SAS ", "Girón", "30/11/2026", "Desarrollo de software"],
        mapa, ["javascript:__doPostBack('x')", "Detalle.aspx?idVacante=77"],
        "https://caprendizaje.sena.edu.co/sgva/Lista.aspx", "ADSO",
    )
    assert v and v.razon_social == "ACME SAS" and v.fecha_limite == "2026-11-30"
    assert v.enlace == "https://caprendizaje.sena.edu.co/sgva/Detalle.aspx?idVacante=77"
    assert v.id_portal == "77" and v.id == "sgva-77"
    assert scraper.fila_a_vacante(["", "x"], mapa, [], "https://x", "ADSO") is None


def test_filtros_area_y_vigencia(vacante):
    assert scraper.coincide_area(vacante, ["software"], "Análisis y Desarrollo de Software")
    otra = Vacante(razon_social="Panadería", perfil="Auxiliar de cocina", programa="Cocina")
    assert not scraper.coincide_area(otra, ["software"], "ADSO")
    vencida = Vacante(razon_social="X", fecha_limite="2020-01-01")
    assert not scraper.vigente(vencida, date(2026, 10, 23))
    assert scraper.vigente(Vacante(razon_social="X", fecha_limite="texto raro"))


def test_id_estable_sin_id_portal():
    a = Vacante(razon_social="Empresa Uno", nit="800", ciudad="Cali", perfil="dev")
    b = Vacante(razon_social="EMPRESA UNO", nit="800", ciudad="cali", perfil="dev")
    assert a.id == b.id and a.id.startswith("h-")
    assert Vacante(razon_social="X", nit="900123456-7").empresa_key == "900123456"


# ----------------------------------------------------------------------------- db
def test_db_snapshots_e_inactivacion(db, vacante):
    otra = Vacante(razon_social="Otra SAS", ciudad="Cúcuta", perfil="software")
    r1 = db.guardar_vacantes([vacante, otra], hoy=date(2026, 10, 22))
    assert r1 == {"nuevas": 2, "actualizadas": 0, "inactivadas": 0}
    r2 = db.guardar_vacantes([vacante], hoy=date(2026, 10, 23))
    assert r2 == {"nuevas": 0, "actualizadas": 1, "inactivadas": 1}
    assert [v.id for v in db.vacantes_activas()] == [vacante.id]
    assert db.fechas_snapshot() == ["2026-10-22", "2026-10-23"]


def test_db_no_inactiva_si_scraping_vacio(db, vacante):
    db.guardar_vacantes([vacante])
    db.guardar_vacantes([])
    assert len(db.vacantes_activas()) == 1


# ----------------------------------------------------------------------------- enricher
def test_elegir_sitio_oficial_ignora_directorios():
    res = [
        {"href": "https://www.einforma.co/empresa/soluciones-digitales", "title": "x", "body": ""},
        {"href": "https://www.linkedin.com/company/soluciones-digitales", "title": "x", "body": ""},
        {"href": "https://www.solucionesdigitales.co/nosotros", "title": "Soluciones Digitales",
         "body": "Casa de software"},
    ]
    sitio, perfil = enricher.elegir_sitio_oficial("Soluciones Digitales del Oriente S.A.S.", res)
    assert sitio == "https://www.solucionesdigitales.co"
    assert "einforma" in perfil


def test_es_directorio_no_confunde_dominios():
    assert enricher.es_directorio("https://co.linkedin.com/company/x")
    assert enricher.es_directorio("https://www.alcaldia.gov.co")
    assert not enricher.es_directorio("https://www.max.com.co")  # no confundir con x.com


def test_clasificar_sector_y_tecnologias():
    assert enricher.clasificar_sector("Clínica odontológica IPS de salud")["sector"] == "Salud"
    assert enricher.clasificar_sector("Somos una empresa de transporte de carga")["sector"] \
        == "Logística y transporte"
    html = '<html><title>X</title><link href="/wp-content/a.css"><meta name="description" ' \
           'content="Hacemos software"></html>'
    assert "WordPress" in enricher.detectar_tecnologias(html)
    assert enricher.extraer_meta(html)["descripcion"] == "Hacemos software"


def test_ficha_heuristica(vacante):
    res = [{"href": "https://solucionesdigitales.co", "title": "Soluciones Digitales — software",
            "body": "Desarrollo de software y transformación digital para pymes"}]
    f = enricher.ficha_heuristica(vacante, res, {}, ["React"])
    assert f.sector == "Tecnología y desarrollo de software"
    assert f.tecnologias[0] == "React" and f.tareas_aprendiz


# ----------------------------------------------------------------------------- cv_adapter
def test_terminos_sin_falsos_positivos():
    t = cv_adapter.terminos_en("JavaScript y React con APIs REST")
    assert {"JavaScript", "React", "APIs REST"} <= t and "Java" not in t


def test_orden_proyectos_prioriza_afinidad(perfil, vacante, ficha):
    req = cv_adapter.requisitos_vacante(vacante, ficha)
    orden = [p["nombre"] for p in cv_adapter.ordenar_proyectos(perfil["proyectos"], req)]
    # Pide APIs REST + Python + React + Docker + pruebas: la Agenda (FastAPI/React/Docker) gana
    assert orden[0] == "Agenda de citas para consultorio"
    assert orden[-1].startswith("Proyecto formativo")  # PHP/Laravel: menos afín

    # Una vacante centrada en Django + PostgreSQL debe priorizar el inventario
    v2 = Vacante(razon_social="X", perfil="Backend con Django y PostgreSQL, Bootstrap")
    req2 = cv_adapter.requisitos_vacante(v2, None)
    top = cv_adapter.ordenar_proyectos(perfil["proyectos"], req2)[0]["nombre"]
    assert top == "Sistema de inventario para tienda de barrio"

    # PHP/Laravel: el proyecto formativo sube al primer lugar
    v3 = Vacante(razon_social="X", perfil="Desarrollo en PHP con Laravel y MySQL")
    req3 = cv_adapter.requisitos_vacante(v3, None)
    assert cv_adapter.ordenar_proyectos(perfil["proyectos"], req3)[0]["nombre"].startswith(
        "Proyecto formativo")


def test_implicaciones_cubren_sql(perfil):
    af = cv_adapter.calcular_afinidad(perfil, {"SQL", "Python", "Flutter/Móvil"})
    assert "SQL" in af.coincidencias  # PostgreSQL/MySQL ⇒ SQL
    assert af.faltantes == ["Flutter/Móvil"] and af.puntaje == 66.7


def test_asunto_y_habilidades_plantilla(perfil, vacante, ficha):
    assert email_generator.programa_corto(perfil["programa_sena"]) == "ADSO"
    assert email_generator.enumerar(["a", "b", "c"]) == "a, b y c"
    data = email_generator.correo_plantilla(
        email_generator.contexto_prompt(perfil, vacante, ficha))
    assert data["asunto"] == "Contrato de aprendizaje ADSO – Laura Camila Rojas Pérez"
    assert "Python (Django, FastAPI)" in data["version_corta"]  # la coma interna no rompe


def test_markdown_ats_y_afinidad(perfil, vacante, ficha, tmp_path):
    res = cv_adapter.adaptar_cv(perfil, vacante, ficha, tmp_path / "cv", pdf=False)
    md = res["markdown"].read_text("utf-8")
    assert md.startswith("# Laura Camila Rojas Pérez")
    assert "|" not in md.replace(" | ", "")  # sin tablas (solo separadores de contacto)
    assert "![" not in md and "<table" not in md
    assert res["afinidad"].puntaje > 50
    assert (tmp_path / "cv" / "analisis.json").exists()


def test_markdown_a_pdf(perfil, vacante, ficha, tmp_path):
    res = cv_adapter.adaptar_cv(perfil, vacante, ficha, tmp_path / "cv", pdf=True)
    assert res["pdf"] is not None and res["pdf"].read_bytes()[:4] == b"%PDF"


# ----------------------------------------------------------------------------- correos
def test_plantilla_respeta_limites(perfil, vacante, ficha):
    ctx = email_generator.contexto_prompt(perfil, vacante, ficha)
    data = email_generator.correo_plantilla(ctx)
    assert email_generator.validar_correo(data) == []
    assert contar_palabras(data["version_corta"]) < 120
    assert contar_palabras(data["version_formal"]) < 180
    assert "Laura" in data["version_formal"] and perfil["portafolio"] in data["version_formal"]


def test_validar_correo_detecta_errores():
    largo = "palabra " * 130
    errores = email_generator.validar_correo(
        {"asunto": "x", "version_corta": largo, "version_formal": "Hola [Nombre]"}
    )
    assert any("version_corta" in e for e in errores)
    assert any("corchetes" in e for e in errores)


class LLMFalso:
    nombre = "falso:test"

    def __init__(self, respuestas):
        self.respuestas = list(respuestas)
        self.llamadas = 0

    def generar_json(self, prompt, system="", temperatura=0.6):
        self.llamadas += 1
        return self.respuestas.pop(0)


def test_generador_reintenta_y_cae_a_plantilla(settings, db, perfil, vacante):
    malo = {"asunto": "x", "version_corta": "muy " * 200, "version_formal": "ok"}
    llm = LLMFalso([malo, malo])
    gen = email_generator.EmailGenerator(settings, db, llm)
    correo = gen.generar(perfil, vacante)
    assert llm.llamadas == 2 and correo.proveedor == "plantilla"


def test_generador_acepta_llm_valido(settings, db, perfil, vacante):
    bueno = {"asunto": "Contrato de aprendizaje ADSO", "version_corta": "Hola, soy Laura.",
             "version_formal": "Respetados señores, adjunto mi hoja de vida. Laura"}
    gen = email_generator.EmailGenerator(settings, db, LLMFalso([bueno]))
    correo = gen.generar(perfil, vacante)
    assert correo.proveedor == "falso:test"
    ruta = gen.guardar(correo, vacante, settings.output_dir / "v1")
    assert db.tiene_correo(vacante.id) and ruta.exists()


# ----------------------------------------------------------------------------- telegram
def test_alertas_sin_duplicados(settings, db, vacante, ficha):
    fuera_area = Vacante(razon_social="Restaurante", perfil="cocina", programa="Cocina")
    db.guardar_vacantes([vacante, fuera_area], hoy=date(2026, 10, 22))
    db.guardar_ficha(ficha)
    pendientes = bot_telegram.vacantes_por_alertar(db, settings)
    assert [v.id for v in pendientes] == [vacante.id]
    db.registrar_alerta(vacante)
    assert bot_telegram.vacantes_por_alertar(db, settings) == []


def test_diff_dia_anterior(db, vacante):
    a = Vacante(razon_social="A SAS", perfil="software")
    db.guardar_vacantes([a], hoy=date(2026, 10, 22))
    db.guardar_vacantes([vacante], hoy=date(2026, 10, 23))
    diff = bot_telegram.comparar_con_dia_anterior(db)
    assert diff.nuevas == {vacante.id} and diff.retiradas == {a.id}


def test_formato_alerta_escapa_html(vacante, ficha):
    vacante.razon_social = "Datos <&> Cía"
    msg = bot_telegram.formatear_alerta(vacante, ficha)
    assert "Datos &lt;&amp;&gt; Cía" in msg and "Fecha límite" in msg
    assert 'href="https://caprendizaje.sena.edu.co' in msg


def test_resumen_trocea_mensajes(db):
    vs = [Vacante(razon_social=f"Empresa {i} " + "x" * 120, perfil="software") for i in range(80)]
    db.guardar_vacantes(vs)
    mensajes = bot_telegram.formatear_resumen(vs, db)
    assert len(mensajes) > 1 and all(len(m) <= 4096 for m in mensajes)


def test_normalizar():
    assert normalizar("  Análisis   y DESARROLLO ") == "analisis y desarrollo"
