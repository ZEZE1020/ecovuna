from fastapi.testclient import TestClient

from backend.agent import decide, triage
from backend.evals.summary import summary
from backend.foundation import get_agent_foundation
from backend.ingest import ingest
from backend.main import app


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_triage_pauses_before_dispatch() -> None:
    state = triage("Homa Bay Central")
    assert state["status"] == "PAUSED_AT_WAO_GATE"
    assert state["advisory"]["status"] == "PENDING_WAO_APPROVAL"
    assert "KALRO-HB-2026-01" in str(state)
    assert state["agent_foundation"]["grounded"] is True
    assert state["agent_foundation"]["human_approval_required"] is True


def test_agent_foundation_defaults_to_offline_grounded_mode(monkeypatch) -> None:
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    foundation = get_agent_foundation()
    assert foundation.provider == "deterministic_offline"
    assert foundation.mode == "offline"
    assert foundation.model == "rule-grounded-planner"


def test_dispatch_requires_named_officer() -> None:
    state = triage("Homa Bay Central")
    try:
        decide(state["run_id"], True, "")
    except ValueError as error:
        assert "required" in str(error)
    else:
        raise AssertionError("dispatch must not bypass the WAO gate")


def test_approval_records_decision() -> None:
    state = triage("Homa Bay Central")
    result = decide(state["run_id"], True, "Test Officer — WAO-TEST")
    assert result["status"] == "APPROVED_DISPATCHED"


def test_operations_recommend_and_confirm_assignment() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/operations/recommendations",
        json={"ward": "Homa Bay Central", "category": "SOIL_AMENDMENT"},
    )
    assert response.status_code == 200
    recommendation = response.json()[0]
    assignment = client.post(
        "/api/operations/assignments",
        json={
            "plot_id": recommendation["plot_id"],
            "partner_id": recommendation["partner"]["partner_id"],
            "input_id": recommendation["input"]["input_id"],
        },
    )
    assert assignment.status_code == 200
    assert assignment.json()["status"] == "CONFIRMED"


def test_health_reports_telemetry_configuration() -> None:
    response = TestClient(app).get("/api/health")
    assert response.status_code == 200
    assert response.json()["telemetry"]["service_name"] == "ecovuna-api"
    assert response.json()["telemetry"]["exporter"] in {"none", "otlp/http"}


def test_evaluation_summary_explains_current_model_baseline() -> None:
    result = summary(1)
    assert result["total"] == 9
    assert result["interpretation"]["model_status"].startswith("The deterministic planner")
