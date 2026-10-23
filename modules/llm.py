"""Cliente LLM unificado (Google Gemini u OpenAI) que siempre devuelve JSON.

Privacidad: a la API del LLM solo se envían datos públicos de la empresa y el perfil
profesional que tú mismo escribes en `data/perfil_aprendiz.json`. Las credenciales del
SGVA y la sesión (`session.json`) NUNCA forman parte de un prompt.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from config import Settings
from modules.utils import retry

log = logging.getLogger(__name__)


class LLMNoDisponible(RuntimeError):
    """No hay proveedor configurado o la librería no está instalada."""


class LLMClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.proveedor = settings.llm_provider
        self._cliente: Any = None

        if self.proveedor == "gemini" and settings.gemini_api_key:
            try:
                from google import genai  # paquete: google-genai

                self._cliente = genai.Client(api_key=settings.gemini_api_key)
                self.modelo = settings.gemini_model
            except ImportError as exc:
                raise LLMNoDisponible("Instala google-genai: pip install google-genai") from exc
        elif self.proveedor == "openai" and settings.openai_api_key:
            try:
                from openai import OpenAI

                self._cliente = OpenAI(api_key=settings.openai_api_key)
                self.modelo = settings.openai_model
            except ImportError as exc:
                raise LLMNoDisponible("Instala openai: pip install openai") from exc
        else:
            raise LLMNoDisponible(
                f"LLM_PROVIDER='{self.proveedor}' sin API key configurada en .env"
            )

    @property
    def nombre(self) -> str:
        return f"{self.proveedor}:{self.modelo}"

    @retry(intentos=3, backoff_base=3.0)
    def generar_json(self, prompt: str, system: str = "", temperatura: float = 0.6) -> dict:
        """Envía el prompt y devuelve el JSON parseado de la respuesta."""
        if self.proveedor == "gemini":
            from google.genai import types

            resp = self._cliente.models.generate_content(
                model=self.modelo,
                contents=prompt,
                config=types.GenerateContentConfig(
                    system_instruction=system or None,
                    response_mime_type="application/json",
                    temperature=temperatura,
                ),
            )
            texto = resp.text or ""
        else:
            mensajes = []
            if system:
                mensajes.append({"role": "system", "content": system})
            mensajes.append({"role": "user", "content": prompt})
            resp = self._cliente.chat.completions.create(
                model=self.modelo,
                messages=mensajes,
                response_format={"type": "json_object"},
                temperature=temperatura,
            )
            texto = resp.choices[0].message.content or ""
        return parsear_json(texto)


def parsear_json(texto: str) -> dict:
    """Extrae el primer objeto JSON válido de una respuesta (tolera ```json ... ```)."""
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip(), flags=re.MULTILINE)
    try:
        data = json.loads(limpio)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", limpio, flags=re.DOTALL)
        if not match:
            raise ValueError(f"La respuesta del LLM no contiene JSON: {texto[:200]!r}") from None
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("Se esperaba un objeto JSON")
    return data


def crear_cliente_opcional(settings: Settings) -> LLMClient | None:
    """Devuelve un cliente si hay configuración válida; si no, None (modo plantilla)."""
    if settings.llm_provider in ("", "ninguno", "none"):
        log.info("Redacción con plantillas locales (sin IA).")
        return None
    try:
        cliente = LLMClient(settings)
        log.info("LLM activo: %s", cliente.nombre)
        return cliente
    except LLMNoDisponible as exc:
        log.warning("LLM no disponible (%s). Se usarán plantillas locales.", exc)
        return None
