"""Deterministic state-graph advisory workflow with an explicit HITL boundary."""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

from .db import connect
from .foundation import get_agent_foundation
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
    return final_state


def decide(
    run_id: str,
    approved: bool,
    wao_officer_name: str,
    notes: str = "",
) -> dict[str, Any]:
    if not wao_officer_name.strip():
        raise ValueError("wao_officer_name is required for any decision")
    resumed_state = resume_run_decision(
        run_id=run_id,
        approved=approved,
        wao_officer_name=wao_officer_name.strip(),
        notes=notes,
    )
    status = resumed_state["status"]
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
                json.dumps({"officer": wao_officer_name.strip(), "notes": notes}),
                json.dumps({"status": status}),
            ),
        )
    return {
        "run_id": run_id,
        "status": status,
        "wao_officer_name": wao_officer_name.strip(),
    }
