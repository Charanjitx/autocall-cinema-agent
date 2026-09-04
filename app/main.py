"""FastAPI entry point for Autocall."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .gemini_service import GeminiConfigurationError, GeminiService, GeminiServiceError
from .models import CallSheet, ParseRequest

BASE_DIR = Path(__file__).parent

app = FastAPI(
    title="Autocall",
    description="Turn screenplay text into a practical daily call sheet.",
    version="0.1.0",
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")


@app.get("/", include_in_schema=False)
async def dashboard() -> FileResponse:
    return FileResponse(BASE_DIR / "static" / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon() -> Response:
    return Response(status_code=204)


@app.get("/api/health")
async def health() -> dict[str, str]:
    # This intentionally reports only configuration state, never the credential.
    import os

    return {"status": "ok", "gemini": "configured" if os.getenv("GEMINI_API_KEY") else "not_configured"}


@app.post("/api/parse", response_model=CallSheet)
async def parse_screenplay(request: ParseRequest) -> CallSheet:
    try:
        return GeminiService().parse_screenplay(request.screenplay)
    except GeminiConfigurationError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except GeminiServiceError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=f"Invalid request: {exc.errors()[0]['msg']}") from exc