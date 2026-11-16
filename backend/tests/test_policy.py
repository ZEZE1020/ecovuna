"""Server-side tool permissions and action policy tests (#18)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.agent import decide, triage
from backend.db import connect
from backend.errors import ConflictError, NotFoundError, PolicyViolationError
from backend.ingest import ingest
from backend.main import app
from backend.mcp_server import stage_advisory_for_wao_approval
from backend.policy import execute_consequential_action


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_missing_officer_is_rejected_with_stable_error_code() -> None:
    state = triage("Homa Bay Central")
    client = TestClient(app)
    response = client.post(
        "/api/agent/decide",
        json={"run_id": state["run_id"], "approved": True, "wao_officer_name": "   "},
    )
    assert response.status_code == 422
    payload = response.json()
    assert payload["error_code"] == "MISSING_OFFICER"


def test_wrong_or_unauthorized_officer_is_rejected() -> None:
    state = triage("Homa Bay Central")
    client = TestClient(app)
    for invalid_officer in ("system", "anonymous", "John Doe", "WAO-ONLY"):
        response = client.post(
            "/api/agent/decide",
            json={
                "run_id": state["run_id"],
                "approved": True,
                "wao_officer_name": invalid_officer,
            },
        )
        assert response.status_code == 403
        assert response.json()["error_code"] == "UNAUTHORIZED_OFFICER"


def test_unknown_run_is_rejected() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/agent/decide",
        json={
            "run_id": "RUN-NONEXISTENT-999",
            "approved": True,
            "wao_officer_name": "Godfrey Ogembo — WAO-KE-043",
        },
    )
    assert response.status_code == 404
    assert response.json()["error_code"] == "UNKNOWN_RUN"

    with pytest.raises(NotFoundError) as exc_info:
        decide("RUN-NONEXISTENT-999", True, "Godfrey Ogembo — WAO-KE-043")
    assert exc_info.value.error_code == "UNKNOWN_RUN"


def test_missing_and_invalid_approval_token_rejected() -> None:
    state = triage("Homa Bay Central")
    client = TestClient(app)

    missing_token = client.post(
        "/api/agent/decide",
        json={
            "run_id": state["run_id"],
            "approved": True,
            "wao_officer_name": "Godfrey Ogembo — WAO-KE-043",
            "approval_token": "",
        },
    )
    assert missing_token.status_code == 403
    assert missing_token.json()["error_code"] == "MISSING_APPROVAL_TOKEN"

    wrong_token = client.post(
        "/api/agent/decide",
        json={
            "run_id": state["run_id"],
            "approved": True,
            "wao_officer_name": "Godfrey Ogembo — WAO-KE-043",
            "approval_token": "APR-FORGED-TOKEN",
        },
    )
    assert wrong_token.status_code == 403
    assert wrong_token.json()["error_code"] == "INVALID_APPROVAL_TOKEN"


def test_already_completed_run_and_replayed_approval_rejected() -> None:
    state = triage("Homa Bay Central")
    token = state["advisory"]["approval_token"]
    first = decide(
        state["run_id"],
        True,
        "Godfrey Ogembo — WAO-KE-043",
        approval_token=token,
    )
    assert first["status"] == "APPROVED_DISPATCHED"
    assert first["dispatched"] is True

    # Replay with token
    with pytest.raises(ConflictError) as replay_exc:
        decide(
            state["run_id"],
            True,
            "Godfrey Ogembo — WAO-KE-043",
            approval_token=token,
        )
    assert replay_exc.value.error_code == "REPLAYED_APPROVAL"

    # Second decision without token on already-completed run
    with pytest.raises(ConflictError) as completed_exc:
        decide(state["run_id"], False, "Godfrey Ogembo — WAO-KE-043")
    assert completed_exc.value.error_code == "RUN_ALREADY_DECIDED"


def test_insufficient_evidence_rejected_for_staging_and_decision() -> None:
    with pytest.raises(PolicyViolationError) as stage_exc:
        stage_advisory_for_wao_approval(
            "RUN-NO-EVIDENCE",
            "Homa Bay Central",
            "SUDDEN_DRY_SPELL",
            "Germination_0_14d",
            ["PLOT-HB-101"],
            "Swahili",
            "English",
            "EV-HYDRO-2026",
            1800.0,
            {"sensor_ids": ["KJB-HB-01"], "plot_ids": ["PLOT-HB-101"]},  # missing kalro_rule_id
        )
    assert stage_exc.value.error_code == "INSUFFICIENT_EVIDENCE"

    ungrounded_run = triage("Ward Without Any Plots")
    assert ungrounded_run["status"] == "SAFE_TERMINAL_VERIFICATION_REQUIRED"
    with pytest.raises(PolicyViolationError) as decide_exc:
        decide(ungrounded_run["run_id"], True, "Godfrey Ogembo — WAO-KE-043")
    assert decide_exc.value.error_code == "INSUFFICIENT_EVIDENCE"


def test_rejected_decision_cannot_be_treated_as_dispatched() -> None:
    state = triage("Homa Bay Central")
    token = state["advisory"]["approval_token"]
    decision = decide(
        state["run_id"],
        False,
        "Godfrey Ogembo — WAO-KE-043",
        "Hold for field visit",
        approval_token=token,
    )
    assert decision["status"] == "REJECTED_FIELD_VISIT"
    assert decision["dispatched"] is False

    client = TestClient(app)
    dispatch_resp = client.post(
        "/api/agent/actions",
        json={
            "tool_name": "dispatch_advisory",
            "run_id": state["run_id"],
            "wao_officer_name": "Godfrey Ogembo — WAO-KE-043",
            "approval_token": token,
        },
    )
    assert dispatch_resp.status_code == 403
    assert dispatch_resp.json()["error_code"] == "REJECTED_NOT_DISPATCHABLE"


def test_consequential_actions_require_approved_signoff_and_prevent_replay() -> None:
    state = triage("Homa Bay Central")
    token = state["advisory"]["approval_token"]

    # Before WAO approval, direct dispatch/input order/credit flag are blocked
    for tool_name in ("dispatch_advisory", "confirm_input_order", "update_credit_flag"):
        with pytest.raises(PolicyViolationError) as exc_info:
            execute_consequential_action(
                tool_name=tool_name,
                run_id=state["run_id"],
                wao_officer_name="Godfrey Ogembo — WAO-KE-043",
                approval_token=token,
                channel="mcp",
            )
        assert exc_info.value.error_code == "UNAPPROVED_ACTION"

    # Approve the run first
    decide(
        state["run_id"],
        True,
        "Godfrey Ogembo — WAO-KE-043",
        approval_token=token,
    )

    # Now execute confirm_input_order once
    order_res = execute_consequential_action(
        tool_name="confirm_input_order",
        run_id=state["run_id"],
        wao_officer_name="Godfrey Ogembo — WAO-KE-043",
        approval_token=token,
        payload={"input_id": "INP-HYDRO-001"},
        channel="api",
    )
    assert order_res["status"] == "EXECUTED"

    # Replaying the same consequential action is blocked
    with pytest.raises(ConflictError) as replay_exc:
        execute_consequential_action(
            tool_name="confirm_input_order",
            run_id=state["run_id"],
            wao_officer_name="Godfrey Ogembo — WAO-KE-043",
            approval_token=token,
            payload={"input_id": "INP-HYDRO-001"},
            channel="api",
        )
    assert replay_exc.value.error_code == "REPLAYED_APPROVAL"

    # Verify policy decisions are recorded in mcp_audit_log and policy_decisions
    with connect() as db:
        policy_rows = db.execute(
            "SELECT * FROM policy_decisions WHERE run_id = ?",
            (state["run_id"],),
        ).fetchall()
        audit_rows = db.execute(
            "SELECT * FROM mcp_audit_log WHERE run_id = ? AND server = 'Ecovuna_Policy'",
            (state["run_id"],),
        ).fetchall()
    assert len(policy_rows) >= 5
    assert len(audit_rows) >= 5
