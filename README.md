# SGVA-Matchmaker

**Automatización de búsqueda de contratos de aprendizaje SENA, análisis empresarial y postulación personalizada.**
Una iniciativa de código abierto de **Shameless Company**.

> ⚠️ **Proyecto independiente — NO oficial del SENA.** Lee el [Descargo de Responsabilidad Institucional](#descargo-de-responsabilidad-institucional) antes de usarlo.

---

## ¿Qué hace?

```
┌────────────┐   ┌─────────────┐   ┌──────────────────────────┐   ┌──────────────┐
│ 1. Scraper │──▶│ 2. Enricher │──▶│ 3. Correos + 4. CV (ATS) │──▶│ 5. Telegram  │
│  SGVA      │   │  empresas   │   │  por cada vacante         │   │  alertas     │
└────────────┘   └─────────────┘   └──────────────────────────┘   └──────────────┘
       └───────────────── data/jobs.db (SQLite) + data/vacantes_activas.json ─────┘
```

| Módulo | Archivo | Resultado |
|---|---|---|
| Extractor SGVA | `modules/scraper.py` | Vacantes activas de tu programa (razón social, NIT, ciudad, fecha límite, perfil, enlace) |
| Investigador empresarial | `modules/enricher.py` | Ficha: sitio web, sector, problema de negocio, tecnologías probables, tareas del aprendiz |
| Generador de correos | `modules/email_generator.py` | `version_corta` (<120 palabras) y `version_formal` (<180) en JSON |
| Adaptador de hoja de vida | `modules/cv_adapter.py` | CV Markdown de una columna + PDF, con proyectos reordenados por afinidad |
| Monitor y alertas | `modules/bot_telegram.py` | Aviso por Telegram de vacantes nuevas, sin duplicados |
| Orquestador | `main.py` | CLI que encadena todo |
| App de escritorio | `app_gui.py` | Ventana con formularios y botón «Buscar vacantes» (se empaqueta como `.exe`) |

Por cada vacante se crea una carpeta en `output/`:

```
output/soluciones-digitales-sas_sgva-5521/
├── hoja_de_vida.md     # CV ATS adaptado a esta vacante
├── hoja_de_vida.pdf    # listo para adjuntar
├── correos.json        # asunto + version_corta + version_formal
└── analisis.json       # % de afinidad, coincidencias y brechas a reforzar
```

y un `output/ranking.json` con las vacantes ordenadas por afinidad con tu perfil.

---

## App de escritorio (Windows, sin instalar Python)

### Para el aprendiz

1. Descarga `SGVA-Matchmaker.exe` y ábrelo. La primera vez, Windows puede mostrar **«Windows protegió su PC»** porque el ejecutable no está firmado: pulsa **Más información → Ejecutar de todas formas**.
2. Lee y acepta el descargo de responsabilidad.
3. **Mi perfil**: llena tus datos, habilidades y proyectos. Pulsa **Guardar perfil**.
4. **Cuenta y ajustes**: escribe tu número de identificación y contraseña de Caprendizaje. La primera vez pulsa **Detectar la página automáticamente**: se abre el navegador, inicias sesión, vas a la tabla de convocatorias y pulsas «Ya veo la tabla».
5. **Buscar vacantes**: pulsa el botón. Cada vacante de tu área aparece con su % de afinidad, su hoja de vida en PDF y dos correos listos para copiar.

Requisitos: Windows 10/11 con **Microsoft Edge** (viene instalado) o Google Chrome. Nada más.

| Qué | Dónde queda |
|---|---|
| Contraseña de Caprendizaje y claves de API | Administrador de credenciales de Windows (cifrado con tu usuario) |
| Base de datos, cookies de sesión, ajustes, registro | `%LOCALAPPDATA%\SGVA-Matchmaker` |
| Hojas de vida y correos generados | `Documentos\SGVA-Matchmaker` |

Si algo falla, en **Acerca de → Diagnóstico del equipo** se revisan el navegador, la generación de PDF, el almacén de contraseñas y la conexión con el portal.

### Para quien construye y distribuye el `.exe`

**Opción A, en tu PC con Windows:** instala [Python 3.12](https://www.python.org/downloads/) (marca «Add to PATH») y haz doble clic en `build_exe.bat`. Al final queda `dist\SGVA-Matchmaker.exe` (~95 MB), con autoprueba y SHA256 incluidos. `build_exe.bat onedir` genera una carpeta en lugar de un solo archivo: arranca más rápido y la marcan menos los antivirus.

**Opción B, sin Windows:** sube el repositorio a GitHub y ejecuta *Actions → Build Windows → Run workflow*. El `.exe` queda en *Artifacts*. Si subes una etiqueta (`git tag v1.1.0 && git push --tags`), se publica en *Releases*.

El ejecutable no incluye navegador (usa Edge o Chrome del equipo) ni WeasyPrint (los PDF se imprimen con ese mismo navegador). La autoprueba se puede repetir en cualquier PC con `SGVA-Matchmaker.exe --autoprueba` y escribe `autoprueba.json` en la carpeta de datos.

**Antes de distribuir o vender:**

- **Firma de código.** Sin firma, SmartScreen y algunos antivirus advertirán o bloquearán el `.exe` (PyInstaller genera muchos falsos positivos). Un certificado de firma de código (OV/EV) o [Azure Trusted Signing](https://learn.microsoft.com/azure/trusted-signing/) lo evita casi del todo. Publica siempre el SHA256.
- **No incluyas tus claves.** Cada usuario pone su propia clave de Gemini/OpenAI y su token de Telegram en la app. Cualquier clave metida en el `.exe` se puede extraer.
- **Marca.** El nombre del producto contiene «SGVA», que es un sistema del SENA. Para una venta comercial conviene un nombre propio (p. ej. «Matchmaker de Aprendices by Shameless Company») y no usar logos ni colores institucionales.
- **Términos del portal.** El uso automatizado del portal Caprendizaje depende de sus términos de uso. Al distribuir la herramienta asumes más responsabilidad que en un uso personal: revísalos y consulta con un abogado si vas a cobrar por ella.
- **Licencia.** El código es MIT: puedes venderlo, pero debes conservar el aviso de copyright y la licencia (la app la incluye).

---

## Instalación (desarrolladores / terminal)

Requisitos: **Python 3.10+** y Git.

```bash
git clone <URL-del-repositorio> sgva-matchmaker
cd sgva-matchmaker

python -m venv .venv
# Windows:  .venv\Scripts\activate
# Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
python -m playwright install chromium
```

**PDF de la hoja de vida.** WeasyPrint necesita la librería Pango del sistema:

| Sistema | Comando |
|---|---|
| Ubuntu/Debian | `sudo apt install libpango-1.0-0 libpangoft2-1.0-0` |
| macOS | `brew install pango` |
| Windows | Instala [MSYS2](https://www.msys2.org/) y ejecuta `pacman -S mingw-w64-x86_64-pango` (ver [guía de WeasyPrint](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html)) |

Si WeasyPrint no está disponible, el programa intenta con `pandoc` (+ `typst`, `wkhtmltopdf` o `xelatex`). Como último recurso, el Markdown siempre se genera y puedes convertirlo a mano:

```bash
pandoc output/<carpeta>/hoja_de_vida.md -o hoja_de_vida.pdf --pdf-engine=typst
```

---

## Configuración

### 1. Variables de entorno

```bash
cp .env.example .env
```

Edita `.env`. Lo mínimo:

| Variable | Para qué |
|---|---|
| `SENA_USER`, `SENA_PASSWORD` | Login en Caprendizaje (opcional: si las dejas vacías, inicias sesión a mano la primera vez) |
| `SGVA_VACANTES_URL` | URL directa de la tabla de convocatorias (recomendado; ver *Calibración*) |
| `PROGRAMA_FORMACION`, `PALABRAS_CLAVE_AREA` | Qué vacantes son "de tu área" |
| `GEMINI_API_KEY` **o** `OPENAI_API_KEY` | Correos y fichas redactados por IA (opcional: sin clave se usan plantillas) |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Alertas (opcional) |

Cómo obtener el chat de Telegram: crea un bot con **@BotFather**, escríbele cualquier mensaje y abre `https://api.telegram.org/bot<TOKEN>/getUpdates`; copia el número de `"chat":{"id": ...}`.

### 2. Tu perfil

```bash
cp data/perfil_aprendiz.example.json data/perfil_aprendiz.json
```

Complétalo con **tus datos reales**: habilidades, proyectos (con sus tecnologías), experiencia, formación. El adaptador nunca inventa experiencia: solo reordena y resalta lo que escribas aquí. Mientras más concretas sean las tecnologías de cada proyecto, mejor funciona el emparejamiento.

### 3. Calibración del portal (primera vez)

> El **inicio de sesión** ya está verificado contra el portal real (23/10/2026): el programa elige la pestaña «Aprendices», escribe en `#tbLoginUsuario` / `#__tbPasswordUsuario` y pulsa `#ini_session_aprendiz`. Lo que falta calibrar es la **tabla de convocatorias**, que solo se ve después de iniciar sesión.

El portal del SENA puede cambiar su estructura sin aviso. Los selectores están en `config/selectors.json`, no en el código. Para verificarlos:

```bash
python main.py --calibrar
```

Se abre un navegador visible: inicia sesión, navega hasta la tabla de convocatorias y presiona ENTER en la terminal. El programa guarda en `data/debug/` el HTML, una captura y un resumen de las tablas encontradas con sus encabezados. Con eso:

- Copia la URL mostrada a `SGVA_VACANTES_URL` en `.env`.
- Si la detección automática de columnas falla, fija los índices en `columnas_manual` (p. ej. `{"razon_social": 1, "ciudad": 3}`).
- Ajusta `tabla`, `siguiente_pagina` o `filtro_programa` si hace falta.

La sesión queda guardada en `session.json`, así que no vuelves a iniciar sesión hasta que expire.

---

## Uso

```bash
python main.py --all             # pipeline completo: scraping → enriquecimiento → CV + correos → alertas
python main.py --scrape          # solo extraer vacantes
python main.py --enrich          # investigar empresas nuevas (o --enrich --forzar para todas)
python main.py --generate-all    # CV + correos para cada vacante activa de tu área
python main.py --generate-all --vacante sgva-5521   # solo una vacante
python main.py --alert --dry-run # ver qué alertas se enviarían, sin enviarlas
python main.py --monitor         # daemon: repite scraping + alertas cada MONITOR_INTERVALO_MIN
python main.py --monitor --once  # un solo ciclo (para cron / Programador de tareas)
python main.py --estado          # resumen de la base local
python main.py --help
```

Opciones útiles: `--visible` (ver el navegador), `--sin-pdf`, `--forzar`, `-v` (logs de depuración). Los logs quedan en `logs/matchmaker.log`.

### Programar el monitor

**Linux/macOS (cron)** — cada 3 horas entre 7 a. m. y 9 p. m.:

```cron
0 7-21/3 * * * cd /ruta/sgva-matchmaker && .venv/bin/python main.py --monitor --once >> logs/cron.log 2>&1
```

**Windows (Programador de tareas)** — acción: `C:\ruta\sgva-matchmaker\.venv\Scripts\python.exe`, argumentos: `main.py --monitor --once`, iniciar en: `C:\ruta\sgva-matchmaker`.

> Si el portal pide CAPTCHA durante una ejecución programada, el proceso abrirá un navegador visible y esperará 5 minutos. Si nadie lo resuelve, ese ciclo falla y se reintenta en el siguiente. Para evitarlo, haz `python main.py --scrape --visible` cuando la sesión expire.

---

## Cómo funciona por dentro

**Scraper.** Playwright (Chromium) con contexto en `es-CO`, zona horaria de Bogotá y un User-Agent real por sesión. Reutiliza `session.json`; si expiró, hace login escribiendo con cadencia humana. Si detecta CAPTCHA o no confirma la sesión, abre el navegador **visible** con tus datos pre-diligenciados para que tú completes la verificación (el software no evade CAPTCHAs). Las columnas se detectan por el texto del encabezado, así que el orden de la tabla no importa. Recorre todas las páginas con pausas aleatorias de 2–5 s y corta si el paginador no avanza. Descarta vacantes con fecha límite vencida y, si el portal no tiene filtro por programa, filtra localmente por tus palabras clave.

**Base de datos.** Cada ejecución guarda un *snapshot* diario. Las vacantes que desaparecen del portal se marcan inactivas (nunca si el scraping vino vacío, para no borrar todo por un fallo).

**Enricher.** Busca en DuckDuckGo (`ddgs`) de lo más específico a lo más amplio, descarta directorios y redes sociales para identificar el sitio oficial, y lee **solo su portada** (una petición) para extraer la meta descripción y huellas técnicas (WordPress, React, Shopify, ASP.NET…). Con LLM configurado, sintetiza la ficha usando únicamente esa evidencia y rechaza URLs que no aparezcan en ella. Sin LLM, usa un clasificador sectorial por palabras clave.

**Correos.** El prompt combina tu perfil y la ficha de la empresa. La respuesta se valida (JSON, límites de palabras, sin `[marcadores]`); si falla, se reintenta una vez y luego se usa la plantilla local. **El programa solo redacta: no envía correos.**

**CV ATS.** Extrae los requisitos del perfil publicado (con sinónimos: `PostgreSQL ⇒ SQL`, `FastAPI ⇒ Python`), puntúa cada proyecto y reordena proyectos y habilidades. El Markdown es de una sola columna, sin tablas, imágenes ni íconos. `analisis.json` te dice qué te falta reforzar.

**Alertas.** Notifica cada vacante activa de tu área que no se haya alertado antes (deduplicación por ID en SQLite). Si son más de 8 a la vez, envía un solo mensaje-resumen. Respeta el límite de Telegram (~1 mensaje/s) y los `RetryAfter`. Si un mensaje no llega, esa vacante se reintenta en el siguiente ciclo.

---

## Seguridad y privacidad

- **App de escritorio**: la contraseña y las claves se guardan en el Administrador de credenciales de Windows (vía `keyring`), nunca en `ajustes.json`. Si desmarcas «Recordar», solo viven en memoria mientras la app está abierta.
- **Credenciales del SGVA**: solo se leen de `.env` y solo se escriben en el formulario del portal del SENA, en tu equipo. Nunca se registran en los logs, nunca se envían a la API del LLM ni a ningún otro servidor, y no están en el código.
- **`session.json`** contiene tus cookies de sesión: se crea con permisos `600` y está en `.gitignore`. Trátalo como una contraseña; bórralo para cerrar sesión.
- **API del LLM**: recibe tu perfil profesional (el de `perfil_aprendiz.json`) y datos públicos de la empresa. No incluyas en ese archivo datos que no quieras compartir con el proveedor (número de documento, dirección, etc.).
- `.env`, `session.json`, `data/*.db`, `data/perfil_aprendiz.json`, `output/` y `logs/` están excluidos de Git.

## Scraping ético

- Pausas aleatorias de **2 a 5 segundos** entre acciones (configurables, pero no las bajes).
- Una sola sesión, un User-Agent real y estable por ejecución, reintentos con espera exponencial.
- El modo monitor sugiere **un ciclo cada 3 horas**; con backoff automático si el portal falla.
- Solo lee las convocatorias a las que tu cuenta ya tiene acceso. No postula automáticamente en tu nombre.
- Del sitio de cada empresa solo se lee la portada pública, una vez.

---

## Pruebas

```bash
python -m pytest -q
```

Incluye pruebas unitarias de todos los módulos y de la capa de la app (sin red), y una prueba de integración del scraper contra un **portal SGVA simulado en localhost** que valida login, guardado y reutilización de `session.json`, paginación, filtros por área y por fecha. No toca el portal real.

## Estructura

```
sgva-matchmaker/
├── app_gui.py                    # app de escritorio (CustomTkinter)
├── main.py                       # orquestador CLI
├── config.py                     # rutas y lectura de .env (modo código vs. .exe)
├── config/selectors.json         # selectores del portal (editables)
├── modules/
│   ├── scraper.py                # 1. extractor SGVA (Playwright)
│   ├── enricher.py               # 2. investigador empresarial
│   ├── email_generator.py        # 3. correos (Gemini / OpenAI / plantilla)
│   ├── cv_adapter.py             # 4. hoja de vida ATS + PDF
│   ├── bot_telegram.py           # 5. monitor y alertas
│   ├── pipeline.py               # pasos compartidos por la CLI y la app
│   ├── app_state.py              # ajustes, credenciales (keyring) y perfil de la app
│   ├── diagnostico.py            # autoprueba del equipo
│   ├── llm.py · db.py · models.py · utils.py
├── packaging/                    # spec de PyInstaller + metadatos del .exe
├── build_exe.bat                 # construir el .exe en Windows
├── .github/workflows/build-windows.yml
├── assets/                       # ícono
├── data/perfil_aprendiz.example.json
├── tests/
├── requirements.txt              # CLI / desarrollo
└── requirements-app.txt          # construir la app
```

---

## Descargo de Responsabilidad Institucional

**SGVA-Matchmaker es una iniciativa independiente de código abierto desarrollada por el colectivo Shameless Company.** No es un producto oficial del **Servicio Nacional de Aprendizaje (SENA)**, ni está avalado, patrocinado, certificado ni respaldado de ninguna forma por el SENA, el Sistema de Gestión Virtual de Aprendices (SGVA) o el portal Caprendizaje.

- **Marcas.** "SENA", "SGVA", "Caprendizaje" y sus logotipos son propiedad del Servicio Nacional de Aprendizaje. Se mencionan aquí únicamente con fines descriptivos, para indicar con qué portal interactúa la herramienta. Este proyecto no usa sus logotipos ni pretende hacerse pasar por un canal oficial.
- **Uso personal y responsable.** La herramienta está pensada para que cada aprendiz consulte, con **su propia cuenta**, las convocatorias a las que ya tiene acceso. No compartas tu cuenta, no la uses para extraer información a gran escala, no redistribuyas los datos de las empresas y no reduzcas los retardos configurados. Respeta los términos y condiciones de uso del portal Caprendizaje y la Ley 1581 de 2012 de protección de datos personales.
- **Riesgos.** El SENA puede modificar el portal, limitar el acceso automatizado o suspender cuentas que considere que hacen un uso indebido. Tú eres responsable del uso que le des a esta herramienta y de verificar que esté permitido.
- **Exactitud.** La información de las vacantes proviene del portal y la de las empresas, de fuentes públicas y de inferencias automáticas que pueden ser incorrectas. Verifica siempre los datos en el portal oficial antes de postularte. Los correos y hojas de vida generados son borradores: revísalos antes de enviarlos.
- **Sin garantía.** El software se entrega "tal cual", sin garantías de ningún tipo, según la licencia MIT.

Los canales oficiales para el contrato de aprendizaje son los del SENA: [www.sena.edu.co](https://www.sena.edu.co).

## Licencia

[MIT](LICENSE) © Shameless Company
