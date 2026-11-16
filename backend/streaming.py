"""Server-Sent Events (SSE) streaming runtime with reconnection and secret redaction (#15)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

from .artifacts_repository import repository as artifact_repo
from .db import connect
from .errors import NotFoundError
from .state_graph import load_run_state

STREAM_SCHEMA_VERSION = "1.0"
VERSIONED_EVENT_TYPES = (
    "plan",
    "tool-start",
    "tool-result",
    "evidence",
    "uncertainty",
    "artifact",
    "approval-required",
    "error",
    "completion",
    "heartbeat",
)

_SENSITIVE_KEYS = {
    "api_key",
    "secret",
    "password",
    "authorization",
    "bearer",
    "private_key",
    "chain_of_thought",
    "raw_reasoning",
}


def sanitize_stream_payload(value: Any) -> Any:
    """Recursively strip secrets, raw credentials, or unsupported chain-of-thought from streamed payloads."""
    if isinstance(value, dict):
        cleaned: dict[str, Any] = {}
        for k, v in value.items():
            key_lower = str(k).lower()
            if any(token in key_lower for token in _SENSITIVE_KEYS):
                cleaned[k] = "[REDACTED]"
            else:
                cleaned[k] = sanitize_stream_payload(v)
        return cleaned
    if isinstance(value, list):
        return [sanitize_stream_payload(item) for item in value]
    return value


def resolve_run_state(run_or_session_id: str) -> tuple[str, str | None, dict[str, Any]]:
    """Resolve either a run_id or session_id to (run_id, session_id, state)."""
    direct_state = load_run_state(run_or_session_id)
    if direct_state is not None:
        return run_or_session_id, None, direct_state

    with connect() as db:
        session_row = db.execute(
            "SELECT session_id, prior_run_ids_json FROM conversation_sessions WHERE session_id = ?",
            (run_or_session_id,),
        ).fetchone()
    if session_row:
        prior_runs = json.loads(session_row["prior_run_ids_json"] or "[]")
        if prior_runs:
            latest_run_id = prior_runs[-1]
            state = load_run_state(latest_run_id)
            if state is not None:
                return latest_run_id, session_row["session_id"], state

    raise NotFoundError(
        f"Run or session '{run_or_session_id}' was not found.",
        error_code="STREAM_TARGET_NOT_FOUND",
    )


def build_stream_events(run_or_session_id: str) -> list[dict[str, Any]]:
    """Construct the ordered, deterministic sequence of versioned progress events for a run/session."""
    run_id, session_id, state = resolve_run_state(run_or_session_id)
    now = datetime.now(UTC).isoformat()
    events: list[dict[str, Any]] = []
    seq = 0

    def _append(event_type: str, data: dict[str, Any]) -> None:
        nonlocal seq
        seq += 1
        events.append(
            {
                "id": f"{run_id}:{seq}",
                "sequence": seq,
                "version": STREAM_SCHEMA_VERSION,
                "event": event_type,
                "run_id": run_id,
                "session_id": session_id,
                "timestamp": now,
                "data": sanitize_stream_payload(data),
            }
        )

    # 1. Plan event
    plan = state.get("plan") or {}
    if plan:
        _append("plan", {"plan": plan})

    # 2. Tool-start and tool-result events matching execution trace and audit record
    for entry in state.get("execution_trace") or []:
        node = str(entry.get("node") or "unknown")
        tool = str(entry.get("tool") or "unknown")
        server = str(entry.get("server") or "Ecovuna_Telemetry")
        output = entry.get("output") or {}
        _append(
            "tool-start",
            {"node": node, "server": server, "tool": tool},
        )
        _append(
            "tool-result",
            {
                "node": node,
                "server": server,
                "tool": tool,
                "latency_ms": entry.get("latency_ms", 1),
                "transition": entry.get("transition"),
                "output": output,
            },
        )

    # 3. Evidence event
    evidence = state.get("evidence") or {}
    if evidence:
        _append(
            "evidence",
            {
                "freshness": evidence.get("freshness", "cached"),
                "citations": evidence.get("citations") or {},
                "research_sources": evidence.get("research_sources") or [],
            },
        )

    # 4. Uncertainty / conflict event
    conflicts = state.get("conflicts") or []
    safety = state.get("safety_decision") or {}
    _append(
        "uncertainty",
        {
            "confidence": state.get("confidence", 0.92),
            "conflicts": conflicts,
            "clarification_question": safety.get("clarification_question"),
            "recommended_verification": safety.get("recommended_verification"),
        },
    )

    # 5. Generated field artifacts
    artifacts = artifact_repo.list_artifacts(run_id=run_id, latest_only=True)
    for art in artifacts:
        _append(
            "artifact",
            {
                "artifact_id": art["artifact_id"],
                "artifact_type": art["artifact_type"],
                "version": art["version"],
                "title": art["title"],
                "approval_status": art["approval_status"],
                "dispatched": art["dispatched"],
            },
        )

    # 6. Approval-required or error event
    status = str(state.get("status") or "PAUSED_AT_WAO_GATE")
    if state.get("error") or status == "ERROR":
        _append(
            "error",
            {"status": status, "error": state.get("error") or "Run encountered an error."},
        )
    elif status in {
        "PAUSED_AT_WAO_GATE",
        "PAUSED_FOR_CONFLICT_VERIFICATION",
        "SAFE_TERMINAL_VERIFICATION_REQUIRED",
    }:
        advisory = state.get("advisory") or {}
        _append(
            "approval-required",
            {
                "status": status,
                "advisory_id": advisory.get("advisory_id"),
                "gate": (state.get("approval") or {}).get("gate", "WAO_HITL_GATE"),
                "gate_message": advisory.get(
                    "gate_message",
                    "Waiting for named Ward Agricultural Officer sign-off",
                ),
            },
        )

    # 7. Heartbeat & clean completion
    _append("heartbeat", {"status": "alive", "run_id": run_id})
    _append(
        "completion",
        {
            "run_id": run_id,
            "status": status,
            "total_events": seq + 1,
        },
    )
    return events


def parse_last_event_sequence(last_event_id: str | None) -> int:
    """Parse sequence number from Last-Event-ID ('RUN-XXXX:5' or '5') for duplicate-free reconnects."""
    if not last_event_id or not last_event_id.strip():
        return 0
    raw = last_event_id.strip()
    if ":" in raw:
        raw = raw.rsplit(":", 1)[-1]
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def format_sse_stream(
    run_or_session_id: str,
    *,
    last_event_id: str | None = None,
) -> Iterator[str]:
    """Yield SSE-formatted frames starting strictly after last_event_id."""
    events = build_stream_events(run_or_session_id)
    resume_after = parse_last_event_sequence(last_event_id)
    for item in events:
        if int(item["sequence"]) <= resume_after:
            continue
        payload = json.dumps(item, ensure_ascii=False)
        yield f"id: {item['id']}\nevent: {item['event']}\ndata: {payload}\n\n"
