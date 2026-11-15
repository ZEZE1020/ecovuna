"""Custom telemetry MCP tool implementations.

The functions are intentionally usable without an MCP dependency so offline CI
can exercise the safety boundary. FastMCP can expose the same functions when
the optional MCP runtime is installed.
"""
from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from .db import connect, initialize, insert_json
from .firestore_sync import sync_advisory_state
from .kijanispace import KijaniSpaceError, fetch_land, normalize_land


def _audit(run_id: str, tool_name: str, inputs: dict[str, Any], output: dict[str, Any]) -> None:
    initialize()
    with connect() as db:
        insert_json(db, "mcp_audit_log", {
            "timestamp": datetime.now(UTC).isoformat(), "run_id": run_id,
            "server": "Ecovuna_Telemetry", "tool_name": tool_name, "action": "tool_call",
            "input_json": inputs, "output_json": output,
        })


def fetch_kijanibox_telemetry(ward: str, run_id: str) -> dict[str, Any]:
    live_error = ""
    with connect() as db:
        plot = db.execute(
            """
            SELECT plots.latitude, plots.longitude, plots.kijanibox_sensor_id
            FROM plots JOIN farmers ON farmers.farmer_id = plots.farmer_id
            WHERE farmers.ward = ? ORDER BY plots.plot_id LIMIT 1
            """, (ward,)
        ).fetchone()
        if plot:
            try:
                reading = normalize_land(
                    ward, plot["kijanibox_sensor_id"], plot["latitude"], plot["longitude"],
                    fetch_land(plot["latitude"], plot["longitude"]),
                )
                insert_json(db, "telemetry_cache", reading)
                live_output = {"ward": ward, "readings": [reading], "source": "KijaniSpace",
                               "freshness": "live"}
            except KijaniSpaceError as exc:
                live_error = str(exc)
                live_output = None
        else:
            live_output = None
        if live_output:
            output = live_output
        else:
            rows = [dict(row) for row in db.execute(
                "SELECT * FROM telemetry_cache WHERE ward = ? ORDER BY timestamp DESC", (ward,)
            )]
            output = {"ward": ward, "readings": rows, "source": "telemetry_cache",
                      "freshness": "cached", "live_error": live_error}
    _audit(run_id, "fetch_kijanibox_telemetry", {"ward": ward}, output)
    return output


def fetch_open_meteo_context(ward: str, run_id: str) -> dict[str, Any]:
    with connect() as db:
        row = db.execute(
            "SELECT precipitation_7d_mm, rainfall_anomaly_mm FROM telemetry_cache WHERE ward = ?",
            (ward,),
        ).fetchone()
    output = {"ward": ward, "precipitation_7d_mm": row[0] if row else 0, "source": "Open-Meteo fixture"}
    _audit(run_id, "fetch_open_meteo_context", {"ward": ward}, output)
    return output


def fetch_kalro_guidelines(crop: str, growth_stage: str, run_id: str) -> dict[str, Any]:
    rule = "KALRO-HB-2026-03" if "water" in crop.lower() else (
        "KALRO-HB-2026-02" if "Flowering" in growth_stage else "KALRO-HB-2026-01"
    )
    output = {"crop": crop, "growth_stage": growth_stage, "rule_id": rule,
              "bulletin_id": "KMD-2026-10-14"}
    _audit(run_id, "fetch_kalro_guidelines", {"crop": crop, "growth_stage": growth_stage}, output)
    return output


def stage_advisory_for_wao_approval(
    run_id: str, ward: str, anomaly_type: str, target_growth_stage: str,
    plot_ids: list[str], sms_swahili: str, sms_english: str,
    voucher_code: str, voucher_total_kes: float, citations: dict[str, Any],
) -> dict[str, Any]:
    if not plot_ids or not citations.get("sensor_ids") or not citations.get("plot_ids"):
        raise ValueError("Advisory must include plot_ids and sensor_ids before staging")
    advisory_id = f"ADV-{uuid.uuid4().hex[:10].upper()}"
    per_farmer = voucher_total_kes / len(plot_ids)
    with connect() as db:
        insert_json(db, "staged_advisories", {
            "advisory_id": advisory_id, "run_id": run_id, "ward": ward,
            "anomaly_type": anomaly_type, "target_growth_stage": target_growth_stage,
            "affected_plot_ids_json": plot_ids, "affected_household_count": len(plot_ids),
            "draft_sms_swahili": sms_swahili, "draft_sms_english": sms_english,
            "ussd_menu_payload": "*384*55#", "evoucher_package_code": voucher_code,
            "evoucher_total_kes": voucher_total_kes, "per_farmer_kes": per_farmer,
            "citations_json": citations, "status": "PENDING_WAO_APPROVAL",
        })
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
        "gate_message": "Waiting for named Ward Agricultural Officer sign-off",
    }
    _audit(run_id, "stage_advisory_for_wao_approval", {"ward": ward}, output)
    sync_advisory_state(output)
    return output
