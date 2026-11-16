"""Project-owned Ecovuna Telemetry MCP server runtime and tool registrations (#11)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .db import connect, initialize, insert_json
from .firestore_sync import sync_advisory_state
from .kijanispace import KijaniSpaceError, fetch_land, normalize_land
from .policy import enforce_stage_policy, mint_approval_token

SERVER_ID = "ecovuna-telemetry"
SERVER_NAME = "Ecovuna Telemetry"
SERVER_CAPABILITIES = {
    "tools": {"listChanged": False},
    "resources": {"subscribe": False},
    "offlineFallback": True,
}

TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "name": "fetch_kijanibox_telemetry",
        "description": "Fetch normalized soil moisture and temperature readings for a Homa Bay ward with offline cache fallback.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ward": {"type": "string", "description": "Administrative ward name"},
                "run_id": {"type": "string", "description": "Active agent run identifier"},
            },
            "required": ["ward", "run_id"],
        },
    },
    {
        "name": "fetch_open_meteo_context",
        "description": "Fetch 7-day precipitation and rainfall anomaly context for a ward.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ward": {"type": "string", "description": "Administrative ward name"},
                "run_id": {"type": "string", "description": "Active agent run identifier"},
            },
            "required": ["ward", "run_id"],
        },
    },
    {
        "name": "fetch_kalro_guidelines",
        "description": "Lookup grounded KALRO agronomic rule and KMD bulletin IDs for a crop and growth stage.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "crop": {"type": "string", "description": "Target crop or condition"},
                "growth_stage": {"type": "string", "description": "Crop growth stage"},
                "run_id": {"type": "string", "description": "Active agent run identifier"},
            },
            "required": ["crop", "growth_stage", "run_id"],
        },
    },
    {
        "name": "stage_advisory_for_wao_approval",
        "description": "Stage a cited farmer advisory and e-voucher package at the named WAO approval gate.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "run_id": {"type": "string"},
                "ward": {"type": "string"},
                "anomaly_type": {"type": "string"},
                "target_growth_stage": {"type": "string"},
                "plot_ids": {"type": "array", "items": {"type": "string"}},
                "sms_swahili": {"type": "string"},
                "sms_english": {"type": "string"},
                "voucher_code": {"type": "string"},
                "voucher_total_kes": {"type": "number"},
                "citations": {"type": "object"},
            },
            "required": [
                "run_id",
                "ward",
                "anomaly_type",
                "target_growth_stage",
                "plot_ids",
                "sms_swahili",
                "sms_english",
                "voucher_code",
                "voucher_total_kes",
                "citations",
            ],
        },
    },
]


def _audit(
    run_id: str,
    tool_name: str,
    inputs: dict[str, Any],
    output: dict[str, Any],
    *,
    server: str = "Ecovuna_Telemetry",
    action: str = "tool_call",
) -> None:
    initialize()
    with connect() as db:
        insert_json(
            db,
            "mcp_audit_log",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "server": server,
                "tool_name": tool_name,
                "action": action,
                "input_json": inputs,
                "output_json": output,
            },
        )


def fetch_kijanibox_telemetry(ward: str, run_id: str) -> dict[str, Any]:
    live_error = ""
    with connect() as db:
        plot = db.execute(
            """
            SELECT plots.latitude, plots.longitude, plots.kijanibox_sensor_id
            FROM plots JOIN farmers ON farmers.farmer_id = plots.farmer_id
            WHERE farmers.ward = ? ORDER BY plots.plot_id LIMIT 1
            """,
            (ward,),
        ).fetchone()
        if plot:
            try:
                reading = normalize_land(
                    ward,
                    plot["kijanibox_sensor_id"],
                    plot["latitude"],
                    plot["longitude"],
                    fetch_land(plot["latitude"], plot["longitude"]),
                )
                insert_json(db, "telemetry_cache", reading)
                live_output = {
                    "ward": ward,
                    "readings": [reading],
                    "source": "KijaniSpace",
                    "freshness": "live",
                }
            except KijaniSpaceError as exc:
                live_error = str(exc)
                live_output = None
        else:
            live_output = None
        if live_output:
            output = live_output
        else:
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM telemetry_cache WHERE ward = ? ORDER BY timestamp DESC",
                    (ward,),
                )
            ]
            output = {
                "ward": ward,
                "readings": rows,
                "source": "telemetry_cache",
                "freshness": "cached",
                "live_error": live_error,
            }
    _audit(run_id, "fetch_kijanibox_telemetry", {"ward": ward}, output)
    return output


def fetch_open_meteo_context(ward: str, run_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            "SELECT precipitation_7d_mm, rainfall_anomaly_mm FROM telemetry_cache WHERE ward = ?",
            (ward,),
        ).fetchone()
    output = {
        "ward": ward,
        "precipitation_7d_mm": row[0] if row else 0,
        "source": "Open-Meteo fixture",
    }
    _audit(run_id, "fetch_open_meteo_context", {"ward": ward}, output)
    return output


def fetch_kalro_guidelines(
    crop: str, growth_stage: str, run_id: str
) -> dict[str, Any]:
    rule = (
        "KALRO-HB-2026-03"
        if "water" in crop.lower()
        else ("KALRO-HB-2026-02" if "Flowering" in growth_stage else "KALRO-HB-2026-01")
    )
    output = {
        "crop": crop,
        "growth_stage": growth_stage,
        "rule_id": rule,
        "bulletin_id": "KMD-2026-10-14",
    }
    _audit(
        run_id,
        "fetch_kalro_guidelines",
        {"crop": crop, "growth_stage": growth_stage},
        output,
    )
    return output


def stage_advisory_for_wao_approval(
    run_id: str,
    ward: str,
    anomaly_type: str,
    target_growth_stage: str,
    plot_ids: list[str],
    sms_swahili: str,
    sms_english: str,
    voucher_code: str,
    voucher_total_kes: float,
    citations: dict[str, Any],
    channel: str = "agent",
) -> dict[str, Any]:
    policy_check = enforce_stage_policy(
        run_id=run_id,
        plot_ids=plot_ids,
        citations=citations,
        channel=channel,
    )
    advisory_id = f"ADV-{uuid.uuid4().hex[:10].upper()}"
    approval_token = mint_approval_token(run_id, advisory_id)
    per_farmer = voucher_total_kes / len(plot_ids)
    with connect() as db:
        insert_json(
            db,
            "staged_advisories",
            {
                "advisory_id": advisory_id,
                "run_id": run_id,
                "ward": ward,
                "anomaly_type": anomaly_type,
                "target_growth_stage": target_growth_stage,
                "affected_plot_ids_json": plot_ids,
                "affected_household_count": len(plot_ids),
                "draft_sms_swahili": sms_swahili,
                "draft_sms_english": sms_english,
                "ussd_menu_payload": "*384*55#",
                "evoucher_package_code": voucher_code,
                "evoucher_total_kes": voucher_total_kes,
                "per_farmer_kes": per_farmer,
                "citations_json": citations,
                "status": "PENDING_WAO_APPROVAL",
            },
        )
    output = {
        "advisory_id": advisory_id,
        "run_id": run_id,
        "ward": ward,
        "anomaly_type": anomaly_type,
        "target_growth_stage": target_growth_stage,
        "affected_plot_ids": plot_ids,
        "affected_household_count": len(plot_ids),
        "draft_sms_swahili": sms_swahili,
        "draft_sms_english": sms_english,
        "ussd_menu_payload": "*384*55#",
        "evoucher_package_code": voucher_code,
        "evoucher_total_kes": voucher_total_kes,
        "per_farmer_kes": per_farmer,
        "citations": citations,
        "status": "PENDING_WAO_APPROVAL",
        "dispatched": False,
        "approval_token": approval_token,
        "policy_decision": policy_check,
        "gate_message": "Waiting for named Ward Agricultural Officer sign-off",
    }
    _audit(run_id, "stage_advisory_for_wao_approval", {"ward": ward}, output)
    sync_advisory_state(output)
    return output


def build_fastmcp_server() -> Any:
    """Create and configure the FastMCP runtime server instance."""
    from fastmcp import FastMCP

    server = FastMCP(SERVER_NAME)
    server.tool(
        name="fetch_kijanibox_telemetry",
        description=TOOL_SCHEMAS[0]["description"],
    )(fetch_kijanibox_telemetry)
    server.tool(
        name="fetch_open_meteo_context",
        description=TOOL_SCHEMAS[1]["description"],
    )(fetch_open_meteo_context)
    server.tool(
        name="fetch_kalro_guidelines",
        description=TOOL_SCHEMAS[2]["description"],
    )(fetch_kalro_guidelines)
    server.tool(
        name="stage_advisory_for_wao_approval",
        description=TOOL_SCHEMAS[3]["description"],
    )(stage_advisory_for_wao_approval)
    return server


def list_registered_mcp_tools() -> list[dict[str, Any]]:
    """Return registered tool definitions with JSON schemas and server metadata."""
    return [dict(schema, server_id=SERVER_ID) for schema in TOOL_SCHEMAS]


def invoke_project_mcp_tool(
    tool_name: str, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Invoke a registered tool on the project-owned MCP server boundary."""
    dispatch = {
        "fetch_kijanibox_telemetry": lambda args: fetch_kijanibox_telemetry(
            args["ward"], args["run_id"]
        ),
        "fetch_open_meteo_context": lambda args: fetch_open_meteo_context(
            args["ward"], args["run_id"]
        ),
        "fetch_kalro_guidelines": lambda args: fetch_kalro_guidelines(
            args["crop"], args["growth_stage"], args["run_id"]
        ),
        "stage_advisory_for_wao_approval": lambda args: stage_advisory_for_wao_approval(
            args["run_id"],
            args["ward"],
            args["anomaly_type"],
            args["target_growth_stage"],
            args["plot_ids"],
            args["sms_swahili"],
            args["sms_english"],
            args["voucher_code"],
            float(args["voucher_total_kes"]),
            args["citations"],
            channel="mcp",
        ),
    }
    if tool_name not in dispatch:
        raise KeyError(f"Unknown MCP tool '{tool_name}' on {SERVER_ID}")
    return dispatch[tool_name](arguments)


if __name__ == "__main__":
    build_fastmcp_server().run()
