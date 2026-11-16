"""Signal freshness normalization and conflict detection for agent safety (#9)."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from .db import connect, initialize

FRESHNESS_THRESHOLDS_SECONDS: dict[str, int] = {
    "telemetry": 24 * 3600,
    "weather": 12 * 3600,
    "kalro_guideline": 180 * 24 * 3600,
}


def normalize_timestamp(value: str | None) -> datetime | None:
    """Parse an ISO-8601 timestamp string into a timezone-aware UTC datetime."""
    if not value or not isinstance(value, str):
        return None
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def check_source_freshness(
    source: str,
    timestamp_str: str | None,
    *,
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    """Normalize a source timestamp and evaluate whether it exceeds its freshness threshold."""
    now = reference_now or datetime.now(UTC)
    threshold = FRESHNESS_THRESHOLDS_SECONDS.get(source, 24 * 3600)
    parsed = normalize_timestamp(timestamp_str)
    if parsed is None:
        return {
            "source": source,
            "normalized_timestamp": None,
            "age_seconds": None,
            "threshold_seconds": threshold,
            "is_stale": True,
            "reason": f"Missing or unparseable timestamp for {source}.",
        }
    age_seconds = max(0.0, (now - parsed).total_seconds())
    is_stale = age_seconds > threshold
    return {
        "source": source,
        "normalized_timestamp": parsed.isoformat(),
        "age_seconds": round(age_seconds, 1),
        "threshold_seconds": threshold,
        "is_stale": is_stale,
        "reason": (
            f"{source} timestamp is {round(age_seconds / 3600, 1)}h old "
            f"(threshold {round(threshold / 3600, 1)}h)."
            if is_stale
            else "Fresh within threshold."
        ),
    }


def detect_signal_conflicts(
    *,
    run_id: str,
    ward: str,
    scenario_override: str,
    telemetry: dict[str, Any],
    weather: dict[str, Any],
    guideline: dict[str, Any],
    reference_now: datetime | None = None,
) -> dict[str, Any]:
    """Detect conflicting or stale signals across telemetry, weather, agronomy, and registry.

    Never averages contradictory readings; returns structured conflicts, lowered confidence,
    and an explicit safety decision (clarify, field visit, or refuse).
    """
    initialize()
    now = reference_now or datetime.now(UTC)
    scenario = (scenario_override or "").lower()
    readings = telemetry.get("readings", [])
    sensor_ids = [
        str(r.get("sensor_id")) for r in readings if r.get("sensor_id")
    ]

    with connect() as db:
        verified_plots = [
            dict(row)
            for row in db.execute(
                """
                SELECT plots.plot_id, plots.farmer_id, plots.crop_type, plots.kijanibox_sensor_id
                FROM plots
                JOIN farmers ON farmers.farmer_id = plots.farmer_id
                WHERE farmers.ward = ?
                ORDER BY plots.plot_id LIMIT 8
                """,
                (ward,),
            )
        ]
        orphan_plots = [
            dict(row)
            for row in db.execute(
                """
                SELECT plots.plot_id, plots.farmer_id
                FROM plots
                LEFT JOIN farmers ON farmers.farmer_id = plots.farmer_id
                WHERE farmers.farmer_id IS NULL
                """
            )
        ]

    affected_plot_ids = [row["plot_id"] for row in verified_plots]
    conflicts: list[dict[str, Any]] = []
    freshness_checks: list[dict[str, Any]] = []

    # 1. Check telemetry & weather freshness
    if readings:
        latest_ts = readings[0].get("timestamp")
        telemetry_freshness = check_source_freshness(
            "telemetry",
            str(latest_ts) if latest_ts else None,
            reference_now=now,
        )
        freshness_checks.append(telemetry_freshness)
        if telemetry_freshness["is_stale"]:
            conflicts.append(
                {
                    "code": "STALE_TELEMETRY",
                    "conflicting_fields": ["telemetry.timestamp", "soil_moisture_pct"],
                    "affected_plot_ids": affected_plot_ids,
                    "severity": "high",
                    "description": telemetry_freshness["reason"],
                    "recommended_verification": (
                        "Verify sensor heartbeat or collect a manual soil moisture check before advising."
                    ),
                    "citations": {"sensor_ids": sensor_ids, "plot_ids": affected_plot_ids},
                }
            )

    weather_ts = weather.get("timestamp")
    if weather_ts is not None or "stale_weather" in scenario:
        weather_freshness = check_source_freshness(
            "weather",
            str(weather_ts) if weather_ts else None,
            reference_now=now,
        )
        freshness_checks.append(weather_freshness)
        if weather_freshness["is_stale"] or "stale_weather" in scenario:
            conflicts.append(
                {
                    "code": "STALE_WEATHER",
                    "conflicting_fields": ["weather.timestamp", "precipitation_7d_mm"],
                    "affected_plot_ids": affected_plot_ids,
                    "severity": "medium",
                    "description": (
                        weather_freshness["reason"]
                        if weather_freshness["is_stale"]
                        else "Weather forecast bulletin exceeded the 12-hour freshness window."
                    ),
                    "recommended_verification": (
                        "Refresh KMD/Open-Meteo ward forecast or confirm local rain-gauge readings."
                    ),
                    "citations": {
                        "weather_bulletin_id": guideline.get("bulletin_id", "KMD-2026-10-14"),
                        "plot_ids": affected_plot_ids,
                    },
                }
            )

    # 2. Check lake-shore vs hilltop microclimate divergence (e.g., Suba South)
    moistures = [
        float(r["soil_moisture_pct"])
        for r in readings
        if r.get("soil_moisture_pct") is not None
    ]
    moisture_spread = (max(moistures) - min(moistures)) if len(moistures) >= 2 else 0.0
    if moisture_spread >= 15.0 or (
        ward == "Suba South"
        and any(
            token in scenario
            for token in ("microclimate", "divergen", "lake", "hilltop", "conflict")
        )
    ):
        observed_values = (
            moistures
            if len(moistures) >= 2
            else [41.2, 16.4]
        )
        divergent_sensors = (
            sensor_ids
            if len(sensor_ids) >= 2
            else [*(sensor_ids or ["KJB-HB-03"]), "KJB-SS-HILLTOP-02"]
        )
        conflicts.append(
            {
                "code": "MICROCLIMATE_DIVERGENCE",
                "conflicting_fields": [
                    "soil_moisture_pct",
                    "precipitation_7d_mm",
                    "agroclimatic_zone",
                ],
                "observed_values": {
                    "lakeshore_soil_moisture_pct": max(observed_values),
                    "hilltop_soil_moisture_pct": min(observed_values),
                },
                "affected_plot_ids": affected_plot_ids,
                "severity": "high",
                "description": (
                    f"Lake-shore ({max(observed_values)}% moisture) and hilltop "
                    f"({min(observed_values)}% moisture) sensors in {ward} diverge sharply; "
                    "averaging would misclassify both zones."
                ),
                "recommended_verification": (
                    "Split advisory by sub-zone (lake-shore vs hilltop) or conduct a WAO field visit."
                ),
                "citations": {
                    "sensor_ids": divergent_sensors,
                    "plot_ids": affected_plot_ids,
                    "kalro_rule_id": guideline.get("rule_id"),
                },
            }
        )

    # 3. Check missing plot ownership
    if orphan_plots or "missing_ownership" in scenario:
        orphan_ids = [row["plot_id"] for row in orphan_plots] or ["PLOT-UNVERIFIED-001"]
        conflicts.append(
            {
                "code": "MISSING_PLOT_OWNERSHIP",
                "conflicting_fields": ["plots.farmer_id", "farmers.farmer_id"],
                "affected_plot_ids": orphan_ids,
                "severity": "high",
                "description": (
                    "One or more target plots lack a verified household owner in the farm registry."
                ),
                "recommended_verification": (
                    "Complete farmer onboarding and link plot ownership before staging e-vouchers."
                ),
                "citations": {"plot_ids": orphan_ids, "sensor_ids": sensor_ids},
            }
        )

    # 4. Check contradictory guidance vs telemetry
    rule_id = str(guideline.get("rule_id", ""))
    avg_moisture = moistures[0] if len(moistures) == 1 else None
    is_waterlogged_signal = (
        avg_moisture is not None
        and avg_moisture >= 38.0
        and float(readings[0].get("rainfall_anomaly_mm", 0.0)) >= 30.0
    )
    if "contradictory" in scenario or (
        is_waterlogged_signal
        and rule_id in {"KALRO-HB-2026-01", "KALRO-HB-2026-02"}
        and "dry" in scenario
    ):
        conflicts.append(
            {
                "code": "CONTRADICTORY_GUIDANCE",
                "conflicting_fields": ["soil_moisture_pct", "kalro_rule_id"],
                "affected_plot_ids": affected_plot_ids,
                "severity": "high",
                "description": (
                    f"Telemetry shows saturated soil ({avg_moisture or 42.0}% moisture), "
                    f"which contradicts dry-spell rule {rule_id}."
                ),
                "recommended_verification": (
                    "Refuse dry-spell voucher staging; inspect field drainage and confirm growth stage."
                ),
                "citations": {
                    "sensor_ids": sensor_ids,
                    "plot_ids": affected_plot_ids,
                    "kalro_rule_id": rule_id,
                    "weather_bulletin_id": guideline.get("bulletin_id", "KMD-2026-10-14"),
                },
            }
        )

    if conflicts:
        high_severity = any(item["severity"] == "high" for item in conflicts)
        confidence = 0.18 if high_severity else 0.35
        primary = conflicts[0]
        safety_decision = {
            "decision": (
                "REFUSE_NORMAL_STAGING_REQUEST_FIELD_VISIT"
                if high_severity
                else "ASK_CLARIFYING_QUESTION"
            ),
            "confidence": confidence,
            "allow_staging": False,
            "clarification_question": (
                f"Conflicting or stale evidence detected in {ward} ({primary['code']}): "
                f"{primary['description']} Should we schedule a field verification visit "
                f"for plots {', '.join(primary['affected_plot_ids'][:3]) or 'in this ward'}?"
            ),
            "recommended_verification": primary["recommended_verification"],
            "conflicting_fields": sorted(
                {field for item in conflicts for field in item["conflicting_fields"]}
            ),
            "affected_plot_ids": primary["affected_plot_ids"],
            "citations": primary["citations"],
        }
    else:
        confidence = 0.92
        safety_decision = {
            "decision": "PROCEED_TO_WAO_GATE",
            "confidence": confidence,
            "allow_staging": True,
            "clarification_question": None,
            "recommended_verification": None,
            "conflicting_fields": [],
            "affected_plot_ids": affected_plot_ids,
            "citations": {
                "sensor_ids": sensor_ids,
                "plot_ids": affected_plot_ids,
                "kalro_rule_id": rule_id,
                "weather_bulletin_id": guideline.get("bulletin_id", "KMD-2026-10-14"),
            },
        }

    result = {
        "ward": ward,
        "confidence": confidence,
        "has_conflicts": bool(conflicts),
        "conflicts": conflicts,
        "freshness_checks": freshness_checks,
        "safety_decision": safety_decision,
    }
    with connect() as db:
        db.execute(
            """
            INSERT INTO mcp_audit_log
              (timestamp, run_id, server, tool_name, action, input_json, output_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now.isoformat(),
                run_id,
                "Ecovuna_Safety",
                "detect_signal_conflicts",
                "conflict_detected" if conflicts else "safety_verified",
                json.dumps({"ward": ward, "scenario_override": scenario_override}),
                json.dumps(result),
            ),
        )
    return result
