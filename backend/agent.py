"""Deterministic state-graph advisory workflow with an explicit HITL boundary."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .artifacts_repository import repository as artifact_repo
from .db import connect, sync_dynamodb_tables
from .foundation import get_agent_foundation
from .policy import enforce_decision_policy
from .state_graph import AgentState, build_graph, resume_run_decision, save_run_state


def triage(ward: str, scenario_override: str = "") -> AgentState:
    started = time.perf_counter()
    state: AgentState = {
        "run_id": f"RUN-{uuid.uuid4().hex[:10].upper()}",
        "ward": ward,
        "scenario_override": scenario_override,
        "request": {"ward": ward, "scenario_override": scenario_override},
        "execution_trace": [],
        "transitions": [],
        "conflicts": [],
        "agent_foundation": get_agent_foundation().as_dict(),
        "error": None,
    }

    graph = build_graph()
    final_state = graph.run(state)

    if final_state.get("error") and final_state.get("status") not in {
        "PAUSED_AT_WAO_GATE",
        "PAUSED_FOR_CONFLICT_VERIFICATION",
        "SAFE_TERMINAL_VERIFICATION_REQUIRED",
    }:
        final_state["status"] = "ERROR"
    elif "status" not in final_state:
        final_state["status"] = "PAUSED_AT_WAO_GATE"

    final_state["cost_telemetry"] = {
        "input_tokens": 0,
        "output_tokens": 0,
        "local_ollama_cost_usd": 0.0,
        "cloud_equivalent_cost_usd": 0.0014,
        "duration_ms": round((time.perf_counter() - started) * 1000, 2),
    }
    save_run_state(final_state)
    artifact_repo.record_immutable_tool_events(
        run_id=final_state["run_id"],
        execution_trace=final_state.get("execution_trace", []),
    )
    final_state["artifacts"] = artifact_repo.generate_and_persist_artifacts(
        run=final_state
    )
    return final_state


def decide(
    run_id: str,
    approved: bool,
    wao_officer_name: str,
    notes: str = "",
    *,
    approval_token: str | None = None,
    channel: str = "api",
    require_explicit_token: bool = False,
) -> dict[str, Any]:
    checked = enforce_decision_policy(
        run_id=run_id,
        approved=approved,
        wao_officer_name=wao_officer_name,
        approval_token=approval_token,
        channel=channel,
        require_explicit_token=require_explicit_token,
    )
    officer = checked["officer"]
    resumed_state = resume_run_decision(
        run_id=run_id,
        approved=approved,
        wao_officer_name=officer,
        notes=notes,
        approval_token=checked["approval_token"],
        policy_decision=checked["policy_decision"],
    )
    artifact_repo.record_immutable_tool_events(
        run_id=run_id,
        execution_trace=resumed_state.get("execution_trace", []),
    )
    updated_artifacts = artifact_repo.generate_and_persist_artifacts(
        run=resumed_state,
        approved_by_wao=officer if approved else None,
    )
    status = resumed_state["status"]
    dispatched = bool(approved)
    campaign_dispatch = {
        "triage_id": run_id,
        "hitl_approved": dispatched,
        "status": "DISPATCHED" if dispatched else "FLAGGED_FOR_VISIT",
        "approved_by": officer,
        "gateway": "Africa's Talking SMS & USSD Gateway",
        "ussd_channel": "*384*55#",
        "farmers_reached": 1850,
        "lead_recipient": "Mama Atieno (+254722841901, Rachuonyo North)",
        "cost_per_ward_alert_usd": 11.40,
    }
    sync_dynamodb_tables(hitl_audit=campaign_dispatch)
    with connect() as db:
        db.execute(
            "UPDATE staged_advisories SET status = ? WHERE run_id = ?",
            (status, run_id),
        )
        db.execute(
            "INSERT INTO mcp_audit_log(timestamp,run_id,server,tool_name,action,input_json,output_json)"
            " VALUES(datetime('now'),?,?,?,?,?,?)",
            (
                run_id,
                "Ecovun-Audit",
                "wao_decision",
                "human_approval",
                json.dumps(
                    {
                        "officer": officer,
                        "notes": notes,
                        "approval_token": checked["approval_token"],
                        "channel": channel,
                    }
                ),
                json.dumps(
                    {
                        "status": status,
                        "dispatched": dispatched,
                        "advisory_id": checked["advisory_id"],
                    }
                ),
            ),
        )
    return {
        "run_id": run_id,
        "status": status,
        "dispatched": dispatched,
        "wao_officer_name": officer,
        "advisory_id": checked["advisory_id"],
        "approval_token": checked["approval_token"],
        "policy_decision": checked["policy_decision"],
        "artifacts": updated_artifacts,
        "campaign_dispatch": campaign_dispatch,
    }
