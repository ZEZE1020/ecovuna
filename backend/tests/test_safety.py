"""Tests for uncertain, stale, and conflicting signal safety (#9)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from backend.agent import triage
from backend.db import connect, insert_json
from backend.ingest import ingest
from backend.main import app
from backend.safety import check_source_freshness, detect_signal_conflicts


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_source_freshness_normalization_and_thresholds() -> None:
    now = datetime(2026, 11, 16, 12, 0, 0, tzinfo=UTC)
    fresh_telemetry = check_source_freshness(
        "telemetry",
        (now - timedelta(hours=4)).isoformat(),
        reference_now=now,
    )
    assert fresh_telemetry["is_stale"] is False

    stale_telemetry = check_source_freshness(
        "telemetry",
        (now - timedelta(hours=30)).isoformat(),
        reference_now=now,
    )
    assert stale_telemetry["is_stale"] is True

    stale_weather = check_source_freshness(
        "weather",
        (now - timedelta(hours=14)).isoformat(),
        reference_now=now,
    )
    assert stale_weather["is_stale"] is True


def test_lakeshore_hilltop_microclimate_divergence_blocks_high_confidence_advisory() -> None:
    # Insert divergent lake-shore (41.8%) and hilltop (15.2%) readings in Suba South
    now_iso = datetime.now(UTC).isoformat()
    with connect() as db:
        insert_json(
            db,
            "telemetry_cache",
            {
                "ward": "Suba South",
                "sensor_id": "KJB-SS-LAKE-01",
                "timestamp": now_iso,
                "soil_moisture_pct": 41.8,
                "soil_temp_c": 24.5,
                "precipitation_7d_mm": 76.0,
                "rainfall_anomaly_mm": 34.0,
                "raw_payload_json": {"zone": "lakeshore", "source": "offline_fixture"},
            },
        )
        insert_json(
            db,
            "telemetry_cache",
            {
                "ward": "Suba South",
                "sensor_id": "KJB-SS-HILL-02",
                "timestamp": now_iso,
                "soil_moisture_pct": 15.2,
                "soil_temp_c": 28.9,
                "precipitation_7d_mm": 8.0,
                "rainfall_anomaly_mm": -36.0,
                "raw_payload_json": {"zone": "hilltop", "source": "offline_fixture"},
            },
        )

    state = triage("Suba South", "lake-shore vs hilltop microclimate")
    assert state["status"] == "PAUSED_FOR_CONFLICT_VERIFICATION"
    assert state.get("advisory") is None
    assert state["confidence"] < 0.5
    codes = [item["code"] for item in state["conflicts"]]
    assert "MICROCLIMATE_DIVERGENCE" in codes
    decision = state["safety_decision"]
    assert decision["allow_staging"] is False
    assert "KJB-SS-LAKE-01" in decision["citations"]["sensor_ids"]
    assert "KJB-SS-HILL-02" in decision["citations"]["sensor_ids"]
    assert decision["clarification_question"] is not None

    # Restore clean fixture state
    ingest(offline_fallback=True)


def test_stale_weather_and_contradictory_guidance_surface_in_chat_and_audit() -> None:
    client = TestClient(app)
    chat_resp = client.post(
        "/api/agent/chat",
        json={
            "ward": "Ndhiwa",
            "message": "Check contradictory dry spell advice against stale_weather in Ndhiwa",
        },
    )
    assert chat_resp.status_code == 200
    payload = chat_resp.json()
    run = payload["run"]
    assert run["status"] == "PAUSED_FOR_CONFLICT_VERIFICATION"
    assert run["advisory"] is None
    codes = {item["code"] for item in run["conflicts"]}
    assert "STALE_WEATHER" in codes
    assert "CONTRADICTORY_GUIDANCE" in codes
    assert "Conflicting or stale evidence detected" in payload["message"]

    with connect() as db:
        audit_row = db.execute(
            "SELECT * FROM mcp_audit_log WHERE run_id = ? AND server = 'Ecovuna_Safety'",
            (run["run_id"],),
        ).fetchone()
    assert audit_row is not None
    assert audit_row["action"] == "conflict_detected"


def test_missing_plot_ownership_prevents_staging() -> None:
    report = detect_signal_conflicts(
        run_id="RUN-OWNERSHIP-CHECK",
        ward="Homa Bay Central",
        scenario_override="missing_ownership",
        telemetry={
            "readings": [
                {
                    "sensor_id": "KJB-HB-01",
                    "timestamp": datetime.now(UTC).isoformat(),
                    "soil_moisture_pct": 18.0,
                }
            ]
        },
        weather={"precipitation_7d_mm": 12.0},
        guideline={"rule_id": "KALRO-HB-2026-01", "bulletin_id": "KMD-2026-10-14"},
    )
    assert report["has_conflicts"] is True
    assert any(c["code"] == "MISSING_PLOT_OWNERSHIP" for c in report["conflicts"])
    assert report["safety_decision"]["allow_staging"] is False
