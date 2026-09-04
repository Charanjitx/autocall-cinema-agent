import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.gemini_service import GeminiService, GeminiServiceError
from app.main import app
from app.models import normalize_call_sheet


client = TestClient(app)


def sample_payload():
    return {
        "scenes": [
            {
                "scene_number": "1",
                "heading": "INT. STUDIO - DAY",
                "location": "Studio",
                "time_of_day": "day",
                "summary": "Maya prepares for the broadcast.",
                "cast": [
                    {"name": "Maya", "call_time": "6am"},
                    {"name": "maya", "call_time": "06:00 AM", "notes": "Lead"},
                    {"name": "Tom", "call_time": "06:30"},
                ],
                "props": [{"name": "Coffee"}, {"name": "coffee", "notes": "Fresh"}],
            }
        ]
    }


def test_normalization_deduplicates_and_computes_counts():
    result = normalize_call_sheet(sample_payload())
    assert result.summary.model_dump() == {"scene_count": 1, "cast_count": 2, "prop_count": 1}
    assert [person.name for person in result.scenes[0].cast] == ["Maya", "Tom"]
    assert result.scenes[0].cast[0].call_time == "06:00 AM"
    assert result.scenes[0].props[0].notes == "Fresh"


def test_normalization_rejects_missing_scenes():
    with pytest.raises(ValueError, match="at least one scene"):
        normalize_call_sheet({"scenes": []})


def test_request_validation_rejects_empty_or_unknown_fields():
    empty_response = client.post("/api/parse", json={"screenplay": "   "})
    assert empty_response.status_code == 422
    extra_response = client.post("/api/parse", json={"screenplay": "INT. ROOM", "unexpected": True})
    assert extra_response.status_code == 422


def test_health_does_not_expose_api_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "secret-that-must-not-appear")
    response = client.get("/api/health")
    assert response.status_code == 200
    assert "secret-that-must-not-appear" not in response.text
    assert response.json()["gemini"] == "configured"


def test_gemini_service_uses_flash_model_and_normalizes_response():
    payload = json.dumps(sample_payload())
    captured = {}

    def generate_content(**kwargs):
        captured.update(kwargs)
        return SimpleNamespace(text=payload)

    mock_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=generate_content
        )
    )
    result = GeminiService(api_key="test-key", client=mock_client).parse_screenplay(
        "INT. STUDIO - DAY"
    )
    assert captured["model"] == "gemini-2.5-flash"
    assert captured["config"]["response_mime_type"] == "application/json"
    assert captured["config"]["response_schema"]["type"] == "object"
    assert result.summary.scene_count == 1
    assert result.scenes[0].cast[0].call_time == "06:00 AM"


def test_gemini_service_accepts_sdk_parsed_payload():
    mock_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kwargs: SimpleNamespace(parsed=sample_payload())
        )
    )
    result = GeminiService(api_key="test-key", client=mock_client).parse_screenplay("INT. ROOM")
    assert result.summary.scene_count == 1


def test_gemini_service_falls_back_when_flash_model_is_unavailable():
    calls = []

    def generate_content(**kwargs):
        calls.append(kwargs["model"])
        if kwargs["model"] != "gemini-3.6-flash":
            raise RuntimeError("404 NOT_FOUND: model is no longer available")
        return SimpleNamespace(text=json.dumps(sample_payload()))

    mock_client = SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    )
    result = GeminiService(api_key="test-key", client=mock_client).parse_screenplay("INT. ROOM")
    assert calls == ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-3.6-flash"]
    assert result.summary.scene_count == 1


def test_gemini_service_retries_transient_provider_failures():
    attempts = 0

    def generate_content(**kwargs):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("503 UNAVAILABLE: high demand")
        return SimpleNamespace(text=json.dumps(sample_payload()))

    mock_client = SimpleNamespace(
        models=SimpleNamespace(generate_content=generate_content)
    )
    result = GeminiService(api_key="test-key", model="gemini-3.6-flash", client=mock_client).parse_screenplay(
        "INT. ROOM"
    )
    assert attempts == 3
    assert result.summary.scene_count == 1


def test_gemini_service_invalid_json_is_actionable():
    mock_client = SimpleNamespace(
        models=SimpleNamespace(
            generate_content=lambda **kwargs: SimpleNamespace(text="{not json")
        )
    )
    with pytest.raises(GeminiServiceError, match="invalid scene data"):
        GeminiService(api_key="test-key", client=mock_client).parse_screenplay("INT. ROOM")


def test_gemini_service_logs_raw_api_exception(caplog):
    def raise_api_error(**kwargs):
        raise RuntimeError("raw-api-error-401")

    mock_client = SimpleNamespace(
        models=SimpleNamespace(generate_content=raise_api_error)
    )
    with caplog.at_level("ERROR"):
        with pytest.raises(GeminiServiceError):
            GeminiService(api_key="test-key", client=mock_client).parse_screenplay("INT. ROOM")
    assert "raw-api-error-401" in caplog.text


def test_parse_endpoint_maps_missing_configuration(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    response = client.post("/api/parse", json={"screenplay": "INT. ROOM - DAY"})
    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]