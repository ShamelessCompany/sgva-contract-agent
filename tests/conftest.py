from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RAIZ))

from config import Settings  # noqa: E402
from modules.db import Database  # noqa: E402
from modules.models import FichaEmpresa, Vacante  # noqa: E402


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    s = Settings()
    s = replace(
        s,
        data_dir=tmp_path, output_dir=tmp_path / "output", logs_dir=tmp_path / "logs",
        db_path=tmp_path / "jobs.db", json_path=tmp_path / "vacantes.json",
        session_path=tmp_path / "session.json",
        perfil_path=RAIZ / "data" / "perfil_aprendiz.example.json",
        programa_formacion="Análisis y Desarrollo de Software",
        palabras_clave_area=["ADSO", "software", "desarrollo"],
        llm_provider="ninguno", gemini_api_key="", openai_api_key="",
        telegram_token="", telegram_chat_id="", delay_min=0, delay_max=0,
    )
    s.ensure_dirs()
    return s


@pytest.fixture
def db(settings: Settings) -> Database:
    return Database(settings.db_path)


@pytest.fixture
def perfil() -> dict:
    return json.loads((RAIZ / "data" / "perfil_aprendiz.example.json").read_text("utf-8"))


@pytest.fixture
def vacante() -> Vacante:
    return Vacante(
        razon_social="Soluciones Digitales del Oriente S.A.S.",
        nit="900123456-7", ciudad="Bucaramanga", fecha_limite="2099-12-31",
        perfil="Aprendiz ADSO para desarrollo de APIs REST en Python, manejo de PostgreSQL, "
               "Git y pruebas de software. Deseable React y Docker.",
        enlace="https://caprendizaje.sena.edu.co/sgva/detalle?idVacante=5521",
        programa="Análisis y Desarrollo de Software", id_portal="5521",
    )


@pytest.fixture
def ficha(vacante: Vacante) -> FichaEmpresa:
    return FichaEmpresa(
        empresa_key=vacante.empresa_key, razon_social=vacante.razon_social, nit=vacante.nit,
        sitio_web="https://solucionesdigitales.co", sector="Tecnología y desarrollo de software",
        problema_negocio="Digitalizar procesos de pymes del oriente colombiano.",
        resumen="Casa de software que desarrolla ERPs a la medida para pymes.",
        tecnologias=["Python", "Django", "PostgreSQL", "Docker"],
        tareas_aprendiz=["Desarrollo de APIs REST", "Pruebas automatizadas"],
    )
