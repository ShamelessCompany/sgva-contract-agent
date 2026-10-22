#!/usr/bin/env python3
"""
Estructura base para la extraccion de solicitudes de contrato de aprendizaje en el portal SGVA (Caprendizaje SENA).
Requiere: pip install playwright
"""
import json
from pathlib import Path

# Portal oficial de Caprendizaje
SGVA_URL = "https://caprendizaje.sena.edu.co"

def simular_extraccion():
    """
    Ejemplo de estructura de datos que saca el scraper una vez autenticado en el SGVA.
    """
    vacantes_detectadas = [
        {
            "id_solicitud": "SGVA-2026-8812",
            "empresa": "Soluciones Digitales de Santander SAS",
            "ciudad": "Bucaramanga / Floridablanca",
            "programa_requerido": "Analisis y Desarrollo de Software (ADSO)",
            "cupos": 2,
            "fecha_limite": "2026-11-15",
            "enlace_detalle": "https://caprendizaje.sena.edu.co/solicitud/detalle?id=8812"
        },
        {
            "id_solicitud": "SGVA-2026-8845",
            "empresa": "Compania Logistica del Oriente",
            "ciudad": "Remoto / Hibrido",
            "programa_requerido": "Analisis y Desarrollo de Software (ADSO)",
            "cupos": 1,
            "fecha_limite": "2026-11-20",
            "enlace_detalle": "https://caprendizaje.sena.edu.co/solicitud/detalle?id=8845"
        }
    ]
    return vacantes_detectadas

if __name__ == "__main__":
    vacantes = simular_extraccion()
    output_path = Path("vacantes_sgva.json")
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(vacantes, f, indent=2, ensure_ascii=False)
    print(f"Extraccion simulada: {len(vacantes)} vacantes guardadas en {output_path}")
