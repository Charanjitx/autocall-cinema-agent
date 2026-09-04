"""Server-side Gemini integration with an explicit failure boundary."""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from typing import Any

from .models import CallSheet, normalize_call_sheet

logger = logging.getLogger(__name__)
DEFAULT_MODEL = "gemini-2.5-flash"
MODEL_FALLBACKS = ("gemini-1.5-flash", "gemini-3.6-flash")
SUPPORTED_MODELS = {DEFAULT_MODEL, *MODEL_FALLBACKS}
TRANSIENT_RETRIES = 3


class GeminiConfigurationError(RuntimeError):
    """Raised when the server is not configured with Gemini credentials."""


class GeminiServiceError(RuntimeError):
    """Raised when Gemini cannot produce a usable call sheet."""


SYSTEM_PROMPT = """You are a film production coordinator. Analyze the screenplay below and
return ONLY valid JSON matching the requested schema. Identify every scene heading,
its production location, time of day, a concise action summary, all named or clearly
present characters, their likely on-set call time, and physical props that appear or
are handled. Call times should be practical estimates in 12-hour format when the
screenplay provides enough context; use TBD when it does not. Do not invent scenes.
Use a simple scene number such as 1, 2, 3. Keep names and props concise and deduplicate
them within each scene.

The JSON object must have this shape:
{"scenes":[{"scene_number":"1","heading":"INT. LOCATION - DAY","location":"Location",
"time_of_day":"DAY","summary":"Short action summary","cast":[{"name":"Name",
"call_time":"06:00 AM","notes":""}],"props":[{"name":"Item","notes":""}]}]}"""


class GeminiService:
    def __init__(self, *, api_key: str | None = None, model: str | None = None, client: Any = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        configured_model = model or os.getenv("GEMINI_MODEL", DEFAULT_MODEL)
        self.model = configured_model if configured_model in SUPPORTED_MODELS else DEFAULT_MODEL
        if not self.api_key and client is None:
            raise GeminiConfigurationError(
                "Gemini is not configured. Add the GEMINI_API_KEY secret, then try again."
            )
        if client is not None:
            self.client = client
            return
        try:
            from google import genai
        except ImportError as exc:
            raise GeminiConfigurationError(
                "The Gemini SDK is not installed. Install project dependencies and try again."
            ) from exc
        self.client = genai.Client(api_key=self.api_key)

    def parse_screenplay(self, screenplay: str) -> CallSheet:
        prompt = f"{SYSTEM_PROMPT}\n\nSCREENPLAY:\n{screenplay}"
        response_schema = CallSheet.model_json_schema()
        response = None
        models_to_try = [self.model, *(model for model in MODEL_FALLBACKS if model != self.model)]
        for index, model in enumerate(models_to_try):
            try:
                response = _generate_with_retries(
                    client=self.client,
                    model=model,
                    prompt=prompt,
                    config=_generation_config(model, response_schema),
                )
                break
            except Exception as exc:
                if index == len(models_to_try) - 1 or not _is_model_unavailable(exc):
                    raise GeminiServiceError(
                        "Gemini could not analyze this screenplay. Check the screenplay and try again."
                    ) from exc

        try:
            if response is None:
                raise ValueError("Gemini did not return a response.")
            payload = _response_payload(response)
            return normalize_call_sheet(payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            logger.exception("Raw Gemini response parsing exception: %s", exc)
            raise GeminiServiceError(
                "Gemini returned incomplete or invalid scene data. Try analyzing again."
            ) from exc


def _is_model_unavailable(exc: Exception) -> bool:
    """Only retry a different model when the provider says this one is unavailable."""

    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    message = str(exc).lower()
    return status_code == 404 or "not_found" in message or "no longer available" in message


def _is_transient(exc: Exception) -> bool:
    status_code = getattr(exc, "code", None) or getattr(exc, "status_code", None)
    message = str(exc).lower()
    return status_code in {429, 500, 502, 503, 504} or any(
        marker in message
        for marker in ("unavailable", "temporarily", "high demand", "rate limit")
    )


def _generate_with_retries(
    *, client: Any, model: str, prompt: str, config: dict[str, Any]
) -> Any:
    """Retry only short-lived provider capacity/rate-limit failures."""

    for attempt in range(TRANSIENT_RETRIES):
        try:
            return client.models.generate_content(
                model=model,
                contents=prompt,
                config=config,
            )
        except Exception as exc:
            logger.exception("Raw Gemini API exception (model=%s, attempt=%s): %s", model, attempt + 1, exc)
            print(
                f"Raw Gemini API exception (model={model}, attempt={attempt + 1}): {exc}",
                file=sys.stderr,
                flush=True,
            )
            if not _is_transient(exc) or attempt == TRANSIENT_RETRIES - 1:
                raise
            time.sleep(0.5 * (attempt + 1))


def _generation_config(model: str, response_schema: dict[str, Any]) -> dict[str, Any]:
    """Use schema enforcement where supported and JSON MIME mode for newer fallback models."""

    config: dict[str, Any] = {
        "response_mime_type": "application/json",
        "temperature": 0.1,
    }
    if model != "gemini-3.6-flash":
        config["response_schema"] = response_schema
    return config


def _response_payload(response: Any) -> dict[str, Any]:
    """Extract JSON from the SDK response without assuming one SDK version."""

    parsed = getattr(response, "parsed", None)
    if parsed is not None:
        if isinstance(parsed, dict):
            return parsed
        if hasattr(parsed, "model_dump"):
            return parsed.model_dump()

    raw_text = getattr(response, "text", None)
    if not raw_text:
        raise ValueError("Gemini returned an empty response.")
    if isinstance(raw_text, str):
        payload = json.loads(raw_text)
    else:
        payload = raw_text
    if not isinstance(payload, dict):
        raise ValueError("Gemini returned a non-object JSON response.")
    return payload