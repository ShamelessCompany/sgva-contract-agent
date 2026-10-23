"""Prueba de integración del scraper contra un portal SGVA SIMULADO en localhost.

No toca el portal real del SENA. Se omite si Chromium de Playwright no está instalado
(`python -m playwright install chromium`).
"""

from __future__ import annotations

import threading
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

import pytest

from modules import scraper

FILAS = {
    1: [
        ("101", "Soluciones Digitales SAS", "900111222-1", "Bucaramanga",
         "Aprendiz ADSO desarrollo de software web", "30/12/2099"),
        ("102", "Panadería La Espiga", "800333444-2", "Girón",
         "Auxiliar de cocina y panadería", "30/12/2099"),
    ],
    2: [
        ("103", "Datos y Nube Ltda", "901555666-3", "Floridablanca",
         "Análisis y Desarrollo de Software: APIs y bases de datos", "15/11/2099"),
        ("104", "Vieja Software SAS", "900777888-4", "Cúcuta",
         "Desarrollo de software (convocatoria cerrada)", "01/01/2020"),
    ],
}

LOGIN = """<html><body><form method="post" action="/sgva/login">
<select id="ddlTipoDoc"><option>Cédula de Ciudadanía</option></select>
<input type="text" id="txtUsuario" name="u"><input type="password" name="p">
<input type="submit" value="Ingresar"></form></body></html>"""


def pagina_vacantes(n: int) -> str:
    filas = "".join(
        f"<tr><td>{c}</td><td>{r}</td><td>{nit}</td><td>{ci}</td><td>{p}</td><td>{f}</td>"
        f"<td><a href='/sgva/detalle?idVacante={c}'>Ver</a></td></tr>"
        for c, r, nit, ci, p, f in FILAS[n]
    )
    sig = f"<a href='/sgva/vacantes?page={n + 1}'>Siguiente</a>" if n + 1 in FILAS else ""
    return f"""<html><body><a href="/sgva/salir">Cerrar sesión</a>
<table id="gvVacantes"><thead><tr><th>Código</th><th>Razón Social</th><th>NIT</th>
<th>Ciudad</th><th>Perfil</th><th>Fecha límite</th><th></th></tr></thead>
<tbody>{filas}</tbody></table>{sig}</body></html>"""


class Portal(BaseHTTPRequestHandler):
    logins = 0

    def log_message(self, *a):  # silencio
        pass

    def _html(self, cuerpo: str, cookie: str | None = None) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(cuerpo.encode())

    def do_GET(self):
        url = urlparse(self.path)
        logueado = "sid=ok" in (self.headers.get("Cookie") or "")
        if url.path.startswith("/sgva/vacantes") and logueado:
            n = int(parse_qs(url.query).get("page", ["1"])[0])
            self._html(pagina_vacantes(n))
        else:
            self._html(LOGIN)

    def do_POST(self):
        largo = int(self.headers.get("Content-Length", 0))
        datos = parse_qs(self.rfile.read(largo).decode())
        if datos.get("u") == ["1098000000"] and datos.get("p") == ["secreta"]:
            Portal.logins += 1
            self.send_response(302)
            self.send_header("Set-Cookie", "sid=ok; Path=/; Max-Age=3600")
            self.send_header("Location", "/sgva/vacantes")
            self.end_headers()
        else:
            self._html(LOGIN)


@pytest.fixture
def portal():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Portal)
    hilo = threading.Thread(target=srv.serve_forever, daemon=True)
    hilo.start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def _chromium_disponible() -> bool:
    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            p.chromium.launch().close()
        return True
    except Exception:  # noqa: BLE001
        return False


@pytest.mark.skipif(not _chromium_disponible(), reason="Chromium de Playwright no instalado")
def test_scraper_login_sesion_paginacion_y_filtros(settings, db, portal):
    s = replace(
        settings, sena_user="1098000000", sena_password="secreta",
        sgva_login_url=f"{portal}/sgva/", sgva_vacantes_url=f"{portal}/sgva/vacantes",
        headless=True, timeout_ms=8000,
    )
    Portal.logins = 0

    # 1) Primera ejecución: login con credenciales y creación de session.json
    vacantes = scraper.run_scraper(s, db)
    nombres = sorted(v.razon_social for v in vacantes)
    # La panadería se filtra por área y "Vieja Software" por fecha vencida
    assert nombres == ["Datos y Nube Ltda", "Soluciones Digitales SAS"]
    assert Portal.logins == 1 and s.session_path.exists()
    v = next(v for v in vacantes if v.id_portal == "101")
    assert v.enlace.endswith("/sgva/detalle?idVacante=101") and v.fecha_limite == "2099-12-30"
    assert s.json_path.exists() and len(db.vacantes_activas()) == 2

    # 2) Segunda ejecución: reutiliza session.json sin volver a loguear
    scraper.run_scraper(s, db)
    assert Portal.logins == 1
