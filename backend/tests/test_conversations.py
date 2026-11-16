"""Tests for evidence-first, context-aware conversations (#5)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.ingest import ingest
from backend.main import app


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_two_consecutive_questions_retain_ward_and_prior_run_context() -> None:
    client = TestClient(app)

    first = client.post(
        "/api/agent/chat",
        json={
            "message": "What is the flood risk in Ndhiwa?",
            "ward": "Ndhiwa",
        },
    )
    assert first.status_code == 200
    first_payload = first.json()
    session_id = first_payload["session_id"]
    first_run_id = first_payload["run"]["run_id"]
    assert first_payload["context"]["ward"] == "Ndhiwa"
    assert first_run_id in first_payload["context"]["prior_run_ids"]

    sections = first_payload["sections"]
    assert sections["observed_facts"]
    assert sections["interpretation"]
    assert sections["uncertainty"]
    assert sections["recommendation"]
    assert sections["approval_state"] == "PENDING_WAO_APPROVAL"
    assert sections["citations"]["kalro_rule_id"] == "KALRO-HB-2026-03"
    assert sections["citations"]["sensor_ids"]
    assert sections["citations"]["plot_ids"]

    # Second consecutive question omits ward; server retains Ndhiwa and prior run ID
    second = client.post(
        "/api/agent/chat",
        json={
            "session_id": session_id,
            "message": "What about flowering maize plots?",
        },
    )
    assert second.status_code == 200
    second_payload = second.json()
    assert second_payload["session_id"] == session_id
    assert second_payload["context"]["ward"] == "Ndhiwa"
    assert first_run_id in second_payload["context"]["prior_run_ids"]
    assert len(second_payload["context"]["prior_run_ids"]) == 2
    assert any(
        first_run_id in fact for fact in second_payload["sections"]["observed_facts"]
    )

    session_resp = client.get(f"/api/agent/sessions/{session_id}")
    assert session_resp.status_code == 200
    session_data = session_resp.json()
    assert session_data["ward"] == "Ndhiwa"
    assert len(session_data["turns"]) == 4


def test_missing_or_stale_evidence_produces_clarification_not_confident_answer() -> None:
    client = TestClient(app)

    missing_resp = client.post(
        "/api/agent/chat",
        json={
            "ward": "Unmapped Ward Zero",
            "message": "Should we apply nitrogen today?",
        },
    )
    assert missing_resp.status_code == 200
    missing_payload = missing_resp.json()
    assert missing_payload["run"]["advisory"] is None
    assert (
        missing_payload["sections"]["approval_state"]
        == "SAFE_TERMINAL_VERIFICATION_REQUIRED"
    )
    assert missing_payload["context"]["telemetry_freshness"] == "missing"
    assert len(missing_payload["context"]["unresolved_questions"]) >= 1
    assert "Verification required" in missing_payload["sections"]["recommendation"]
