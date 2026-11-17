"""Explicit, resumable state graph for the Ecovuna agent (#12)."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any, TypedDict

from .db import connect


class AgentState(TypedDict, total=False):
    run_id: str
    ward: str
    scenario_override: str
    request: dict[str, Any]
    plan: dict[str, Any]
    evidence: dict[str, Any]
    conflicts: list[dict[str, Any]]
    draft: dict[str, Any]
    approval: dict[str, Any]
    decision: dict[str, Any] | None
    telemetry: dict[str, Any]
    guideline: dict[str, Any]
    advisory: dict[str, Any] | None
    safety_decision: dict[str, Any]
    confidence: float
    execution_trace: list[dict[str, Any]]
    transitions: list[dict[str, str]]
    current_node: str
    status: str
    cost_telemetry: dict[str, Any]
    agent_foundation: dict[str, object]
    error: str | None
    _next_transition: str


NodeAction = Callable[[AgentState], AgentState]


class StateNode:
    """Explicit state graph node with conditional outgoing transitions."""

    def __init__(self, name: str, action: NodeAction) -> None:
        self.name = name
        self.action = action
        self.transitions: dict[str, StateNode] = {}

    def add_transition(self, on: str, to: StateNode) -> None:
        self.transitions[on] = to

    def run(self, state: AgentState) -> AgentState:
        state["current_node"] = self.name
        trace_start_index = len(state.get("execution_trace", []))
        try:
            next_state = self.action(state)
            next_node_key = next_state.pop("_next_transition", "success")
        except TimeoutError as exc:
            next_state = state.copy()
            next_state["error"] = f"Tool timeout in {self.name}: {exc}"
            next_node_key = (
                "tool_timeout" if "tool_timeout" in self.transitions else "failure"
            )
            _trace(
                next_state,
                self.name,
                f"{self.name}_timeout",
                {"error": next_state["error"]},
            )
        except (RuntimeError, ValueError, KeyError, LookupError, OSError) as exc:
            next_state = state.copy()
            next_state["error"] = str(exc)
            next_node_key = (
                "tool_timeout"
                if "timeout" in str(exc).lower() and "tool_timeout" in self.transitions
                else "failure"
            )
            _trace(
                next_state,
                self.name,
                f"{self.name}_error",
                {"error": next_state["error"]},
            )

        next_node = self.transitions.get(next_node_key)
        target_name = next_node.name if next_node else "terminal"
        transition_label = f"{self.name} --[{next_node_key}]--> {target_name}"
        next_state.setdefault("transitions", []).append(
            {
                "from_node": self.name,
                "transition": next_node_key,
                "to_node": target_name,
            }
        )
        trace_entries = next_state.setdefault("execution_trace", [])
        for entry in trace_entries[trace_start_index:]:
            entry["transition"] = transition_label

        if next_node:
            return next_node.run(next_state)
        return next_state


def save_run_state(state: AgentState) -> None:
    """Persist run state at the approval or terminal boundary for safe resumption."""
    serializable = {
        key: value for key, value in state.items() if not key.startswith("_")
    }
    now = datetime.now(UTC).isoformat()
    with connect() as db:
        existing = db.execute(
            "SELECT created_at FROM agent_runs WHERE run_id = ?",
            (state["run_id"],),
        ).fetchone()
        created_at = existing["created_at"] if existing else now
        db.execute(
            """
            INSERT OR REPLACE INTO agent_runs
              (run_id, ward, status, current_node, state_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                state["run_id"],
                state.get("ward", ""),
                state.get("status", "UNKNOWN"),
                state.get("current_node", "unknown"),
                json.dumps(serializable),
                created_at,
                now,
            ),
        )


def load_run_state(run_id: str) -> AgentState | None:
    """Load persisted run state by run_id."""
    with connect() as db:
        row = db.execute(
            "SELECT state_json FROM agent_runs WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if not row:
        return None
    loaded: AgentState = json.loads(row["state_json"])
    return loaded


def build_graph() -> StateNode:
    """Construct the explicit Ecovuna state graph with recovery and approval nodes."""
    start_node = StateNode("start", _start_node)
    plan_node = StateNode("plan", _plan_node)
    fetch_evidence_node = StateNode("plan_and_fetch", _plan_and_fetch)
    recover_node = StateNode("recover", _recover_node)
    citation_self_check_node = StateNode("citation_self_check", _citation_self_check)
    stage_write_action_node = StateNode("stage_write_action", _stage_write_action)
    human_approval_node = StateNode("human_approval", _human_approval_gate)
    safe_terminal_node = StateNode("safe_terminal", _safe_terminal_node)
    error_node = StateNode("error", _error_node)

    start_node.add_transition("success", plan_node)
    plan_node.add_transition("success", fetch_evidence_node)
    plan_node.add_transition("failure", error_node)

    fetch_evidence_node.add_transition("success", citation_self_check_node)
    fetch_evidence_node.add_transition("stale_data", recover_node)
    fetch_evidence_node.add_transition("tool_timeout", recover_node)
    fetch_evidence_node.add_transition("missing_evidence", recover_node)
    fetch_evidence_node.add_transition("failure", recover_node)

    recover_node.add_transition("recovered", citation_self_check_node)
    recover_node.add_transition("missing_evidence", safe_terminal_node)
    recover_node.add_transition("failure", error_node)

    citation_self_check_node.add_transition("success", stage_write_action_node)
    citation_self_check_node.add_transition("conflict_detected", safe_terminal_node)
    citation_self_check_node.add_transition("missing_evidence", safe_terminal_node)
    citation_self_check_node.add_transition("failure", error_node)

    stage_write_action_node.add_transition("success", human_approval_node)
    stage_write_action_node.add_transition("failure", error_node)

    return start_node


def _start_node(state: AgentState) -> AgentState:
    state.setdefault(
        "request",
        {
            "ward": state.get("ward", ""),
            "scenario_override": state.get("scenario_override", ""),
        },
    )
    state.setdefault("conflicts", [])
    state.setdefault("transitions", [])
    return state


def _plan_node(state: AgentState) -> AgentState:
    scenario = state.get("scenario_override", "").lower()
    ward = state.get("ward", "")
    stage = (
        "Flowering_Tasseling_41_65d"
        if "flower" in scenario
        else "Germination_0_14d"
    )
    anomaly = (
        "FLASH_FLOOD_WATERLOGGING"
        if "flood" in scenario or ward == "Ndhiwa"
        else "SUDDEN_DRY_SPELL"
    )
    plan = {
        "ward": ward,
        "target_growth_stage": stage,
        "hypothesis_anomaly": anomaly,
        "steps": [
            "fetch_kijanibox_telemetry",
            "fetch_open_meteo_context",
            "fetch_kalro_guidelines",
            "stage_advisory_for_wao_approval",
        ],
    }
    state["plan"] = plan
    _trace(state, "plan", "create_execution_plan", plan)
    return state


def _plan_and_fetch(state: AgentState) -> AgentState:
    from .mcp_server import (
        fetch_kijanibox_telemetry,
        fetch_open_meteo_context,
        fetch_ward_telemetry,
    )

    scenario = state.get("scenario_override", "").lower()
    if "simulate_timeout" in scenario:
        raise TimeoutError("Simulated telemetry provider timeout")

    ward_telemetry = fetch_ward_telemetry(state["ward"], state["run_id"])
    _trace(state, "plan_and_fetch", "fetch_ward_telemetry", ward_telemetry)

    telemetry = fetch_kijanibox_telemetry(state["ward"], state["run_id"])
    state["telemetry"] = telemetry
    _trace(state, "plan_and_fetch", "fetch_kijanibox_telemetry", telemetry)

    weather = fetch_open_meteo_context(state["ward"], state["run_id"])
    _trace(state, "plan_and_fetch", "fetch_open_meteo_context", weather)

    readings = telemetry.get("readings", [])
    state["evidence"] = {
        "telemetry": telemetry,
        "weather": weather,
        "freshness": telemetry.get("freshness", "cached"),
        "recovered": False,
    }
    if not readings:
        state["_next_transition"] = "missing_evidence"
    elif telemetry.get("freshness") == "stale" or "stale" in scenario:
        state["_next_transition"] = "stale_data"
    else:
        state["_next_transition"] = "success"
    return state


def _recover_node(state: AgentState) -> AgentState:
    ward = state["ward"]
    with connect() as db:
        rows = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM telemetry_cache WHERE ward = ? ORDER BY timestamp DESC",
                (ward,),
            )
        ]
    if rows:
        fallback_telemetry = {
            "ward": ward,
            "readings": rows,
            "source": "telemetry_cache_recovery",
            "freshness": "cached_recovery",
            "recovered_from": state.get("error") or "stale_or_missing_live_signal",
        }
        state["telemetry"] = fallback_telemetry
        state.setdefault("evidence", {})["telemetry"] = fallback_telemetry
        state["evidence"]["recovered"] = True
        state["error"] = None
        _trace(state, "recover", "fallback_telemetry_cache", fallback_telemetry)
        state["_next_transition"] = "recovered"
        return state

    failure_info = {
        "ward": ward,
        "reason": "No cached telemetry available for recovery.",
    }
    _trace(state, "recover", "fallback_telemetry_cache", failure_info)
    state["_next_transition"] = "missing_evidence"
    return state


def _citation_self_check(state: AgentState) -> AgentState:
    from .mcp_client import BORROWED_SERVER_ID, call_borrowed_reference_server
    from .mcp_server import (
        draft_localized_advisory,
        fetch_kalro_guidelines,
        prepare_evoucher_batch,
        search_agronomy_protocols,
    )
    from .research_connectors import gather_research_bundle
    from .safety import detect_signal_conflicts

    plan = state.get("plan", {})
    scenario = state.get("scenario_override", "").lower()
    stage = plan.get("target_growth_stage") or (
        "Flowering_Tasseling_41_65d"
        if "flower" in scenario
        else "Germination_0_14d"
    )
    anomaly = plan.get("hypothesis_anomaly") or (
        "FLASH_FLOOD_WATERLOGGING"
        if "flood" in scenario or state["ward"] == "Ndhiwa"
        else "SUDDEN_DRY_SPELL"
    )
    guideline = fetch_kalro_guidelines(
        "waterlogged maize" if anomaly.startswith("FLASH") else "Maize WH-505",
        stage,
        state["run_id"],
    )
    _trace(state, "citation_self_check", "fetch_kalro_guidelines", guideline)
    state["guideline"] = guideline

    rag_protocol = search_agronomy_protocols(
        crop="Maize WH-505",
        symptom=anomaly,
        ward_id=state["ward"],
        run_id=state["run_id"],
    )
    _trace(state, "citation_self_check", "search_agronomy_protocols", rag_protocol)

    evoucher_batch = prepare_evoucher_batch(
        ward_id=state["ward"],
        intervention_type=anomaly,
        run_id=state["run_id"],
    )
    _trace(state, "citation_self_check", "prepare_evoucher_batch", evoucher_batch)

    borrowed_ref = call_borrowed_reference_server(
        "file://data/kalro_bulletins/homabay_agronomy_2026.md",
        run_id=state["run_id"],
        rule_id=guideline["rule_id"],
        simulate_unavailable="borrowed_offline" in scenario,
    )
    _trace(
        state,
        "citation_self_check",
        "fetch",
        borrowed_ref,
        server=BORROWED_SERVER_ID,
    )
    state.setdefault("evidence", {})["borrowed_reference"] = borrowed_ref

    research_bundle = gather_research_bundle(
        run_id=state["run_id"],
        rule_id=guideline["rule_id"],
        bulletin_id=guideline["bulletin_id"],
        simulate_web_failure="web_offline" in scenario or "borrowed_offline" in scenario,
    )
    _trace(
        state,
        "citation_self_check",
        "ingest_document_source",
        research_bundle["document_source"],
        server="ecovuna-research-connector",
    )
    _trace(
        state,
        "citation_self_check",
        "fetch_official_web_source",
        research_bundle["web_source"],
        server="ecovuna-research-connector",
    )
    state["evidence"]["research_sources"] = research_bundle["sources"]
    if not research_bundle["citation_verified"]:
        state["_next_transition"] = "missing_evidence"
        return state

    pre_existing_conflicts = list(state.get("conflicts") or [])
    safety_report = detect_signal_conflicts(
        run_id=state["run_id"],
        ward=state["ward"],
        scenario_override=state.get("scenario_override", ""),
        telemetry=state.get("telemetry", {}),
        weather=(state.get("evidence") or {}).get("weather", {}),
        guideline=guideline,
    )
    combined_conflicts = pre_existing_conflicts + safety_report["conflicts"]
    state["conflicts"] = combined_conflicts
    state["safety_decision"] = safety_report["safety_decision"]
    state["confidence"] = (
        0.18 if pre_existing_conflicts else safety_report["confidence"]
    )
    _trace(state, "citation_self_check", "detect_signal_conflicts", safety_report)

    if combined_conflicts:
        state["_next_transition"] = "conflict_detected"
        return state

    with connect() as db:
        rows = db.execute(
            "SELECT plots.plot_id FROM plots JOIN farmers ON farmers.farmer_id = plots.farmer_id "
            "WHERE farmers.ward = ? LIMIT 8",
            (state["ward"],),
        ).fetchall()
    plot_ids = [row[0] for row in rows]
    sensor_ids = [
        reading["sensor_id"]
        for reading in state.get("telemetry", {}).get("readings", [])
        if "sensor_id" in reading
    ]
    if not plot_ids or not sensor_ids:
        state["_next_transition"] = "missing_evidence"
        return state

    voucher = (
        "EV-FUNG-2026"
        if anomaly.startswith("FLASH")
        else ("EV-FOLIAR-2026" if stage.startswith("Flowering") else "EV-HYDRO-2026")
    )
    english = (
        "Open drainage and apply fungicide."
        if anomaly.startswith("FLASH")
        else "Use foliar potassium and irrigation."
        if voucher.startswith("EV-FOLIAR")
        else "Block nitrogen top-dressing; protect roots with hydrogel."
    )
    citations = {
        "sensor_ids": sensor_ids,
        "plot_ids": plot_ids,
        "weather_bulletin_id": "KMD-2026-10-14",
        "kalro_rule_id": guideline["rule_id"],
    }
    state["draft"] = {
        "anomaly": anomaly,
        "stage": stage,
        "plot_ids": plot_ids,
        "voucher": voucher,
        "sms_swahili": "Mkulima: fuata ushauri wa afisa wako.",
        "sms_english": english,
        "voucher_total_kes": 1800.0,
        "citations": citations,
    }
    localized_draft = draft_localized_advisory(
        findings={"ward_id": state["ward"], "voucher_code": voucher},
        citations=citations,
        languages=["sw", "luo", "en"],
        run_id=state["run_id"],
    )
    _trace(state, "citation_self_check", "draft_localized_advisory", localized_draft)
    state.setdefault("evidence", {})["citations"] = citations
    state["_next_transition"] = "success"
    return state


def _stage_write_action(state: AgentState) -> AgentState:
    from .mcp_server import stage_advisory_for_wao_approval

    draft = state["draft"]
    advisory = stage_advisory_for_wao_approval(
        state["run_id"],
        state["ward"],
        draft["anomaly"],
        draft["stage"],
        draft["plot_ids"],
        draft["sms_swahili"],
        draft["sms_english"],
        draft["voucher"],
        draft["voucher_total_kes"],
        draft["citations"],
    )
    _trace(state, "stage_write_action", "stage_advisory_for_wao_approval", advisory)
    state["advisory"] = advisory
    state["_next_transition"] = "success"
    return state


def _human_approval_gate(state: AgentState) -> AgentState:
    from .mcp_server import request_wao_approval

    advisory = state.get("advisory") or {}
    wao_req = request_wao_approval(
        triage_id=state["run_id"],
        summary=f"Awaiting WAO approval for {state.get('ward')} ({advisory.get('evoucher_package_code')})",
    )
    _trace(state, "human_approval", "request_wao_approval", wao_req)
    approval_payload = {
        "status": "PENDING_WAO_APPROVAL",
        "gate": "WAO_HITL_GATE",
        "resumable": True,
        "advisory_id": advisory.get("advisory_id"),
        "approval_token": advisory.get("approval_token"),
        "dispatched": False,
    }
    state["approval"] = approval_payload
    state["status"] = "PAUSED_AT_WAO_GATE"
    _trace(state, "human_approval", "await_wao_decision", approval_payload)
    state["_next_transition"] = "awaiting_human_approval"
    return state


def _safe_terminal_node(state: AgentState) -> AgentState:
    has_conflicts = bool(state.get("conflicts"))
    reason = "conflict_detected" if has_conflicts else "missing_or_unverified_evidence"
    state["status"] = (
        "PAUSED_FOR_CONFLICT_VERIFICATION"
        if has_conflicts
        else "SAFE_TERMINAL_VERIFICATION_REQUIRED"
    )
    state["advisory"] = None
    safety_decision = state.get("safety_decision") or {}
    summary = {
        "status": state["status"],
        "reason": reason,
        "confidence": state.get("confidence", 0.15),
        "conflicts": state.get("conflicts", []),
        "clarification_question": safety_decision.get(
            "clarification_question",
            "Clarify ward/plot evidence or schedule field verification before staging.",
        ),
        "recommended_verification": safety_decision.get(
            "recommended_verification",
            "Conduct field verification before staging any advisory.",
        ),
        "action_required": "Clarify ward/plot evidence or schedule field verification before staging.",
    }
    _trace(state, "safe_terminal", "halt_ungrounded_staging", summary)
    state["_next_transition"] = "halted_safely"
    return state


def _error_node(state: AgentState) -> AgentState:
    state["status"] = "ERROR"
    _trace(
        state,
        "error",
        "terminal_error",
        {"error": state.get("error") or "Unknown execution failure"},
    )
    state["_next_transition"] = "error_terminal"
    return state


def resume_run_decision(
    run_id: str,
    approved: bool,
    wao_officer_name: str,
    notes: str = "",
    *,
    approval_token: str = "",
    policy_decision: dict[str, Any] | None = None,
) -> AgentState:
    """Resume a paused run at the human approval node without rerunning write steps."""
    state = load_run_state(run_id)
    status = "APPROVED_DISPATCHED" if approved else "REJECTED_FIELD_VISIT"
    dispatched = bool(approved)
    decision_payload = {
        "run_id": run_id,
        "approved": approved,
        "status": status,
        "dispatched": dispatched,
        "wao_officer_name": wao_officer_name,
        "approval_token": approval_token,
        "notes": notes,
        "policy_decision": policy_decision or {},
        "decided_at": datetime.now(UTC).isoformat(),
    }
    if state is None:
        state = {
            "run_id": run_id,
            "ward": "",
            "execution_trace": [],
            "transitions": [],
        }

    def _apply_decision(current: AgentState) -> AgentState:
        current["decision"] = decision_payload
        current["status"] = status
        current["approval"] = {
            **(current.get("approval") or {}),
            "status": status,
            "dispatched": dispatched,
            "wao_officer_name": wao_officer_name,
            "approval_token": approval_token,
            "decided_at": decision_payload["decided_at"],
        }
        if isinstance(current.get("advisory"), dict):
            from .multilingual import generate_advisory_variants

            current["advisory"]["status"] = status
            current["advisory"]["dispatched"] = dispatched
            current["advisory"]["approved_by_wao"] = wao_officer_name if approved else None
            current["advisory"]["output_variants"] = generate_advisory_variants(
                current["advisory"],
                approved_by_wao=wao_officer_name if approved else None,
            )
        _trace(current, "human_approval", "wao_decision", decision_payload)
        current["_next_transition"] = "approved" if approved else "rejected"
        return current

    approval_resume_node = StateNode("human_approval", _apply_decision)
    completed_node = StateNode("completed", lambda s: s)
    field_visit_node = StateNode("field_visit_required", lambda s: s)
    approval_resume_node.add_transition("approved", completed_node)
    approval_resume_node.add_transition("rejected", field_visit_node)

    updated_state = approval_resume_node.run(state)
    save_run_state(updated_state)
    return updated_state


def _trace(
    state: AgentState,
    node: str,
    tool: str,
    output: dict[str, Any],
    *,
    server: str = "Ecovuna_Telemetry",
) -> None:
    state.setdefault("execution_trace", []).append(
        {
            "node": node,
            "tool": tool,
            "server": server,
            "latency_ms": 1,
            "output": output,
        }
    )
