"""Evidence-first, context-aware conversation session management (#5)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .agent import triage
from .db import connect, initialize
from .errors import NotFoundError


def _load_or_create_session(
    *,
    session_id: str | None,
    ward: str | None,
    crop: str | None,
    season: str | None,
) -> dict[str, Any]:
    initialize()
    clean_session_id = (
        session_id.strip()
        if session_id and session_id.strip()
        else f"SES-{uuid.uuid4().hex[:10].upper()}"
    )
    now = datetime.now(UTC).isoformat()
    with connect() as db:
        row = db.execute(
            "SELECT * FROM conversation_sessions WHERE session_id = ?",
            (clean_session_id,),
        ).fetchone()
        if row:
            existing = dict(row)
            resolved_ward = (
                ward.strip()
                if ward and ward.strip()
                else existing["ward"]
            )
            resolved_crop = (
                crop.strip()
                if crop and crop.strip()
                else existing["crop"]
            )
            resolved_season = (
                season.strip()
                if season and season.strip()
                else existing["season"]
            )
            return {
                "session_id": clean_session_id,
                "ward": resolved_ward,
                "crop": resolved_crop,
                "season": resolved_season,
                "telemetry_freshness": existing["telemetry_freshness"],
                "prior_run_ids": json.loads(existing["prior_run_ids_json"]),
                "unresolved_questions": json.loads(
                    existing["unresolved_questions_json"]
                ),
                "created_at": existing["created_at"],
                "updated_at": now,
            }

        resolved_ward = (
            ward.strip()
            if ward and ward.strip()
            else "Homa Bay Central"
        )
        resolved_crop = crop.strip() if crop and crop.strip() else "Maize WH-505"
        resolved_season = (
            season.strip() if season and season.strip() else "2026_SHORT_RAINS"
        )
        context = {
            "session_id": clean_session_id,
            "ward": resolved_ward,
            "crop": resolved_crop,
            "season": resolved_season,
            "telemetry_freshness": "cached",
            "prior_run_ids": [],
            "unresolved_questions": [],
            "created_at": now,
            "updated_at": now,
        }
        db.execute(
            """
            INSERT INTO conversation_sessions
              (session_id, ward, crop, season, telemetry_freshness,
               prior_run_ids_json, unresolved_questions_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                clean_session_id,
                resolved_ward,
                resolved_crop,
                resolved_season,
                "cached",
                "[]",
                "[]",
                now,
                now,
            ),
        )
        return context


def _save_session_and_turns(
    context: dict[str, Any],
    *,
    user_message: str,
    agent_message: str,
    run_id: str,
    sections: dict[str, Any],
) -> None:
    now = datetime.now(UTC).isoformat()
    with connect() as db:
        db.execute(
            """
            UPDATE conversation_sessions
            SET ward = ?, crop = ?, season = ?, telemetry_freshness = ?,
                prior_run_ids_json = ?, unresolved_questions_json = ?, updated_at = ?
            WHERE session_id = ?
            """,
            (
                context["ward"],
                context["crop"],
                context["season"],
                context["telemetry_freshness"],
                json.dumps(context["prior_run_ids"]),
                json.dumps(context["unresolved_questions"]),
                now,
                context["session_id"],
            ),
        )
        db.execute(
            """
            INSERT INTO conversation_turns
              (turn_id, session_id, role, message, run_id, sections_json, citations_json, created_at)
            VALUES (?, ?, 'user', ?, ?, '{}', '{}', ?)
            """,
            (
                f"TRN-{uuid.uuid4().hex[:10].upper()}",
                context["session_id"],
                user_message,
                run_id,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO conversation_turns
              (turn_id, session_id, role, message, run_id, sections_json, citations_json, created_at)
            VALUES (?, ?, 'agent', ?, ?, ?, ?, ?)
            """,
            (
                f"TRN-{uuid.uuid4().hex[:10].upper()}",
                context["session_id"],
                agent_message,
                run_id,
                json.dumps(sections),
                json.dumps(sections.get("citations", {})),
                now,
            ),
        )


def _derive_scenario(message: str) -> str:
    normalized = message.lower()
    if any(
        token in normalized
        for token in (
            "microclimate",
            "divergen",
            "lake-shore",
            "hilltop",
            "stale_weather",
            "missing_ownership",
            "contradictory",
            "conflict",
            "stale",
        )
    ):
        return normalized
    if "flood" in normalized or "water" in normalized:
        return "flash flood waterlogging"
    if "flower" in normalized:
        return "flowering maize dry spell"
    return "sudden dry spell"


def build_conversation_sections(
    *,
    context: dict[str, Any],
    run: dict[str, Any],
) -> dict[str, Any]:
    """Build structured observed_facts, interpretation, uncertainty, recommendation, approval_state, and citations."""
    readings = (run.get("telemetry") or {}).get("readings", [])
    advisory = run.get("advisory")
    safety = run.get("safety_decision") or {}
    conflicts = run.get("conflicts") or []
    freshness = (run.get("telemetry") or {}).get("freshness", "missing")

    observed_facts: list[str] = [
        f"Active ward context: {context['ward']} ({context['crop']}, season {context['season']})."
    ]
    if context["prior_run_ids"]:
        observed_facts.append(
            f"Prior session runs: {', '.join(context['prior_run_ids'])}."
        )
    if readings:
        latest = readings[0]
        observed_facts.append(
            f"Sensor {latest.get('sensor_id')} reported {latest.get('soil_moisture_pct')}% "
            f"soil moisture and {latest.get('precipitation_7d_mm')} mm 7-day precipitation "
            f"(freshness: {freshness})."
        )
    else:
        observed_facts.append(
            f"No verified sensor readings were found for {context['ward']}."
        )

    citations: dict[str, Any] = {}
    if isinstance(advisory, dict) and advisory.get("citations"):
        citations = dict(advisory["citations"])
    elif safety.get("citations"):
        citations = dict(safety["citations"])
    else:
        citations = {
            "sensor_ids": [r.get("sensor_id") for r in readings if r.get("sensor_id")],
            "plot_ids": [],
            "kalro_rule_id": (run.get("guideline") or {}).get("rule_id"),
            "weather_bulletin_id": (run.get("guideline") or {}).get(
                "bulletin_id", "KMD-2026-10-14"
            ),
        }

    if conflicts or run.get("status") in {
        "PAUSED_FOR_CONFLICT_VERIFICATION",
        "SAFE_TERMINAL_VERIFICATION_REQUIRED",
    }:
        clarification = (
            safety.get("clarification_question")
            or f"Evidence for {context['ward']} is missing or stale. Please confirm plot ownership and sensor status before staging an advisory."
        )
        verification = (
            safety.get("recommended_verification")
            or "Collect a verified field reading or select a ward with active KijaniBox telemetry."
        )
        interpretation = (
            f"Grounded checks halted staging for {context['ward']} because required evidence is missing, stale, or conflicting."
        )
        uncertainty = (
            f"Confidence is low ({run.get('confidence', 0.15):.2f}); {clarification}"
        )
        recommendation = f"Verification required before advising: {verification}"
        approval_state = run.get("status", "SAFE_TERMINAL_VERIFICATION_REQUIRED")
    else:
        rule_id = citations.get("kalro_rule_id", "KALRO-HB-2026-01")
        anomaly = (advisory or {}).get("anomaly_type", "SUDDEN_DRY_SPELL")
        stage = (advisory or {}).get("target_growth_stage", "Germination_0_14d")
        sms_en = (advisory or {}).get("draft_sms_english", "")
        voucher = (advisory or {}).get("evoucher_package_code", "")
        interpretation = (
            f"Telemetry and agronomic rule {rule_id} indicate {anomaly} affecting {stage} plots in {context['ward']}."
        )
        uncertainty = (
            f"Telemetry source is '{freshness}' (confidence {run.get('confidence', 0.92):.2f}); "
            "human officer verification is required before dispatch."
        )
        recommendation = (
            f"{sms_en} Stage package {voucher} for plots {', '.join(citations.get('plot_ids', [])[:4])} "
            f"(citations: {', '.join(citations.get('sensor_ids', []))}, {rule_id})."
        )
        approval_state = (advisory or {}).get("status", run.get("status", "PAUSED_AT_WAO_GATE"))

    return {
        "observed_facts": observed_facts,
        "interpretation": interpretation,
        "uncertainty": uncertainty,
        "recommendation": recommendation,
        "approval_state": approval_state,
        "citations": citations,
    }


def run_conversation_turn(
    *,
    message: str,
    ward: str | None = None,
    session_id: str | None = None,
    crop: str | None = None,
    season: str | None = None,
) -> dict[str, Any]:
    """Execute one context-aware conversation turn backed by the state graph."""
    context = _load_or_create_session(
        session_id=session_id,
        ward=ward,
        crop=crop,
        season=season,
    )
    scenario = _derive_scenario(message)
    if "flower" in message.lower():
        context["crop"] = "Maize WH-505 (Flowering)"

    run = triage(context["ward"], scenario)
    freshness = (run.get("telemetry") or {}).get("freshness", "missing")
    if not (run.get("telemetry") or {}).get("readings"):
        freshness = "missing"
    elif any(
        c.get("code") in {"STALE_TELEMETRY", "STALE_WEATHER"}
        for c in (run.get("conflicts") or [])
    ):
        freshness = "stale"
    context["telemetry_freshness"] = freshness

    sections = build_conversation_sections(context=context, run=run)
    safety = run.get("safety_decision") or {}
    if run.get("conflicts") or run.get("status") in {
        "PAUSED_FOR_CONFLICT_VERIFICATION",
        "SAFE_TERMINAL_VERIFICATION_REQUIRED",
    }:
        clarification = (
            safety.get("clarification_question")
            or f"Evidence for {context['ward']} is missing or stale. Which verified plot or sensor should we inspect before staging an advisory?"
        )
        if clarification not in context["unresolved_questions"]:
            context["unresolved_questions"].append(clarification)
        agent_message = clarification
    else:
        context["unresolved_questions"] = []
        agent_message = (
            f"I found grounded evidence for {context['ward']} and prepared an advisory "
            f"({sections['citations'].get('kalro_rule_id')}) for your review."
        )

    if run["run_id"] not in context["prior_run_ids"]:
        context["prior_run_ids"].append(run["run_id"])

    _save_session_and_turns(
        context,
        user_message=message,
        agent_message=agent_message,
        run_id=run["run_id"],
        sections=sections,
    )
    return {
        "session_id": context["session_id"],
        "message": agent_message,
        "question": message,
        "context": {
            "session_id": context["session_id"],
            "ward": context["ward"],
            "crop": context["crop"],
            "season": context["season"],
            "telemetry_freshness": context["telemetry_freshness"],
            "prior_run_ids": list(context["prior_run_ids"]),
            "unresolved_questions": list(context["unresolved_questions"]),
        },
        "sections": sections,
        "run": run,
    }


def get_conversation_session(session_id: str) -> dict[str, Any]:
    """Load a persisted conversation session and its turn history."""
    initialize()
    with connect() as db:
        session_row = db.execute(
            "SELECT * FROM conversation_sessions WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        if not session_row:
            raise NotFoundError(
                f"Conversation session '{session_id}' was not found.",
                error_code="SESSION_NOT_FOUND",
            )
        turns_rows = [
            dict(row)
            for row in db.execute(
                "SELECT * FROM conversation_turns WHERE session_id = ? ORDER BY created_at, rowid",
                (session_id,),
            )
        ]
    turns = []
    for item in turns_rows:
        item["sections"] = json.loads(item.pop("sections_json") or "{}")
        item["citations"] = json.loads(item.pop("citations_json") or "{}")
        turns.append(item)
    return {
        "session_id": session_row["session_id"],
        "ward": session_row["ward"],
        "crop": session_row["crop"],
        "season": session_row["season"],
        "telemetry_freshness": session_row["telemetry_freshness"],
        "prior_run_ids": json.loads(session_row["prior_run_ids_json"]),
        "unresolved_questions": json.loads(session_row["unresolved_questions_json"]),
        "turns": turns,
    }
