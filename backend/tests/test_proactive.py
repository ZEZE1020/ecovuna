"""Tests for proactive daily brief and follow-up queue workflows (#8)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.db import connect
from backend.ingest import ingest
from backend.main import app


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_daily_brief_is_reproducible_and_includes_reasons_freshness_and_citations() -> None:
    client = TestClient(app)
    resp1 = client.get("/api/agent/brief")
    resp2 = client.get("/api/agent/brief")
    assert resp1.status_code == 200
    assert resp2.status_code == 200

    b1 = resp1.json()
    b2 = resp2.json()
    assert b1["brief_id"] == b2["brief_id"]
    assert b1["autonomous_dispatch"] is False
    assert b1["state_mutations_performed"] == 0
    assert len(b1["queue"]) >= 3
    assert [i["item_id"] for i in b1["queue"]] == [i["item_id"] for i in b2["queue"]]

    for item in b1["queue"]:
        assert item["priority_score"] > 0
        assert len(item["ranking_factors"]) >= 1
        assert item["freshness"]["last_telemetry_timestamp"]
        assert item["citations"]["kalro_rule_id"]
        assert item["citations"]["weather_bulletin_id"] == "KMD-2026-10-14"
        assert item["autonomous_actions_taken"] is False
        assert item["requires_wao_approval"] is True


def test_officer_can_refine_brief_and_convert_item_into_traceable_approval_gated_run() -> None:
    client = TestClient(app)

    # Refine brief with follow-up question
    refined = client.get(
        "/api/agent/brief",
        params={"question": "Which wards face flash flood risk?"},
    )
    assert refined.status_code == 200
    assert "flash flood" in refined.json()["refinement_note"].lower()

    with connect() as db:
        dispatched_before = db.execute(
            "SELECT COUNT(*) FROM staged_advisories WHERE status = 'APPROVED_DISPATCHED'"
        ).fetchone()[0]

    # Open a ranked item and continue it as a traceable run
    cont_resp = client.post(
        "/api/agent/brief/continue",
        json={
            "item_id": "BRIEF-NDHIWA",
            "question": "Check flash flood waterlogging in Ndhiwa",
            "session_id": "SES-PROACTIVE-08",
        },
    )
    assert cont_resp.status_code == 200
    payload = cont_resp.json()
    assert payload["autonomous_dispatch"] is False
    assert payload["session_id"] == "SES-PROACTIVE-08"
    assert payload["run"]["ward"] == "Ndhiwa"
    assert payload["run"]["status"] == "PAUSED_AT_WAO_GATE"
    assert payload["run"]["advisory"]["dispatched"] is False

    with connect() as db:
        dispatched_after = db.execute(
            "SELECT COUNT(*) FROM staged_advisories WHERE status = 'APPROVED_DISPATCHED'"
        ).fetchone()[0]
    assert dispatched_after == dispatched_before
