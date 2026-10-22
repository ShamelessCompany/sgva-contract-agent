#!/usr/bin/env python3
"""
Generador de prompts para correos de postulacion y hojas de vida adaptadas.
Toma los datos de la vacante del SGVA y la investigacion de la empresa.
"""

def generar_prompt_correo(datos_aprendiz: dict, datos_empresa: dict) -> str:
    prompt = f"""
Actua como un redactor profesional de solicitudes de empleo.
Escribe un correo electronico de presentacion corto y directo (maximo 140 palabras) para postular a un contrato de aprendizaje del SENA.

Datos del aprendiz:
- Nombre: {datos_aprendiz.get('nombre')}
- Programa SENA: {datos_aprendiz.get('programa')}
- Habilidades clave: {', '.join(datos_aprendiz.get('habilidades', []))}
- Portafolio / GitHub: {datos_aprendiz.get('portafolio')}

Datos de la empresa (extraidos del SGVA):
- Nombre de la empresa: {datos_empresa.get('nombre')}
- Sector o actividad: {datos_empresa.get('sector')}
- Que necesita la empresa: {datos_empresa.get('perfil_buscado')}

Reglas obligatorias para el correo:
1. Asunto claro indicando disponibilidad inmediata para contrato de aprendizaje.
2. Saludo formal dirigido al area de seleccion o gestion humana.
3. Explicar en 2 oraciones por que las habilidades del aprendiz encajan con lo que hace la empresa.
4. Incluir enlace al portafolio y disponibilidad para entrevista.
5. Evitar frases de relleno, lenguaje exagerado o halagos vacios.
"""
    return prompt.strip()

def generar_prompt_cv(datos_aprendiz: dict, datos_empresa: dict) -> str:
    prompt = f"""
Adapta el resumen profesional y el orden de los proyectos de la hoja de vida para que destaque ante la siguiente vacante del SGVA:

Empresa: {datos_empresa.get('nombre')}
Actividad: {datos_empresa.get('sector')}
Perfil requerido: {datos_empresa.get('perfil_buscado')}

Proyectos del aprendiz:
{datos_aprendiz.get('proyectos_resumen')}

Genera:
1. Un perfil profesional de 3 lineas enfocado en lo que la empresa busca.
2. La seleccion y redaccion de los 2 proyectos mas relevantes con logros tecnicos medibles.
"""
    return prompt.strip()

if __name__ == "__main__":
    aprendiz_ejemplo = {
        "nombre": "Andres Carvajal",
        "programa": "Analisis y Desarrollo de Software (ADSO) - SENA",
        "habilidades": ["Python", "FastAPI", "Bases de datos SQL", "Automatizacion con scripts"],
        "portafolio": "https://github.com/AndresCarvajal04",
        "proyectos_resumen": "- Bots de automatizacion en Python con Playwright.\n- APIs en la nube con Cloudflare Workers y bases de datos relacionales."
    }
    
    empresa_ejemplo = {
        "nombre": "Tecnologia y Servicios Integrados SAS",
        "sector": "Desarrollo de software empresarial y soporte a sistemas cloud",
        "perfil_buscado": "Apoyo en pruebas de software, consultas en bases de datos y scripts de mantenimiento."
    }

    print("=== PROMPT PARA CORREO DE POSTULACION ===")
    print(generar_prompt_correo(aprendiz_ejemplo, empresa_ejemplo))
