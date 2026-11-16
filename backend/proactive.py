"""Proactive daily brief and follow-up queue for extension officers without autonomous external actions (#8)."""

from __future__ import annotations

from typing import Any

from .conversations import run_conversation_turn
from .db import connect, initialize
from .errors import NotFoundError

FIXTURE_REFERENCE_TIME = "2026-10-15T06:00:00+00:00"


def _compute_ward_rankings(
    *,
    ward_filter: str | None = None,
    focus: str | None = None,
) -> list[dict[str, Any]]:
    initialize()
    with connect() as db:
        ward_rows = db.execute(
            """
            SELECT farmers.ward AS ward,
                   COUNT(DISTINCT farmers.farmer_id) AS households,
                   COUNT(plots.plot_id) AS plots
            FROM farmers
            LEFT JOIN plots ON plots.farmer_id = farmers.farmer_id
            GROUP BY farmers.ward
            ORDER BY farmers.ward
            """
        ).fetchall()

        items: list[dict[str, Any]] = []
        for wrow in ward_rows:
            ward = str(wrow["ward"])
            if ward_filter and ward.lower() != ward_filter.strip().lower():
                continue

            readings = [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM telemetry_cache WHERE ward = ? ORDER BY timestamp DESC",
                    (ward,),
                )
            ]
            plots = [
                dict(p)
                for p in db.execute(
                    """
                    SELECT plots.plot_id, plots.farmer_id, plots.crop_type,
                           plots.current_growth_stage, plots.kijanibox_sensor_id,
                           farmers.full_name
                    FROM plots
                    JOIN farmers ON farmers.farmer_id = plots.farmer_id
                    WHERE farmers.ward = ?
                    ORDER BY plots.plot_id
                    """,
                    (ward,),
                )
            ]
            pending_advisories = [
                dict(a)
                for a in db.execute(
                    """
                    SELECT advisory_id, run_id, anomaly_type, status
                    FROM staged_advisories
                    WHERE ward = ? AND status = 'PENDING_WAO_APPROVAL'
                    ORDER BY rowid DESC
                    """,
                    (ward,),
                )
            ]
            field_visits = [
                dict(v)
                for v in db.execute(
                    """
                    SELECT run_id, status, updated_at
                    FROM agent_runs
                    WHERE ward = ? AND status IN ('REJECTED_FIELD_VISIT', 'PAUSED_FOR_CONFLICT_VERIFICATION')
                    ORDER BY updated_at DESC
                    """,
                    (ward,),
                )
            ]

            moisture_vals = [float(r["soil_moisture_pct"]) for r in readings]
            precip_vals = [float(r["precipitation_7d_mm"]) for r in readings]
            sensor_ids = [str(r["sensor_id"]) for r in readings]
            latest_ts = (
                str(readings[0]["timestamp"]) if readings else FIXTURE_REFERENCE_TIME
            )

            min_moisture = min(moisture_vals) if moisture_vals else 20.0
            max_moisture = max(moisture_vals) if moisture_vals else 20.0
            max_precip = max(precip_vals) if precip_vals else 0.0
            spread = round(max_moisture - min_moisture, 1)

            score = 0
            ranking_factors: list[dict[str, Any]] = []
            recommended_scenario = "sudden dry spell"
            rule_id = "KALRO-HB-2026-01"

            if spread >= 15.0:
                score += 45
                recommended_scenario = "microclimate divergence"
                ranking_factors.append(
                    {
                        "factor": "microclimate_sensor_divergence",
                        "weight": 45,
                        "detail": f"Sensor moisture spread is {spread}% ({min_moisture}% vs {max_moisture}%) across {ward}.",
                    }
                )
            if max_precip >= 80.0:
                score += 40
                recommended_scenario = "flash flood waterlogging"
                rule_id = "KALRO-HB-2026-03"
                ranking_factors.append(
                    {
                        "factor": "flash_flood_waterlogging_risk",
                        "weight": 40,
                        "detail": f"7-day precipitation reached {max_precip} mm in {ward}.",
                    }
                )
            if min_moisture <= 16.0:
                score += 35
                ranking_factors.append(
                    {
                        "factor": "severe_soil_moisture_deficit",
                        "weight": 35,
                        "detail": f"Lowest sensor soil moisture is {min_moisture}% (<16% threshold).",
                    }
                )
            if pending_advisories:
                weight = min(25, len(pending_advisories) * 10)
                score += weight
                ranking_factors.append(
                    {
                        "factor": "stale_unapproved_advisories",
                        "weight": weight,
                        "detail": f"{len(pending_advisories)} staged advisory(s) awaiting named WAO sign-off.",
                    }
                )
            if field_visits:
                weight = min(20, len(field_visits) * 10)
                score += weight
                ranking_factors.append(
                    {
                        "factor": "pending_field_visits",
                        "weight": weight,
                        "detail": f"{len(field_visits)} run(s) flagged for physical field verification.",
                    }
                )

            households_Weight = int(wrow["households"]) * 2
            score += households_Weight
            ranking_factors.append(
                {
                    "factor": "caseload_household_exposure",
                    "weight": households_Weight,
                    "detail": f"{wrow['households']} households and {wrow['plots']} plots registered in {ward}.",
                }
            )

            if focus:
                focus_lower = focus.lower()
                if (
                    ("flood" in focus_lower and max_precip >= 80.0)
                    or ("conflict" in focus_lower and spread >= 15.0)
                    or ("dry" in focus_lower and min_moisture <= 16.0)
                ):
                    score += 20

            plot_ids = [str(p["plot_id"]) for p in plots[:6]]
            household_Preview = [
                {
                    "farmer_id": p["farmer_id"],
                    "full_name": p["full_name"],
                    "plot_id": p["plot_id"],
                    "crop_type": p["crop_type"],
                    "growth_stage": p["current_growth_stage"],
                }
                for p in plots[:3]
            ]

            slug = ward.lower().replace(" ", "-")
            items.append(
                {
                    "item_id": f"BRIEF-{slug.upper()}",
                    "ward": ward,
                    "priority_score": score,
                    "recommended_scenario": recommended_scenario,
                    "summary": (
                        f"{ward}: score {score} — {ranking_factors[0]['detail']}"
                    ),
                    "freshness": {
                        "last_telemetry_timestamp": latest_ts,
                        "source": "telemetry_cache",
                        "status": "cached_verified",
                    },
                    "ranking_factors": ranking_factors,
                    "affected_households": household_Preview,
                    "stale_advisories_count": len(pending_advisories),
                    "field_visits_due_count": len(field_visits)
                    + (1 if spread >= 15.0 else 0),
                    "citations": {
                        "sensor_ids": sensor_ids,
                        "plot_ids": plot_ids,
                        "kalro_rule_id": rule_id,
                        "weather_bulletin_id": "KMD-2026-10-14",
                    },
                    "autonomous_actions_taken": False,
                    "requires_wao_approval": True,
                }
            )

    items.sort(key=lambda item: (-int(item["priority_score"]), str(item["ward"])))
    for rank_idx, item in enumerate(items, start=1):
        item["rank"] = rank_idx
    return items


def build_daily_brief(
    *,
    ward: str | None = None,
    question: str | None = None,
) -> dict[str, Any]:
    """Generate a deterministic, read-only daily brief and follow-up queue from fixture data."""
    ranked_items = _compute_ward_rankings(ward_filter=ward, focus=question)
    with connect() as db:
        audit_count_before = db.execute(
            "SELECT COUNT(*) FROM mcp_audit_log WHERE action IN ('human_approval', 'consequential_action')"
        ).fetchone()[0]

    refinement_note = (
        f"Refined daily brief for question: '{question.strip()}'."
        if question and question.strip()
        else "Standard morning extension brief across Homa Bay wards."
    )
    return {
        "brief_id": "BRIEF-DAILY-2026-10-15",
        "generated_at": FIXTURE_REFERENCE_TIME,
        "mode": "read_only_proactive_brief",
        "refinement_note": refinement_note,
        "autonomous_dispatch": False,
        "state_mutations_performed": 0,
        "consequential_audit_count": audit_count_before,
        "queue": ranked_items,
    }


def convert_brief_item_to_run(
    *,
    item_id: str,
    question: str | None = None,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Open a ranked brief item and continue it as an inspectable, approval-gated agent run."""
    all_items = _compute_ward_rankings()
    matched = next((item for item in all_items if item["item_id"] == item_id), None)
    if matched is None:
        raise NotFoundError(
            f"Daily brief item '{item_id}' was not found.",
            error_code="BRIEF_ITEM_NOT_FOUND",
        )

    ward = str(matched["ward"])
    prompt = (
        question.strip()
        if question and question.strip()
        else f"Investigate {matched['recommended_scenario']} in {ward} from daily brief {item_id}"
    )
    turn = run_conversation_turn(
        message=prompt,
        ward=ward,
        session_id=session_id,
    )
    return {
        "brief_item": matched,
        "session_id": turn["session_id"],
        "message": turn["message"],
        "context": turn["context"],
        "sections": turn["sections"],
        "run": turn["run"],
        "autonomous_dispatch": False,
    }
