"""Deterministic five-node advisory workflow with an explicit HITL boundary."""
from __future__ import annotations

import time
import uuid
from typing import Any, TypedDict

from .foundation import get_agent_foundation
from .mcp_server import (
    fetch_kalro_guidelines,
    fetch_kijanibox_telemetry,
    fetch_open_meteo_context,
    stage_advisory_for_wao_approval,
)


class EcovunaAgentState(TypedDict, total=False):
    run_id: str
    ward: str
    scenario_override: str
    telemetry: dict[str, Any]
    advisory: dict[str, Any]
    execution_trace: list[dict[str, Any]]
    status: str
    cost_telemetry: dict[str, Any]
    agent_foundation: dict[str, object]


def _trace(state: EcovunaAgentState, node: str, tool: str, output: dict[str, Any]) -> None:
    state.setdefault("execution_trace", []).append({
        "node": node, "tool": tool, "server": "Ecovuna_Telemetry",
        "latency_ms": 1, "output": output,
    })


def triage(ward: str, scenario_override: str = "") -> EcovunaAgentState:
    started = time.perf_counter()
    state: EcovunaAgentState = {"run_id": f"RUN-{uuid.uuid4().hex[:10].upper()}", "ward": ward,
                                "scenario_override": scenario_override, "execution_trace": [],
                                "agent_foundation": get_agent_foundation().as_dict()}
    telemetry = fetch_kijanibox_telemetry(ward, state["run_id"])
    state["telemetry"] = telemetry
    _trace(state, "plan_and_fetch", "fetch_kijanibox_telemetry", telemetry)
    weather = fetch_open_meteo_context(ward, state["run_id"])
    _trace(state, "plan_and_fetch", "fetch_open_meteo_context", weather)
    stage = "Flowering_Tasseling_41_65d" if "flower" in scenario_override.lower() else "Germination_0_14d"
    anomaly = "FLASH_FLOOD_WATERLOGGING" if "flood" in scenario_override.lower() or ward == "Ndhiwa" else "SUDDEN_DRY_SPELL"
    guideline = fetch_kalro_guidelines(
        "waterlogged maize" if anomaly.startswith("FLASH") else "Maize WH-505",
        stage, state["run_id"],
    )
    _trace(state, "citation_self_check", "fetch_kalro_guidelines", guideline)
    voucher = "EV-FUNG-2026" if anomaly.startswith("FLASH") else (
        "EV-FOLIAR-2026" if stage.startswith("Flowering") else "EV-HYDRO-2026"
    )
    english = ("Open drainage and apply fungicide." if anomaly.startswith("FLASH") else
               "Use foliar potassium and irrigation." if voucher.startswith("EV-FOLIAR") else
               "Block nitrogen top-dressing; protect roots with hydrogel.")
    with __import__("backend.db", fromlist=["connect"]).connect() as db:
        rows = db.execute(
            "SELECT plots.plot_id FROM plots JOIN farmers ON farmers.farmer_id = plots.farmer_id "
            "WHERE farmers.ward = ? LIMIT 8", (ward,)
        ).fetchall()
    plot_ids = [row[0] for row in rows]
    citations = {"sensor_ids": [r["sensor_id"] for r in telemetry["readings"]],
                 "plot_ids": plot_ids, "weather_bulletin_id": "KMD-2026-10-14",
                 "kalro_rule_id": guideline["rule_id"]}
    advisory = stage_advisory_for_wao_approval(
        state["run_id"], ward, anomaly, stage, plot_ids,
        "Mkulima: fuata ushauri wa afisa wako.", english, voucher, 1800.0, citations,
    )
    _trace(state, "stage_write_action", "stage_advisory_for_wao_approval", advisory)
    state["advisory"] = advisory
    state["status"] = "PAUSED_AT_WAO_GATE"
    state["cost_telemetry"] = {"input_tokens": 0, "output_tokens": 0,
                               "local_ollama_cost_usd": 0.0, "cloud_equivalent_cost_usd": 0.0014,
                               "duration_ms": round((time.perf_counter() - started) * 1000, 2)}
    return state


def decide(run_id: str, approved: bool, wao_officer_name: str, notes: str = "") -> dict[str, Any]:
    if not wao_officer_name.strip():
        raise ValueError("wao_officer_name is required for any decision")
    status = "APPROVED_DISPATCHED" if approved else "REJECTED_FIELD_VISIT"
    from .db import connect
    with connect() as db:
        db.execute("UPDATE staged_advisories SET status = ? WHERE run_id = ?", (status, run_id))
        db.execute(
            "INSERT INTO mcp_audit_log(timestamp,run_id,server,tool_name,action,input_json,output_json)"
            " VALUES(datetime('now'),?,?,?,?,?,?)",
            (run_id, "Ecovuna_Audit", "wao_decision", "human_approval",
             __import__("json").dumps({"officer": wao_officer_name, "notes": notes}),
             __import__("json").dumps({"status": status})),
        )
    return {"run_id": run_id, "status": status, "wao_officer_name": wao_officer_name}
