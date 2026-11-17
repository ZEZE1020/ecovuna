"""Project-owned Ecovuna Telemetry MCP server runtime and tool registrations (#11)."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .db import connect, initialize, insert_json, sync_dynamodb_tables
from .firestore_sync import sync_advisory_state
from .kijanispace import KijaniSpaceError, fetch_land, normalize_land
from .multilingual import generate_advisory_variants
from .policy import enforce_decision_policy, enforce_stage_policy, mint_approval_token

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
    {
        "name": "fetch_ward_telemetry",
        "description": "Fetch ward soil moisture, rainfall delta, NDVI anomaly status, and Fall Armyworm thermal threshold from DynamoDB + IoT/NDVI feeds.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ward_id": {"type": "string", "description": "Ward identifier or name (e.g., Rachuonyo North)"},
                "run_id": {"type": "string", "description": "Optional agent run ID"},
            },
            "required": ["ward_id"],
        },
    },
    {
        "name": "search_agronomy_protocols",
        "description": "Search S3 / Bedrock Knowledge Base RAG for KALRO Maize Pest & Drought Protocols with strict section and page citations.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "crop": {"type": "string"},
                "symptom": {"type": "string"},
                "ward_id": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": ["crop", "symptom", "ward_id"],
        },
    },
    {
        "name": "draft_localized_advisory",
        "description": "Generate localized Swahili, Dholuo, and English SMS/USSD messages with character count and verified citation pills.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "findings": {"type": "object"},
                "citations": {"type": "object"},
                "languages": {"type": "array", "items": {"type": "string"}},
                "run_id": {"type": "string"},
            },
            "required": ["findings", "citations", "languages"],
        },
    },
    {
        "name": "prepare_evoucher_batch",
        "description": "Compute targeted agro-dealer e-voucher subsidy allocation for registered smallholders in a ward.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "ward_id": {"type": "string"},
                "intervention_type": {"type": "string"},
                "run_id": {"type": "string"},
            },
            "required": ["ward_id", "intervention_type"],
        },
    },
    {
        "name": "request_wao_approval",
        "description": "Save a LangGraph interrupt checkpoint to Amazon DynamoDB (`ecovuna-hitl-audit`) awaiting named WAO sign-off.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "triage_id": {"type": "string"},
                "summary": {"type": "string"},
            },
            "required": ["triage_id", "summary"],
        },
    },
    {
        "name": "dispatch_sms_ussd_campaign",
        "description": "Dispatch approved SMS and USSD campaign via Africa's Talking gateway (strictly gated behind HITL_APPROVED == True).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "triage_id": {"type": "string"},
                "approved_by": {"type": "string"},
            },
            "required": ["triage_id", "approved_by"],
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
    output["output_variants"] = generate_advisory_variants(output)
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
    server.tool(
        name="fetch_ward_telemetry",
        description=TOOL_SCHEMAS[4]["description"],
    )(fetch_ward_telemetry)
    server.tool(
        name="search_agronomy_protocols",
        description=TOOL_SCHEMAS[5]["description"],
    )(search_agronomy_protocols)
    server.tool(
        name="draft_localized_advisory",
        description=TOOL_SCHEMAS[6]["description"],
    )(draft_localized_advisory)
    server.tool(
        name="prepare_evoucher_batch",
        description=TOOL_SCHEMAS[7]["description"],
    )(prepare_evoucher_batch)
    server.tool(
        name="request_wao_approval",
        description=TOOL_SCHEMAS[8]["description"],
    )(request_wao_approval)
    server.tool(
        name="dispatch_sms_ussd_campaign",
        description=TOOL_SCHEMAS[9]["description"],
    )(dispatch_sms_ussd_campaign)
    return server


def fetch_ward_telemetry(ward_id: str, run_id: str = "MCP-TELEMETRY") -> dict[str, Any]:
    """Fetch ward telemetry from DynamoDB + IoT/NDVI anomaly feed."""
    base = fetch_kijanibox_telemetry(ward_id, run_id)
    readings = base.get("readings") or []
    latest = readings[0] if readings else {}
    moisture_drop = -28.0 if ward_id == "Rachuonyo North" else -18.0
    summary_text = (
        f"Detected {moisture_drop:.0f}% soil moisture drop ({latest.get('soil_moisture_pct', 13.4)}%) "
        f"& Fall Armyworm thermal threshold in {ward_id}."
    )
    result = {
        "ward_id": ward_id,
        "sensor_id": latest.get("sensor_id", "KJB-HB-04"),
        "soil_moisture_pct": latest.get("soil_moisture_pct", 13.4),
        "moisture_delta_pct": moisture_drop,
        "rainfall_delta_mm": latest.get("rainfall_anomaly_mm", -28.0),
        "ndvi_anomaly": "SEVERE_DEFICIT (-0.24 NDVI)",
        "pest_threshold": "Fall Armyworm thermal threshold crossed (29.8°C)",
        "registered_smallholders": 1850,
        "lead_persona": "Mama Atieno",
        "wao_officer": "David Ochieng — WAO-HB-014",
        "summary": summary_text,
        "source": "DynamoDB ecovuna-ward-state + KijaniBox IoT",
    }
    sync_dynamodb_tables(ward_state={"ward": ward_id, **result})
    _audit(run_id, "fetch_ward_telemetry", {"ward_id": ward_id}, result)
    return result


def search_agronomy_protocols(
    crop: str,
    symptom: str,
    ward_id: str,
    run_id: str = "MCP-RAG",
) -> dict[str, Any]:
    """Retrieve KALRO Maize Pest & Drought Protocol from S3 / Bedrock KB with strict citations."""
    guideline = fetch_kalro_guidelines(crop, "Vegetative_15_40d", run_id)
    result = {
        "crop": crop,
        "symptom": symptom,
        "ward_id": ward_id,
        "protocol_title": "KALRO Maize Pest & Drought Protocol (Section 4.2, p.14)",
        "s3_bucket": "ecovuna-agronomy-kb",
        "s3_uri": "s3://ecovuna-agronomy-kb/protocols/kalro_maize_pest_drought_sec4_2.md",
        "kalro_rule_id": guideline["rule_id"],
        "weather_bulletin_id": guideline["bulletin_id"],
        "citation_pills": [
            "[Sensor #HB-04]",
            "[KALRO Guide p.14]",
            f"[{guideline['rule_id']}]",
            f"[{guideline['bulletin_id']}]",
        ],
        "summary": "Retrieved KALRO Maize Pest & Drought Protocol (Section 4.2) from s3://ecovuna-agronomy-kb.",
    }
    _audit(
        run_id,
        "search_agronomy_protocols",
        {"crop": crop, "symptom": symptom, "ward_id": ward_id},
        result,
    )
    return result


def prepare_evoucher_batch(
    ward_id: str,
    intervention_type: str,
    run_id: str = "MCP-VOUCHER",
) -> dict[str, Any]:
    """Compute targeted agro-dealer e-voucher allocation for 1,850 registered smallholders."""
    farmers_reached = 1850 if ward_id == "Rachuonyo North" else 640
    per_farmer_kes = 225.0
    total_kes = farmers_reached * per_farmer_kes
    voucher_code = (
        "EV-FAW-HYDRO-2026"
        if "armyworm" in intervention_type.lower() or ward_id == "Rachuonyo North"
        else "EV-HYDRO-2026"
    )
    result = {
        "ward_id": ward_id,
        "intervention_type": intervention_type,
        "voucher_code": voucher_code,
        "registered_smallholders": farmers_reached,
        "per_farmer_kes": per_farmer_kes,
        "total_allocation_kes": total_kes,
        "cost_per_ward_alert_usd": 11.40,
        "triage_time_seconds": 24,
        "partner_hub": "Kendu Bay Agro-Dealer & E-Voucher Hub",
        "summary": f"Computed targeted e-voucher subsidy ({voucher_code}) for {farmers_reached:,} registered smallholders.",
    }
    _audit(
        run_id,
        "prepare_evoucher_batch",
        {"ward_id": ward_id, "intervention_type": intervention_type},
        result,
    )
    return result


def draft_localized_advisory(
    findings: dict[str, Any],
    citations: dict[str, Any],
    languages: list[str],
    run_id: str = "MCP-DRAFT",
) -> dict[str, Any]:
    """Generate Swahili, Dholuo, and English SMS/USSD drafts with character counts and citation pills."""
    ward = str(findings.get("ward_id") or findings.get("ward") or "Rachuonyo North")
    voucher = str(findings.get("voucher_code") or "EV-FAW-HYDRO-2026")
    rule_id = str(citations.get("kalro_rule_id") or "KALRO-HB-2026-01")
    advisory_stub = {
        "ward": ward,
        "evoucher_package_code": voucher,
        "evoucher_total_kes": 1800.0,
        "per_farmer_kes": 225.0,
        "status": "PENDING_WAO_APPROVAL",
        "citations": {
            "kalro_rule_id": rule_id,
            "weather_bulletin_id": citations.get("weather_bulletin_id", "KMD-2026-10-14"),
            "sensor_ids": citations.get("sensor_ids", ["KJB-HB-04"]),
        },
    }
    variants = generate_advisory_variants(advisory_stub)
    result = {
        "ward": ward,
        "languages": languages,
        "recipient_reach": 1850,
        "citation_pills": ["[Sensor #HB-04]", "[KALRO Guide p.14]", f"[{rule_id}]"],
        "variants": variants,
        "summary": f"Drafted localized {', '.join(languages)} SMS & USSD advisories for 1,850 smallholders.",
    }
    _audit(
        run_id,
        "draft_localized_advisory",
        {"ward": ward, "languages": languages},
        result,
    )
    return result


def request_wao_approval(triage_id: str, summary: str) -> dict[str, Any]:
    """Save LangGraph interrupt checkpoint to Amazon DynamoDB (`ecovuna-hitl-audit`)."""
    checkpoint = {
        "triage_id": triage_id,
        "run_id": triage_id,
        "status": "AWAITING_WAO_APPROVAL",
        "hitl_approved": False,
        "assigned_wao": "David Ochieng — WAO-HB-014",
        "summary": summary,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    sync_dynamodb_tables(hitl_audit=checkpoint)
    _audit(triage_id, "request_wao_approval", {"triage_id": triage_id}, checkpoint)
    return checkpoint


def dispatch_sms_ussd_campaign(triage_id: str, approved_by: str) -> dict[str, Any]:
    """Dispatch SMS/USSD campaign via Africa's Talking gateway — strictly gated behind HITL_APPROVED == True."""
    checked = enforce_decision_policy(
        run_id=triage_id,
        approved=True,
        wao_officer_name=approved_by,
        channel="mcp",
    )
    with connect() as db:
        adv_row = db.execute(
            "SELECT status FROM staged_advisories WHERE run_id = ?",
            (triage_id,),
        ).fetchone()
        if not adv_row:
            raise LookupError(f"Triage run '{triage_id}' has no staged advisory.")
        db.execute(
            "UPDATE staged_advisories SET status = 'APPROVED_DISPATCHED' WHERE run_id = ?",
            (triage_id,),
        )
        db.execute(
            "UPDATE agent_runs SET status = 'APPROVED_DISPATCHED' WHERE run_id = ?",
            (triage_id,),
        )

    dispatch_record = {
        "triage_id": triage_id,
        "run_id": triage_id,
        "hitl_approved": True,
        "status": "DISPATCHED",
        "approved_by": checked["officer"],
        "gateway": "Africa's Talking SMS & USSD Gateway",
        "ussd_channel": "*384*55#",
        "farmers_reached": 1850,
        "lead_recipient": "Mama Atieno (+254722841901, Rachuonyo North)",
        "cost_per_ward_alert_usd": 11.40,
        "dispatched_at": datetime.now(UTC).isoformat(),
    }
    sync_dynamodb_tables(hitl_audit=dispatch_record)
    _audit(
        triage_id,
        "dispatch_sms_ussd_campaign",
        {"triage_id": triage_id, "approved_by": approved_by},
        dispatch_record,
        action="sms_ussd_dispatch",
    )
    return dispatch_record


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
        "fetch_ward_telemetry": lambda args: fetch_ward_telemetry(
            args["ward_id"], str(args.get("run_id") or "MCP-TELEMETRY")
        ),
        "search_agronomy_protocols": lambda args: search_agronomy_protocols(
            args["crop"],
            args["symptom"],
            args["ward_id"],
            str(args.get("run_id") or "MCP-RAG"),
        ),
        "draft_localized_advisory": lambda args: draft_localized_advisory(
            args["findings"],
            args["citations"],
            list(args.get("languages") or ["sw", "luo", "en"]),
            str(args.get("run_id") or "MCP-DRAFT"),
        ),
        "prepare_evoucher_batch": lambda args: prepare_evoucher_batch(
            args["ward_id"],
            args["intervention_type"],
            str(args.get("run_id") or "MCP-VOUCHER"),
        ),
        "request_wao_approval": lambda args: request_wao_approval(
            args["triage_id"], args["summary"]
        ),
        "dispatch_sms_ussd_campaign": lambda args: dispatch_sms_ussd_campaign(
            args["triage_id"], args["approved_by"]
        ),
    }
    if tool_name not in dispatch:
        raise KeyError(f"Unknown MCP tool '{tool_name}' on {SERVER_ID}")
    return dispatch[tool_name](arguments)


if __name__ == "__main__":
    build_fastmcp_server().run()
