"""
Módulo 1 — Extractor SGVA (Caprendizaje).

Automatiza con Playwright el ingreso al portal de contrato de aprendizaje y extrae las
convocatorias activas del programa de formación configurado.

Flujo:
1. Si existe `session.json`, se carga como `storage_state` y se verifica que siga vigente.
2. Si no existe (o expiró), se hace login con SENA_USER / SENA_PASSWORD leídos de `.env`.
   - Si se detecta CAPTCHA o verificación manual, se abre un navegador VISIBLE con los
     campos pre-diligenciados para que TÚ la resuelvas. El software no evade CAPTCHAs.
3. Se guarda la sesión en `session.json` (permisos 600) para no volver a loguear.
4. Se recorre la tabla de convocatorias (todas las páginas) con retardos de 2–5 s.
5. Se exporta a SQLite (`data/jobs.db`) y a `data/vacantes_activas.json`.

Los selectores CSS viven en `config/selectors.json`: si el SENA cambia el portal, solo
hay que editar ese archivo (o usar `python main.py --calibrar` para inspeccionarlo).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from datetime import date, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urljoin

from config import Settings
from modules import navegadores
from modules.db import Database
from modules.models import Vacante
from modules.utils import (
    dormir_async,
    limpiar,
    normalizar,
    polite_delay_async,
    retry_async,
    verificar_cancelacion,
)

Aviso = Callable[[str], None]


class NavegadorNoDisponible(RuntimeError):
    """No se encontró Edge, Chrome ni el Chromium de Playwright."""


async def lanzar_navegador(pw: Any, canal: str, headless: bool, slow_mo: int = 0) -> Any:
    """Lanza el navegador elegido (Edge, Chrome, Brave, Vivaldi) o, si no está instalado,
    el siguiente disponible. Ver `modules/navegadores.py`."""
    errores: list[str] = []
    for nombre, opciones in navegadores.candidatos(canal, headless):
        try:
            navegador = await pw.chromium.launch(slow_mo=slow_mo, **opciones)
            log.debug("Navegador lanzado (%s)", nombre)
            try:
                navegador.canal_sgva = nombre  # para el diagnóstico
            except AttributeError:
                pass
            return navegador
        except Exception as exc:  # noqa: BLE001
            errores.append(f"{nombre}: {str(exc).splitlines()[0]}")
    raise NavegadorNoDisponible(
        "No se pudo abrir un navegador. Instala Microsoft Edge, Google Chrome o Brave. "
        "Detalle: " + " | ".join(errores)
    )

log = logging.getLogger(__name__)

# Palabras (normalizadas) que identifican cada columna de la tabla del SGVA.
# Se compara contra el encabezado de la tabla, así el orden de columnas no importa.
COLUMNAS: dict[str, tuple[str, ...]] = {
    "razon_social": ("razon social", "empresa", "nombre empresa", "entidad", "empleador"),
    "nit": ("nit", "identificacion", "documento", "id empresa"),
    "ciudad": ("ciudad", "municipio", "ubicacion", "departamento", "lugar"),
    "fecha_limite": ("fecha limite", "fecha cierre", "cierre", "vence", "fecha fin", "hasta"),
    "perfil": ("perfil", "descripcion", "cargo", "ocupacion", "requisitos", "funciones"),
    "programa": ("programa", "formacion", "especialidad"),
    "id_portal": ("codigo", "cod.", "id vacante", "numero", "no.", "consecutivo"),
}

MESES = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "set": 9, "oct": 10, "nov": 11, "dic": 12,
}


# =============================================================================
# Funciones puras (sin navegador) — fáciles de probar con pytest
# =============================================================================
def mapear_columnas(encabezados: list[str]) -> dict[str, int]:
    """Asocia cada campo del modelo con el índice de columna cuyo encabezado coincide."""
    mapa: dict[str, int] = {}
    normalizados = [normalizar(h) for h in encabezados]
    for campo, claves in COLUMNAS.items():
        for idx, enc in enumerate(normalizados):
            if idx in mapa.values() or not enc:
                continue
            if any(clave in enc for clave in claves):
                mapa[campo] = idx
                break
    return mapa


def parsear_fecha(texto: str) -> str:
    """Convierte fechas típicas del portal a ISO (AAAA-MM-DD). Si no puede, devuelve el texto."""
    t = limpiar(texto)
    if not t:
        return ""
    # 23/10/2026, 23-10-2026, 23/10/2026 11:59 p.m.
    m = re.search(r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})", t)
    if m:
        d, mth, y = (int(x) for x in m.groups())
        try:
            return date(y, mth, d).isoformat()
        except ValueError:
            pass
    # 2026-10-23
    m = re.search(r"(\d{4})-(\d{1,2})-(\d{1,2})", t)
    if m:
        y, mth, d = (int(x) for x in m.groups())
        try:
            return date(y, mth, d).isoformat()
        except ValueError:
            pass
    # 23 de octubre de 2026 / 23-oct-2026
    m = re.search(r"(\d{1,2})\s*(?:de\s+|-)?([a-záéíóú]{3,})\.?\s*(?:de\s+|-)?(\d{4})", t, re.I)
    if m:
        mes = MESES.get(normalizar(m.group(2))[:3])
        if mes:
            try:
                return date(int(m.group(3)), mes, int(m.group(1))).isoformat()
            except ValueError:
                pass
    return t


def fila_a_vacante(
    celdas: list[str],
    mapa: dict[str, int],
    enlaces: list[str],
    base_url: str,
    programa_defecto: str,
) -> Vacante | None:
    """Construye una `Vacante` a partir de una fila de la tabla. Devuelve None si está vacía."""

    def celda(campo: str) -> str:
        idx = mapa.get(campo)
        return limpiar(celdas[idx]) if idx is not None and idx < len(celdas) else ""

    razon = celda("razon_social")
    if not razon:
        return None

    enlace = ""
    for href in enlaces:
        if href and not href.lower().startswith(("javascript:", "#", "mailto:")):
            enlace = urljoin(base_url, href)
            break

    id_portal = celda("id_portal")
    if not id_portal and enlace:
        m = re.search(r"(?:id|cod|vacante|solicitud)[^=&]*=(\d+)", enlace, re.I)
        if m:
            id_portal = m.group(1)

    return Vacante(
        razon_social=razon,
        nit=celda("nit"),
        ciudad=celda("ciudad"),
        fecha_limite=parsear_fecha(celda("fecha_limite")),
        perfil=celda("perfil"),
        enlace=enlace or base_url,
        # Solo se asigna el programa si se conoce (columna de la tabla o filtro del portal);
        # nunca por defecto, para que el filtro local por área no deje pasar todo.
        programa=celda("programa") or programa_defecto,
        id_portal=id_portal,
    )


def coincide_area(vacante: Vacante, palabras_clave: list[str], programa: str) -> bool:
    """Filtro local: la vacante menciona el programa o alguna palabra clave del área."""
    texto = normalizar(f"{vacante.programa} {vacante.perfil}")
    claves = [normalizar(programa)] + [normalizar(p) for p in palabras_clave]
    return any(c and c in texto for c in claves)


def vigente(vacante: Vacante, hoy: date | None = None) -> bool:
    """Descarta vacantes con fecha límite ISO ya vencida (si no hay fecha, se conserva)."""
    try:
        return date.fromisoformat(vacante.fecha_limite) >= (hoy or date.today())
    except ValueError:
        return True


# =============================================================================
# Scraper con Playwright
# =============================================================================
class SGVAScraper:
    """Encapsula navegador, sesión y extracción. Úsalo con `await SGVAScraper(s).run()`."""

    def __init__(self, settings: Settings, aviso: Aviso | None = None) -> None:
        self.s = settings
        # Mensajes que requieren acción del usuario (consola en CLI, ventana en la app)
        self.aviso: Aviso = aviso or (lambda msg: print("\n" + "=" * 70 + f"\n{msg}\n" + "=" * 70))
        self.sel: dict[str, Any] = settings.load_selectors()
        self._pw: Any = None
        self._browser: Any = None
        self.context: Any = None
        self.page: Any = None
        self._filtrado_en_portal = False

    # ------------------------------------------------------------- navegador
    async def _abrir(self, headless: bool, usar_sesion: bool = True) -> None:
        from playwright.async_api import async_playwright

        if self._pw is None:
            self._pw = await async_playwright().start()
        await self._cerrar_navegador()
        self._browser = await lanzar_navegador(self._pw, self.s.browser_channel, headless)
        estado = (
            str(self.s.session_path) if usar_sesion and self.s.session_path.exists() else None
        )
        opciones = navegadores.opciones_contexto(headless)
        if headless:
            # El modo oculto se anuncia como «HeadlessChrome»: se usa el UA real del mismo
            # navegador sin esa marca (antes se usaba uno inventado que no coincidía).
            prueba = await self._browser.new_page()
            ua = await prueba.evaluate("navigator.userAgent")
            await prueba.close()
            opciones["user_agent"] = ua.replace("HeadlessChrome", "Chrome")
        self.context = await self._browser.new_context(storage_state=estado, **opciones)
        self.context.set_default_timeout(self.s.timeout_ms)
        self.page = await self.context.new_page()

    async def _cerrar_navegador(self) -> None:
        if self._browser is not None:
            try:
                await self._browser.close()
            except Exception:  # noqa: BLE001 - el navegador puede estar ya cerrado
                pass
            self._browser = None

    async def cerrar(self) -> None:
        await self._cerrar_navegador()
        if self._pw is not None:
            await self._pw.stop()
            self._pw = None

    async def _pausa(self) -> None:
        await polite_delay_async(self.s.delay_min, self.s.delay_max)

    @retry_async(intentos=3, backoff_base=4.0)
    async def _ir(self, url: str) -> None:
        """Navegación con reintentos (maneja caídas de red y timeouts del portal)."""
        url = (url or "").strip()
        if not url:
            url = self.s.sgva_login_url
        if not url.startswith("http://") and not url.startswith("https://"):
            url = f"https://{url}"
        if "caprendizaje.sena.edu.co" in url:
            url = url.replace("http://", "https://")
            partes_validas = ("login", "detalle", "consulta", "solicitud", "convocatoria", "aspx")
            if not any(p in url.lower() for p in partes_validas):
                url = "https://caprendizaje.sena.edu.co/sgva/SGVA_Diseno/pag/login.aspx"
        log.info("Navegando a: %s", url)
        try:
            await self.page.goto(url, wait_until="domcontentloaded", timeout=45000)
        except Exception as exc:
            log.warning("Fallo al navegar a %s: %s", url, exc)
            raise
        try:
            await self.page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass

    async def _primero_visible(self, candidatos: list[str] | str, timeout: int = 3000) -> Any:
        """Devuelve el primer locator visible de una lista de selectores candidatos."""
        if isinstance(candidatos, str):
            candidatos = [candidatos]
        for selector in candidatos:
            loc = self.page.locator(selector).first
            try:
                await loc.wait_for(state="visible", timeout=timeout)
                return loc
            except Exception:  # noqa: BLE001
                continue
        return None

    async def _hay(self, candidatos: list[str], pagina: Any = None) -> bool:
        for selector in candidatos:
            try:
                if await (pagina or self.page).locator(selector).count() > 0:
                    return True
            except Exception:  # noqa: BLE001
                continue
        return False

    # ------------------------------------------------------------- sesión / login
    async def _sesion_activa(self) -> bool:
        login = self.sel["login"]
        if await self._hay(login.get("indicador_sesion", [])):
            return True
        # Si hay un campo de contraseña en pantalla, estamos en el login: no hay sesión
        return not await self._hay(login.get("campo_clave", []))

    async def _guardar_sesion(self) -> None:
        await self.context.storage_state(path=str(self.s.session_path))
        try:
            os.chmod(self.s.session_path, 0o600)  # solo lectura/escritura del dueño
        except OSError:
            pass
        log.info("Sesión guardada en %s", self.s.session_path.name)

    async def _elegir_rol(self) -> None:
        """Pulsa la pestaña «Aprendices» del formulario (la página abre en «Empresas»)."""
        pestana = await self._primero_visible(self.sel["login"].get("pestana_rol", []), timeout=1500)
        if pestana:
            await pestana.click()
            await asyncio.sleep(0.8)
        else:
            log.debug("No se encontró la pestaña de rol; se asume formulario de aprendiz.")

    async def _llenar_credenciales(self) -> bool:
        login = self.sel["login"]
        await self._elegir_rol()
        if login.get("selector_tipo_documento") and login.get("valor_tipo_documento"):
            try:
                await self.page.select_option(
                    login["selector_tipo_documento"], label=login["valor_tipo_documento"]
                )
            except Exception as exc:  # noqa: BLE001
                log.debug("No se pudo seleccionar tipo de documento: %s", exc)
        usuario = await self._primero_visible(login["campo_usuario"], timeout=8000)
        clave = await self._primero_visible(login["campo_clave"], timeout=3000)
        if not usuario or not clave:
            return False
        # Escritura con cadencia humana; las credenciales solo se envían al portal del SENA.
        await usuario.fill("")
        await usuario.type(self.s.sena_user, delay=60)
        await asyncio.sleep(0.6)
        await clave.fill("")
        await clave.type(self.s.sena_password, delay=60)
        return True

    async def asegurar_sesion(self) -> None:
        """Garantiza una sesión válida: reutiliza session.json o hace login."""
        usa_sesion = self.s.session_path.exists()
        await self._abrir(headless=self.s.headless, usar_sesion=usa_sesion)
        await self._ir(self.s.sgva_vacantes_url or self.s.sgva_login_url)
        await self._pausa()

        if usa_sesion and await self._sesion_activa():
            log.info("Sesión reutilizada desde session.json (sin nuevo login).")
            return
        if usa_sesion:
            log.info("La sesión guardada expiró. Se realizará login nuevamente.")
            self.s.session_path.unlink(missing_ok=True)
            await self._abrir(headless=self.s.headless, usar_sesion=False)

        await self._login()

    async def _login(self) -> None:
        if not self.s.credenciales_configuradas:
            log.warning("SENA_USER/SENA_PASSWORD no están en .env → login manual.")
            await self._login_manual()
            return

        await self._ir(self.s.sgva_login_url)
        await self._pausa()
        captchas = self.sel["login"].get("indicadores_captcha", [])

        if await self._hay(captchas):
            log.warning("CAPTCHA/verificación detectada antes del login.")
            await self._login_manual()
            return

        if not await self._llenar_credenciales():
            log.warning("No se encontró el formulario de login con los selectores actuales.")
            await self._login_manual()
            return

        await self._pausa()
        boton = await self._primero_visible(self.sel["login"]["boton_ingresar"])
        if boton:
            await boton.click()
        else:
            await self.page.keyboard.press("Enter")

        try:
            await self.page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        await self._pausa()

        if await self._sesion_activa():
            log.info("Login exitoso.")
            await self._guardar_sesion()
            return

        if await self._hay(captchas):
            log.warning("El portal solicitó verificación manual tras el login.")
        else:
            log.warning("No se confirmó la sesión (¿credenciales o selectores?).")
        await self._login_manual()

    async def _login_manual(self) -> None:
        """Abre un navegador visible para que el usuario complete el login / CAPTCHA."""
        espera_min = int(self.sel["login"].get("espera_manual_min", 5))
        await self._abrir(headless=False, usar_sesion=False)
        await self._ir(self.s.sgva_login_url)
        if self.s.credenciales_configuradas:
            await self._llenar_credenciales()
        else:
            await self._elegir_rol()
        mensaje = (
            "VERIFICACIÓN MANUAL REQUERIDA\n"
            "Completa el inicio de sesión (y el CAPTCHA si aparece) en la ventana del "
            f"navegador que se abrió. Tienes {espera_min} minutos; el proceso continuará "
            "solo en cuanto detecte la sesión."
        )
        log.warning(mensaje.replace("\n", " — "))
        self.aviso(mensaje)
        limite = asyncio.get_running_loop().time() + espera_min * 60
        indicador = self.sel["login"].get("indicador_sesion", [])
        while asyncio.get_running_loop().time() < limite:
            await dormir_async(3)
            if not self.context.pages:
                raise RuntimeError("Se cerró el navegador antes de completar el inicio de sesión.")
            try:
                # El portal puede abrir el panel en otra pestaña: se revisan todas.
                for pagina in reversed(self.context.pages):
                    if await self._hay(indicador, pagina):
                        self.page = pagina
                        await self._guardar_sesion()
                        # Se sigue en ESTA ventana: cerrarla y abrir otra perdía la sesión
                        # (el balanceador del portal la ata al navegador por pocos minutos).
                        log.info("Sesión confirmada. La búsqueda continúa en esta misma ventana.")
                        return
            except Exception:  # noqa: BLE001 - la página puede estar navegando
                continue
        raise TimeoutError("No se completó el login manual a tiempo.")

    # ------------------------------------------------------------- extracción
    async def _ir_a_convocatorias(self) -> None:
        vac = self.sel["vacantes"]
        if self.s.sgva_vacantes_url:
            await self._ir(self.s.sgva_vacantes_url)
        else:
            # Navegación por menú desde el inicio: lista de pasos a clicar en orden
            await self._ir(self.s.sgva_login_url)
            await self._pausa()
            for paso in vac.get("pasos_menu", []):
                loc = await self._primero_visible(paso, timeout=8000)
                if not loc:
                    raise RuntimeError(f"No se encontró el paso de menú: {paso}")
                await loc.click()
                await self._pausa()
        await self._pausa()

        filtro = vac.get("filtro_programa")
        if filtro:
            campo = await self._primero_visible(filtro, timeout=5000)
            if campo:
                tag = await campo.evaluate("e => e.tagName.toLowerCase()")
                if tag == "select":
                    opciones: list[str] = await campo.evaluate(
                        "e => Array.from(e.options).map(o => o.textContent.trim())"
                    )
                    objetivo = normalizar(self.s.programa_formacion)
                    elegida = next((o for o in opciones if objetivo in normalizar(o)), None)
                    if elegida:
                        await campo.select_option(label=elegida)
                else:
                    await campo.fill(self.s.programa_formacion)
                buscar = await self._primero_visible(vac.get("boton_buscar", []), timeout=3000)
                if buscar:
                    await buscar.click()
                    try:
                        await self.page.wait_for_load_state("networkidle", timeout=20000)
                    except Exception:  # noqa: BLE001
                        pass
                await self._pausa()
                self._filtrado_en_portal = True
                return
        self._filtrado_en_portal = False

    async def _leer_tabla(self) -> tuple[list[str], list[dict[str, Any]]]:
        """Lee encabezados y filas de la tabla de convocatorias en la página actual."""
        js = """
        (selector) => {
          const tabla = document.querySelector(selector);
          if (!tabla) return null;
          let headers = Array.from(tabla.querySelectorAll('thead th'));
          if (!headers.length)
            headers = Array.from(tabla.querySelectorAll('tr:first-child th, tr:first-child td'));
          const filas = Array.from(tabla.querySelectorAll('tbody tr, tr'))
            .filter(tr => tr.querySelectorAll('td').length > 1 && !tr.querySelector('th'))
            .filter(tr => !tr.querySelector('table'));  // excluye fila de paginador anidada
          return {
            headers: headers.map(h => h.innerText.trim()),
            rows: filas.map(tr => ({
              cells: Array.from(tr.querySelectorAll('td')).map(td => td.innerText.trim()),
              links: Array.from(tr.querySelectorAll('a[href]')).map(a => a.href),
            })),
          };
        }
        """
        for selector in self.sel["vacantes"]["tabla"]:
            datos = await self.page.evaluate(js, selector)
            if datos and datos["rows"]:
                return datos["headers"], datos["rows"]
        return [], []

    async def _siguiente_pagina(self) -> bool:
        boton = await self._primero_visible(
            self.sel["vacantes"].get("siguiente_pagina", []), timeout=2000
        )
        if not boton:
            return False
        clase = (await boton.get_attribute("class")) or ""
        deshabilitado = await boton.get_attribute("disabled")
        if "disabled" in clase.lower() or deshabilitado is not None:
            return False
        await boton.click()
        try:
            await self.page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:  # noqa: BLE001
            pass
        return True

    async def _detalle(self, vacante: Vacante) -> None:
        """Opcional: abre la solicitud para leer el perfil completo (con retardo ético)."""
        selector = self.sel["vacantes"].get("detalle_perfil")
        if not selector or not vacante.enlace or vacante.enlace == self.page.url:
            return
        detalle = await self.context.new_page()
        try:
            await self._pausa()
            await detalle.goto(vacante.enlace, wait_until="domcontentloaded")
            for sel in selector:
                loc = detalle.locator(sel).first
                if await loc.count():
                    texto = limpiar(await loc.inner_text())
                    if len(texto) > len(vacante.perfil):
                        vacante.perfil = texto[:4000]
                    break
        except Exception as exc:  # noqa: BLE001
            log.debug("Detalle no disponible para %s: %s", vacante.razon_social, exc)
        finally:
            await detalle.close()

    async def extraer(self) -> list[Vacante]:
        await self._ir_a_convocatorias()
        vacantes: dict[str, Vacante] = {}
        firmas_vistas: set[str] = set()
        mapa: dict[str, int] = {}

        for pagina in range(1, self.s.max_paginas + 1):
            verificar_cancelacion()
            encabezados, filas = await self._leer_tabla()
            if not filas:
                log.warning("Página %d sin filas. ¿Selector de tabla correcto?", pagina)
                break
            if encabezados and not mapa:
                mapa = mapear_columnas(encabezados)
                manual = self.sel["vacantes"].get("columnas_manual") or {}
                mapa.update({k: int(v) for k, v in manual.items()})
                log.info("Columnas detectadas: %s", mapa)
                if "razon_social" not in mapa:
                    raise RuntimeError(
                        "No se identificó la columna de Razón Social. Ajusta "
                        "'columnas_manual' en config/selectors.json o usa --calibrar."
                    )

            firma = json.dumps(filas[0]["cells"], ensure_ascii=False)
            if firma in firmas_vistas:  # el paginador no avanzó: evitar bucle infinito
                break
            firmas_vistas.add(firma)

            for fila in filas:
                if fila["cells"] == encabezados:  # fila de encabezado sin <th>
                    continue
                v = fila_a_vacante(
                    fila["cells"], mapa, fila["links"], self.page.url,
                    self.s.programa_formacion if self._filtrado_en_portal else "",
                )
                if v:
                    vacantes[v.id] = v
            log.info("Página %d: %d filas (acumuladas %d)", pagina, len(filas), len(vacantes))

            await self._pausa()
            if not await self._siguiente_pagina():
                break

        resultado = list(vacantes.values())
        if self.sel["vacantes"].get("detalle_perfil"):
            for v in resultado:
                await self._detalle(v)

        if not getattr(self, "_filtrado_en_portal", False):
            antes = len(resultado)
            resultado = [
                v for v in resultado
                if coincide_area(v, self.s.palabras_clave_area, self.s.programa_formacion)
            ]
            log.info("Filtro local por área: %d → %d vacantes", antes, len(resultado))

        resultado = [v for v in resultado if vigente(v)]
        return resultado

    async def run(self) -> list[Vacante]:
        try:
            await self.asegurar_sesion()
            vacantes = await self.extraer()
            await self._guardar_sesion()  # refresca cookies tras navegar
            return vacantes
        finally:
            await self.cerrar()

    # ------------------------------------------------------------- calibración
    async def calibrar(self, destino: Path, esperar: Callable[[], Any] | None = None) -> dict:
        """Modo asistido: el usuario navega hasta la tabla y se vuelca HTML + captura + tablas.

        `esperar` es una función bloqueante que retorna cuando el usuario indica que ya ve la
        tabla (por defecto, esperar ENTER en la consola; en la app, un botón "Continuar").
        """
        destino.mkdir(parents=True, exist_ok=True)
        if esperar is None:
            def esperar() -> None:
                print("\nNavega (e inicia sesión si hace falta) hasta la tabla de convocatorias.\n"
                      "Cuando la veas en pantalla, vuelve aquí y presiona ENTER...")
                input()
        try:
            await self._abrir(headless=False, usar_sesion=self.s.session_path.exists())
            await self._ir(self.s.sgva_vacantes_url or self.s.sgva_login_url)
            await asyncio.get_running_loop().run_in_executor(None, esperar)
            verificar_cancelacion()
            if self.context.pages:  # la tabla pudo quedar en otra pestaña
                self.page = self.context.pages[-1]
            await self._guardar_sesion()
            sello = datetime.now().strftime("%Y%m%d_%H%M%S")
            (destino / f"convocatorias_{sello}.html").write_text(
                await self.page.content(), encoding="utf-8"
            )
            await self.page.screenshot(
                path=str(destino / f"convocatorias_{sello}.png"), full_page=True
            )
            tablas = await self.page.evaluate(
                """() => Array.from(document.querySelectorAll('table')).map((t, i) => ({
                    indice: i, id: t.id, clases: t.className,
                    filas: t.querySelectorAll('tr').length,
                    encabezados: Array.from(t.querySelectorAll('th'))
                        .map(h => h.innerText.trim()).slice(0, 15),
                }))"""
            )
            tablas = [t for t in tablas if t["filas"] > 1]
            resumen = destino / f"tablas_{sello}.json"
            resultado = {"url": self.page.url, "tablas": tablas}
            resumen.write_text(json.dumps(resultado, ensure_ascii=False, indent=2), encoding="utf-8")
            resultado["resumen"] = resumen
            resultado["columnas"] = {
                t["indice"]: mapear_columnas(t["encabezados"]) for t in tablas if t["encabezados"]
            }
            return resultado
        finally:
            await self.cerrar()


# =============================================================================
# API pública del módulo
# =============================================================================
def run_scraper(settings: Settings, db: Database, aviso: Aviso | None = None) -> list[Vacante]:
    """Ejecuta el scraping completo y persiste en SQLite + JSON."""
    vacantes = asyncio.run(SGVAScraper(settings, aviso).run())
    if not vacantes:
        log.warning("No se extrajeron vacantes; no se modifica la base de datos.")
        return []
    resumen = db.guardar_vacantes(vacantes)
    total = db.exportar_json(settings.json_path)
    log.info(
        "Scraping OK: %d vacantes (%d nuevas, %d actualizadas, %d inactivadas). JSON: %d",
        len(vacantes), resumen["nuevas"], resumen["actualizadas"], resumen["inactivadas"], total,
    )
    return vacantes


def run_calibracion(
    settings: Settings, esperar: Callable[[], Any] | None = None, aviso: Aviso | None = None
) -> dict:
    """Devuelve {"url", "tablas", "columnas", "resumen"} de la página donde quedó el usuario."""
    return asyncio.run(
        SGVAScraper(settings, aviso).calibrar(settings.data_dir / "debug", esperar)
    )
