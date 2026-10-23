"""Pruebas de la capa de la app de escritorio (sin interfaz gráfica)."""

from __future__ import annotations

import json
import threading
import time

import pytest

from modules import app_state, pipeline, utils
from modules.models import Vacante


class AlmacenFalso(app_state.AlmacenSecretos):
    def __init__(self):  # noqa: D107 - sin keyring real
        self.disponible = True
        self._memoria = {}

    def leer(self, nombre):
        return self._memoria.get(nombre, "")

    def escribir(self, nombre, valor):
        self._memoria[nombre] = valor
        return True


def test_ajustes_no_guardan_secretos_en_json(tmp_path):
    almacen = AlmacenFalso()
    a = app_state.AjustesApp(sena_user="1098", sena_password="clave-super-secreta",
                             gemini_api_key="AIza-xyz", telegram_chat_id="42")
    assert a.guardar(tmp_path, almacen)
    crudo = (tmp_path / "ajustes.json").read_text("utf-8")
    assert "clave-super-secreta" not in crudo and "AIza-xyz" not in crudo
    assert json.loads(crudo)["sena_user"] == "1098"
    b = app_state.AjustesApp.cargar(tmp_path, almacen)
    assert b.sena_password == "clave-super-secreta" and b.telegram_chat_id == "42"


def test_no_recordar_borra_secretos(tmp_path):
    almacen = AlmacenFalso()
    app_state.AjustesApp(sena_password="x").guardar(tmp_path, almacen)
    app_state.AjustesApp(sena_password="x", recordar_secretos=False).guardar(tmp_path, almacen)
    assert almacen.leer("sena_password") == ""


def test_ajustes_a_settings():
    s = app_state.AjustesApp(palabras_clave="software, redes ,", navegador="chrome",
                             mostrar_navegador=True).a_settings()
    assert s.palabras_clave_area == ["software", "redes"]
    assert s.browser_channel == "chrome" and s.headless is False


def test_lista_comas_respeta_parentesis():
    assert app_state.lista_comas("Python (Django, FastAPI), React; Git\nSQL") == [
        "Python (Django, FastAPI)", "React", "Git", "SQL"]


def test_ida_y_vuelta_experiencia_y_educacion():
    exp = [{"cargo": "Auxiliar", "empresa": "ACME", "periodo": "2024", "logros": ["a", "b"]}]
    assert app_state.parse_experiencia(app_state.format_experiencia(exp)) == exp
    edu = [{"titulo": "ADSO", "institucion": "SENA", "periodo": "2025 – 2027"}]
    assert app_state.parse_educacion(app_state.format_educacion(edu)) == edu
    assert app_state.parse_educacion("Bachiller")[0] == {"titulo": "Bachiller", "institucion": "",
                                                          "periodo": ""}


def test_problemas_perfil(perfil):
    assert app_state.problemas_perfil(perfil) == []
    assert "tu nombre" in app_state.problemas_perfil(app_state.perfil_vacio())


def test_palabras_sugeridas():
    assert "ADSO" in app_state.palabras_sugeridas("Análisis y Desarrollo de Software")
    assert app_state.palabras_sugeridas("Gestión Logística Internacional") == \
        "gestión,logística,internacional"


def test_cancelacion_interrumpe_pausas():
    utils.CANCELAR.clear()
    threading.Timer(0.2, utils.CANCELAR.set).start()
    inicio = time.monotonic()
    with pytest.raises(utils.Cancelado):
        utils.polite_delay(5, 5)
    assert time.monotonic() - inicio < 1.5
    utils.CANCELAR.clear()


def test_cancelado_no_lo_atrapa_except_exception():
    utils.CANCELAR.set()
    try:
        with pytest.raises(utils.Cancelado):
            try:
                utils.verificar_cancelacion()
            except Exception:  # noqa: BLE001 - así son los bloques defensivos del pipeline
                pytest.fail("Cancelado fue atrapado por except Exception")
    finally:
        utils.CANCELAR.clear()


def test_ranking_acumulativo_y_solo_activas(settings, db, vacante):
    otra = Vacante(razon_social="Otra Software SAS", perfil="desarrollo de software con PHP",
                   fecha_limite="2099-01-01", id_portal="9")
    db.guardar_vacantes([vacante, otra])
    r1 = pipeline.paso_generar(settings, db, pdf=False)
    assert {r["empresa"] for r in r1} == {vacante.razon_social, otra.razon_social}
    assert r1[0]["afinidad"] >= r1[1]["afinidad"]
    # Segunda corrida: nada nuevo que generar, pero el ranking conserva ambas
    r2 = pipeline.paso_generar(settings, db, pdf=False)
    assert len(r2) == 2
    # La vacante retirada del portal desaparece del ranking
    db.guardar_vacantes([vacante])
    assert [r["vacante_id"] for r in pipeline.leer_ranking(settings, db)] == [vacante.id]


def test_pdf_con_navegador(monkeypatch, tmp_path):
    """Motor de PDF de la app de escritorio (sin WeasyPrint)."""
    import builtins

    from modules import cv_adapter

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch().close()
    except Exception:  # noqa: BLE001
        pytest.skip("Chromium de Playwright no instalado")

    original = builtins.__import__

    def sin_weasyprint(name, *args, **kwargs):
        if name.startswith("weasyprint"):
            raise ImportError("simulado")
        return original(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", sin_weasyprint)
    md = tmp_path / "cv.md"
    md.write_text("# Laura Rojas\n\n## Proyectos\n\n- Inventario con Django\n", "utf-8")
    pdf = cv_adapter.markdown_a_pdf(md)
    assert pdf and pdf.read_bytes()[:4] == b"%PDF"
