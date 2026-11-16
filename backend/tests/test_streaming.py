"""Tests for SSE streaming agent conversation runtime, reconnection, and audit parity (#15)."""

from __future__ import annotations

import json

from fastapi.testclient import TestClient

from backend.db import connect
from backend.ingest import ingest
from backend.main import app
from backend.streaming import sanitize_stream_payload


def setup_module() -> None:
    ingest(offline_fallback=True)


def _parse_sse(raw_text: str) -> list[dict[str, object]]:
    frames: list[dict[str, object]] = []
    for block in raw_text.strip().split("\n\n"):
        if not block.strip():
            continue
        lines = block.strip().splitlines()
        data_line = next((line for line in lines if line.startswith("data: ")), None)
        if data_line:
            frames.append(json.loads(data_line.removeprefix("data: ")))
    return frames


def test_sse_stream_emits_versioned_progress_events_and_matches_audit_record() -> None:
    client = TestClient(app)
    chat_resp = client.post(
        "/api/agent/chat",
        json={
            "message": "Check germination maize in Homa Bay Central",
            "ward": "Homa Bay Central",
            "session_id": "SES-STREAM-15",
        },
    )
    assert chat_resp.status_code == 200
    run_id = chat_resp.json()["run"]["run_id"]

    # Stream by session_id
    stream_resp = client.get("/api/agent/stream/SES-STREAM-15")
    assert stream_resp.status_code == 200
    assert stream_resp.headers["content-type"].startswith("text/event-stream")
    events = _parse_sse(stream_resp.text)
    event_types = [e["event"] for e in events]

    assert event_types[0] == "plan"
    assert "tool-start" in event_types
    assert "tool-result" in event_types
    assert "evidence" in event_types
    assert "uncertainty" in event_types
    assert "artifact" in event_types
    assert "approval-required" in event_types
    assert "heartbeat" in event_types
    assert event_types[-1] == "completion"

    # Verify tool and approval events match the audit record
    with connect() as db:
        audit_tools = {
            row["tool_name"]
            for row in db.execute(
                "SELECT tool_name FROM mcp_audit_log WHERE run_id = ?",
                (run_id,),
            )
        }
    streamed_tools = {
        e["data"]["tool"]  # type: ignore[index]
        for e in events
        if e["event"] == "tool-result"
    }
    assert audit_tools.issubset(streamed_tools)


def test_reconnecting_client_recovers_without_duplicating_events_and_get_state_works() -> None:
    client = TestClient(app)
    triage_resp = client.post(
        "/api/agent/triage",
        json={"ward": "Homa Bay Central"},
    )
    run_id = triage_resp.json()["run_id"]

    full_events = _parse_sse(client.get(f"/api/agent/stream/{run_id}").text)
    assert len(full_events) > 5
    fifth_id = str(full_events[4]["id"])

    # Reconnect with Last-Event-ID -> only events strictly after sequence 5 are returned
    resumed_resp = client.get(
        f"/api/agent/stream/{run_id}",
        headers={"Last-Event-ID": fifth_id},
    )
    resumed_events = _parse_sse(resumed_resp.text)
    assert len(resumed_events) == len(full_events) - 5
    assert int(resumed_events[0]["sequence"]) == 6  # type: ignore[arg-type]

    # Normal GET endpoint recovers final state
    snapshot_resp = client.get(f"/api/agent/runs/{run_id}")
    assert snapshot_resp.status_code == 200
    assert snapshot_resp.json()["state"]["run_id"] == run_id
    assert snapshot_resp.json()["state"]["status"] == "PAUSED_AT_WAO_GATE"


def test_stream_sanitizer_strips_secrets_and_chain_of_thought() -> None:
    dirty = {
        "api_key": "sk-secret-123",
        "chain_of_thought": "internal reasoning",
        "nested": {"authorization_header": "Bearer token", "safe_field": "ok"},
    }
    cleaned = sanitize_stream_payload(dirty)
    assert cleaned["api_key"] == "[REDACTED]"
    assert cleaned["chain_of_thought"] == "[REDACTED]"
    assert cleaned["nested"]["authorization_header"] == "[REDACTED]"
    assert cleaned["nested"]["safe_field"] == "ok"
