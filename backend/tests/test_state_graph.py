"""Explicit state graph, conditional transitions, recovery, and resumption tests (#12)."""

from __future__ import annotations

from backend.agent import decide, triage
from backend.db import connect
from backend.ingest import ingest
from backend.state_graph import build_graph, load_run_state


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_trace_exposes_node_and_transition_names() -> None:
    state = triage("Homa Bay Central")
    assert state["status"] == "PAUSED_AT_WAO_GATE"
    nodes = [entry["node"] for entry in state["execution_trace"]]
    assert "plan" in nodes
    assert "plan_and_fetch" in nodes
    assert "citation_self_check" in nodes
    assert "stage_write_action" in nodes
    assert "human_approval" in nodes
    for entry in state["execution_trace"]:
        assert "--[" in entry["transition"]
        assert "]-->" in entry["transition"]

    transition_map = {
        (item["from_node"], item["transition"]): item["to_node"]
        for item in state["transitions"]
    }
    assert transition_map[("plan", "success")] == "plan_and_fetch"
    assert transition_map[("plan_and_fetch", "success")] == "citation_self_check"
    assert transition_map[("citation_self_check", "success")] == "stage_write_action"
    assert transition_map[("stage_write_action", "success")] == "human_approval"


def test_tool_timeout_follows_recovery_path_to_cached_evidence() -> None:
    state = triage("Homa Bay Central", "simulate_timeout")
    assert state["status"] == "PAUSED_AT_WAO_GATE"
    assert state["evidence"]["recovered"] is True
    transitions = [
        (item["from_node"], item["transition"], item["to_node"])
        for item in state["transitions"]
    ]
    assert ("plan_and_fetch", "tool_timeout", "recover") in transitions
    assert ("recover", "recovered", "citation_self_check") in transitions


def test_missing_evidence_reaches_safe_terminal_state_without_staging() -> None:
    state = triage("Unknown Ward Without Telemetry")
    assert state["status"] == "SAFE_TERMINAL_VERIFICATION_REQUIRED"
    assert state.get("advisory") is None
    transitions = [
        (item["from_node"], item["transition"], item["to_node"])
        for item in state["transitions"]
    ]
    assert ("plan_and_fetch", "missing_evidence", "recover") in transitions
    assert ("recover", "missing_evidence", "safe_terminal") in transitions


def test_conflict_transition_halts_staging_safely() -> None:
    graph = build_graph()
    initial = {
        "run_id": "RUN-CONFLICT-TEST",
        "ward": "Homa Bay Central",
        "scenario_override": "sudden dry spell",
        "conflicts": [{"field": "soil_moisture_pct", "severity": "high"}],
        "execution_trace": [],
        "transitions": [],
    }
    final_state = graph.run(initial)
    assert final_state["status"] == "PAUSED_FOR_CONFLICT_VERIFICATION"
    assert final_state.get("advisory") is None
    transitions = [
        (item["from_node"], item["transition"], item["to_node"])
        for item in final_state["transitions"]
    ]
    assert ("citation_self_check", "conflict_detected", "safe_terminal") in transitions


def test_approval_resumes_persisted_run_without_rerunning_write_steps() -> None:
    state = triage("Homa Bay Central")
    run_id = state["run_id"]
    persisted_before = load_run_state(run_id)
    assert persisted_before is not None
    assert persisted_before["status"] == "PAUSED_AT_WAO_GATE"

    with connect() as db:
        count_before = db.execute(
            "SELECT COUNT(*) FROM staged_advisories WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
    assert count_before == 1

    decision = decide(run_id, True, "Godfrey Ogembo — WAO-KE-043", "Verified")
    assert decision["status"] == "APPROVED_DISPATCHED"

    persisted_after = load_run_state(run_id)
    assert persisted_after is not None
    assert persisted_after["status"] == "APPROVED_DISPATCHED"
    assert persisted_after["decision"]["wao_officer_name"] == "Godfrey Ogembo — WAO-KE-043"
    assert (
        "human_approval",
        "approved",
        "completed",
    ) in [
        (item["from_node"], item["transition"], item["to_node"])
        for item in persisted_after["transitions"]
    ]

    with connect() as db:
        count_after = db.execute(
            "SELECT COUNT(*) FROM staged_advisories WHERE run_id = ?",
            (run_id,),
        ).fetchone()[0]
    assert count_after == 1
