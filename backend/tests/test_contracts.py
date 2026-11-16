"""OpenAPI contract and centralized error-handling tests (#13)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.ingest import ingest
from backend.kijanispace import KijaniSpaceError
from backend.main import app


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_openapi_advertises_typed_request_and_response_schemas() -> None:
    client = TestClient(app)
    schema = client.get("/openapi.json").json()
    paths = schema["paths"]

    critical_paths = (
        "/api/health",
        "/api/agent/foundation",
        "/api/evaluations/summary",
        "/api/agent/triage",
        "/api/agent/chat",
        "/api/agent/decide",
        "/api/mcp/registry",
        "/api/audit-logs",
        "/api/dashboard",
        "/api/advisories",
        "/api/telemetry",
        "/api/farmers",
        "/api/plots",
        "/api/operations/recommendations",
        "/api/operations/assignments",
    )
    for path in critical_paths:
        assert path in paths, f"Missing OpenAPI path {path}"

    components = schema["components"]["schemas"]
    for model_name in (
        "HealthResponse",
        "TriageRequest",
        "AgentRunResponse",
        "ChatRequest",
        "ChatResponse",
        "DecisionRequest",
        "DecisionResponse",
        "FarmerOnboardingRequest",
        "FarmerResponse",
        "PlotOnboardingRequest",
        "PlotResponse",
        "AssignmentRequest",
        "AssignmentResponse",
    ):
        assert model_name in components, f"Missing component schema {model_name}"


def test_malformed_request_returns_structured_validation_error() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/agent/chat",
        json={"message": "", "ward": "Homa Bay Central"},
        headers={"X-Request-ID": "REQ-TEST-422"},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["request_id"] == "REQ-TEST-422"
    assert payload["error_code"] == "VALIDATION_ERROR"
    assert payload["retryable"] is False
    assert payload["message"] == payload["detail"]
    assert "body.message" in payload["details"]["invalid_fields"]


def test_missing_record_returns_structured_not_found_error() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/plots",
        json={
            "farmer_id": "FARM-DOES-NOT-EXIST",
            "latitude": -0.52,
            "longitude": 34.45,
            "crop_type": "Maize WH-505",
            "planting_date": "2026-10-01",
            "current_growth_stage": "Germination_0_14d",
            "acreage": 1.5,
        },
    )
    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == "FARMER_NOT_FOUND"
    assert payload["retryable"] is False
    assert payload["request_id"].startswith("REQ-")


def test_provider_failure_returns_retryable_envelope_without_leaking_secrets(
    monkeypatch,
) -> None:
    def fail_triage(ward: str, scenario_override: str = ""):
        _ = (ward, scenario_override)
        raise KijaniSpaceError(
            "Upstream timeout with api_key=SECRET-TOKEN-123 and Bearer super-secret-jwt"
        )

    monkeypatch.setattr("backend.routers.agent.triage", fail_triage)
    client = TestClient(app)
    response = client.post(
        "/api/agent/triage",
        json={"ward": "Homa Bay Central", "scenario_override": "sudden dry spell"},
    )
    assert response.status_code == 503
    payload = response.json()
    assert payload["error_code"] == "PROVIDER_UNAVAILABLE"
    assert payload["retryable"] is True
    assert "SECRET-TOKEN-123" not in str(payload)
    assert "super-secret-jwt" not in str(payload)
    assert "[REDACTED]" in payload["details"]["reason"]
