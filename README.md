# sgva-contract-agent

Repositorio de Shameless Company para la automatizacion de busqueda de contratos de aprendizaje en la plataforma SGVA (Caprendizaje SENA), analisis de empresas y generacion de correos y hojas de vida personalizadas.

## Objetivo del repositorio
Crear un sistema con scripts y agentes que entre al portal del SGVA, saque todos los enlaces de convocatorias abiertas para aprendices, investigue de que trata cada empresa a partir de su nombre o NIT, y genere instrucciones (prompts) para redactar correos de contacto directo y ajustar la hoja de vida segun lo que busca la compania.

El proposito es doble: usarlo para que los integrantes del equipo consigan patrocinio o contrato rapido, y empaquetar la herramienta como un servicio o software que otros aprendices puedan usar.

---

## Modulos e ideas de proyectos con requisitos de MVP

### 1. Extractor de convocatorias y enlaces del portal SGVA
- Que es: Script en Python con Playwright o BeautifulSoup que inicia sesion en el portal de Caprendizaje (SGVA), recorre la lista de empresas que buscan aprendices en el programa de formacion (por ejemplo ADSO u otras areas) y extrae todos los enlaces, nombres de empresas y fechas de publicacion.
- Requisitos de MVP:
  1. Script que maneje el inicio de sesion con credenciales del aprendiz de forma segura (leyendo desde un archivo .env local).
  2. Funcion que extraiga la tabla de solicitudes activas y saque en un archivo JSON o CSV: nombre de la empresa, ciudad, fecha limite y enlace al detalle de la vacante.
  3. Evitar bloqueos del portal agregando tiempos de espera aleatorios entre paginas.

### 2. Investigador automatico de actividad empresarial
- Que es: Modulo que toma la razon social o el NIT de las empresas extraidas en el paso anterior y busca en internet a que se dedican (su pagina web, redes sociales o registro publico) para resumir que productos venden, que tecnologias usan y cual es su sector.
- Requisitos de MVP:
  1. Funcion que haga una busqueda rapida en la web con el nombre de la empresa y extraiga el texto principal de su sitio web o descripcion publica.
  2. Generar una ficha corta por empresa con tres datos: sector principal, que problema resuelven y tecnologias o tareas probables para el aprendiz.
  3. Guardar estos datos asociados a la vacante en el archivo de seguimiento.

### 3. Generador de prompts para correos de contacto directo
- Que es: Plantilla estructurada que combina la informacion de la vacante del SGVA y lo investigado sobre la empresa para armar un correo electronico personalizado y profesional que no parezca una plantilla generica.
- Requisitos de MVP:
  1. Plantilla de prompt que reciba: nombre del aprendiz, programa del SENA, nombre de la empresa y sector de la empresa.
  2. Salida de texto lista para enviar con: asunto claro, saludo formal, dos lineas explicando por que el perfil del aprendiz le aporta valor a ese negocio en especifico, y datos de contacto.
  3. Opcion para generar dos versiones de correo: uno corto y directo (menos de 150 palabras) y otro mas formal con enlace al portafolio.

### 4. Adaptador de hoja de vida a la medida de la vacante
- Que es: Herramienta que toma los datos del perfil del aprendiz y genera una version de hoja de vida en formato limpio de una sola columna (compatible con sistemas de lectura automatica ATS) destacando las habilidades y proyectos que coinciden con lo que esa empresa necesita.
- Requisitos de MVP:
  1. Plantilla base de hoja de vida en Markdown o Typst sin tablas complejas ni disenos que confundan a los lectores automaticos.
  2. Modulo que revise los requisitos que pide la empresa en el SGVA y ordene los proyectos del aprendiz poniendo primero los mas relevantes.
  3. Exportacion automatica a archivo PDF listo para adjuntar en el correo de postulacion.

### 5. Bot de alertas de nuevas vacantes
- Que es: Tarea programada que revisa el portal del SGVA dos veces al dia y manda una notificacion por Telegram o correo si aparece una empresa nueva buscando aprendices en el area del usuario.
- Requisitos de MVP:
  1. Script que compare la lista de vacantes actual con la del dia anterior.
  2. Bot de Telegram que mande el enlace directo y el nombre de la empresa nueva en cuanto se detecte.
  3. Registro para no repetir avisos de empresas que ya se hayan revisado.
