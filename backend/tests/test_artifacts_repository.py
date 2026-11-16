"""Tests for persisted conversation sessions, immutable tool events, and versioned field artifacts (#17)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.agent import decide
from backend.artifacts_repository import repository as artifact_repo
from backend.errors import InvalidRequestError, PolicyViolationError
from backend.ingest import ingest
from backend.main import app


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_reopening_session_preserves_messages_citations_trace_and_approval_state() -> None:
    client = TestClient(app)
    chat_resp = client.post(
        "/api/agent/chat",
        json={
            "message": "Check germination maize dry spell in Homa Bay Central",
            "ward": "Homa Bay Central",
            "session_id": "SES-PERSIST-17",
        },
    )
    assert chat_resp.status_code == 200
    run_id = chat_resp.json()["run"]["run_id"]

    # Reopen session via GET endpoint
    reopen_resp = client.get("/api/agent/sessions/SES-PERSIST-17")
    assert reopen_resp.status_code == 200
    session_data = reopen_resp.json()
    assert session_data["session_id"] == "SES-PERSIST-17"
    assert len(session_data["turns"]) >= 2
    assert session_data["latest_run"]["run_id"] == run_id
    assert session_data["latest_run"]["status"] == "PAUSED_AT_WAO_GATE"
    assert len(session_data["tool_events"]) >= 4
    assert len(session_data["artifacts"]) == 4

    # Filter sessions by ward and status
    list_resp = client.get(
        "/api/agent/sessions",
        params={"ward": "Homa Bay Central", "status": "PAUSED_AT_WAO_GATE"},
    )
    assert list_resp.status_code == 200
    session_ids = {s["session_id"] for s in list_resp.json()["sessions"]}
    assert "SES-PERSIST-17" in session_ids


def test_field_artifacts_are_versioned_downloadable_and_unapproved_cannot_be_dispatched() -> None:
    client = TestClient(app)
    chat_resp = client.post(
        "/api/agent/chat",
        json={
            "message": "Prepare flowering maize advisory",
            "ward": "Homa Bay Central",
        },
    )
    run_id = chat_resp.json()["run"]["run_id"]

    # Inspect v1 artifacts (unapproved)
    arts_resp = client.get("/api/agent/artifacts", params={"run_id": run_id})
    assert arts_resp.status_code == 200
    v1_artifacts = arts_resp.json()["artifacts"]
    assert {a["artifact_type"] for a in v1_artifacts} == {
        "field_brief",
        "sms",
        "ussd",
        "visit_list",
    }
    for art in v1_artifacts:
        assert art["version"] == 1
        assert art["approval_status"] == "PENDING_WAO_APPROVAL"
        assert art["dispatched"] is False

        # Download check
        dl_resp = client.get(f"/api/agent/artifacts/{art['artifact_id']}/download")
        assert dl_resp.status_code == 200
        assert "attachment; filename=" in dl_resp.headers["content-disposition"]
        assert dl_resp.headers["x-dispatched"] == "false"

        # Unapproved artifact cannot be treated as dispatched
        verify_resp = client.post(
            f"/api/agent/artifacts/{art['artifact_id']}/verify-dispatch"
        )
        assert verify_resp.status_code == 403
        assert (
            verify_resp.json()["error_code"]
            == "UNAPPROVED_ARTIFACT_DISPATCH_FORBIDDEN"
        )

    # Safe checkpoint verification succeeds while paused at WAO gate
    checkpoint = artifact_repo.verify_safe_checkpoint(run_id)
    assert checkpoint["status"] == "PAUSED_AT_WAO_GATE"

    # Approve run -> generates v2 artifacts without overwriting v1
    decide(run_id, True, "Grace Otieno — WAO-002", "Approved for dispatch")

    # Continuing from completed terminal state is blocked
    with pytest.raises(InvalidRequestError):
        artifact_repo.verify_safe_checkpoint(run_id)

    v2_artifacts = artifact_repo.list_artifacts(run_id=run_id, latest_only=True)
    all_versions = artifact_repo.list_artifacts(run_id=run_id, latest_only=False)
    assert len(v2_artifacts) == 4
    assert len(all_versions) == 8  # 4 v1 + 4 v2 preserved immutably

    for art in v2_artifacts:
        assert art["version"] == 2
        assert art["approval_status"] == "APPROVED_DISPATCHED"
        assert art["approved_by_wao"] == "Grace Otieno — WAO-002"
        assert art["dispatched"] is True
        verified = artifact_repo.assert_artifact_dispatchable(art["artifact_id"])
        assert verified["dispatched"] is True

    # v1 remains unapproved and blocked from dispatch
    v1_first_id = v1_artifacts[0]["artifact_id"]
    with pytest.raises(PolicyViolationError):
        artifact_repo.assert_artifact_dispatchable(v1_first_id)
