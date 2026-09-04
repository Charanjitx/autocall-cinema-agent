"""Server-side Gemini integration with an explicit failure boundary."""

from __future__ import annotations

import json
import os
from typing import Any

from .models import CallSheet, normalize_call_sheet


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
them within each scene."""


class GeminiService:
    def __init__(self, *, api_key: str | None = None, model: str | None = None, client: Any = None):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY", "").strip()
        self.model = model or os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
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
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=prompt,
                config={
                    "response_mime_type": "application/json",
                    "response_schema": CallSheet,
                    "temperature": 0.1,
                },
            )
        except Exception as exc:
            raise GeminiServiceError(
                "Gemini could not analyze this screenplay. Check the screenplay and try again."
            ) from exc

        raw_text = getattr(response, "text", None)
        if not raw_text:
            raise GeminiServiceError("Gemini returned an empty response. Try analyzing again.")
        try:
            payload = json.loads(raw_text)
            return normalize_call_sheet(payload)
        except (json.JSONDecodeError, TypeError, ValueError) as exc:
            raise GeminiServiceError(
                "Gemini returned incomplete or invalid scene data. Try analyzing again."
            ) from exc