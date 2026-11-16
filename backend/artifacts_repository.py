"""Unified repository interface for sessions, immutable tool events, and versioned field artifacts (#17)."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from .db import connect, initialize
from .errors import InvalidRequestError, NotFoundError, PolicyViolationError

ARTIFACT_TYPES = ("field_brief", "sms", "ussd", "visit_list")
SAFE_RESUME_CHECKPOINTS = {
    "PAUSED_AT_WAO_GATE",
    "PAUSED_FOR_CONFLICT_VERIFICATION",
    "SAFE_TERMINAL_VERIFICATION_REQUIRED",
}


class ArtifactSessionRepository:
    """Repository abstraction shared by local SQLite and Firestore-backed state."""

    def record_immutable_tool_events(
        self,
        *,
        run_id: str,
        execution_trace: list[dict[str, Any]],
        session_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Persist append-only tool events for a run without overwriting existing events."""
        initialize()
        now = datetime.now(UTC).isoformat()
        recorded: list[dict[str, Any]] = []
        with connect() as db:
            existing_count = db.execute(
                "SELECT COUNT(*) FROM run_tool_events WHERE run_id = ?",
                (run_id,),
            ).fetchone()[0]
            for idx, entry in enumerate(execution_trace[existing_count:], start=existing_count + 1):
                event_id = f"EVT-{run_id}-{idx:03d}"
                node = str(entry.get("node") or "unknown")
                server = str(entry.get("server") or "Ecovuna_Telemetry")
                tool_name = str(entry.get("tool") or "unknown_tool")
                output = entry.get("output") or {}
                db.execute(
                    """
                    INSERT OR IGNORE INTO run_tool_events
                      (event_id, run_id, session_id, sequence_no, node, server, tool_name, output_json, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        run_id,
                        session_id,
                        idx,
                        node,
                        server,
                        tool_name,
                        json.dumps(output),
                        now,
                    ),
                )
                recorded.append(
                    {
                        "event_id": event_id,
                        "run_id": run_id,
                        "session_id": session_id,
                        "sequence_no": idx,
                        "node": node,
                        "server": server,
                        "tool_name": tool_name,
                        "output": output,
                        "created_at": now,
                    }
                )
        return recorded

    def list_tool_events(self, run_id: str) -> list[dict[str, Any]]:
        initialize()
        with connect() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM run_tool_events WHERE run_id = ? ORDER BY sequence_no ASC",
                    (run_id,),
                )
            ]
        for row in rows:
            row["output"] = json.loads(row.pop("output_json") or "{}")
        return rows

    def generate_and_persist_artifacts(
        self,
        *,
        run: dict[str, Any],
        session_id: str | None = None,
        approved_by_wao: str | None = None,
    ) -> list[dict[str, Any]]:
        """Create a new immutable version of field_brief, sms, ussd, and visit_list artifacts."""
        initialize()
        run_id = str(run["run_id"])
        ward = str(run.get("ward") or "Homa Bay Central")
        advisory = run.get("advisory") or {}
        citations = (
            advisory.get("citations")
            or (run.get("evidence") or {}).get("citations")
            or {
                "sensor_ids": [
                    r.get("sensor_id")
                    for r in (run.get("telemetry") or {}).get("readings", [])
                    if r.get("sensor_id")
                ],
                "plot_ids": [],
                "kalro_rule_id": (run.get("guideline") or {}).get("rule_id"),
                "weather_bulletin_id": (run.get("guideline") or {}).get("bulletin_id"),
            }
        )
        approval_status = str(
            advisory.get("status") or run.get("status") or "PENDING_WAO_APPROVAL"
        )
        officer = (
            approved_by_wao.strip()
            if approved_by_wao and approved_by_wao.strip()
            else (
                (run.get("decision") or {}).get("wao_officer_name")
                or advisory.get("approved_by_wao")
            )
        )
        dispatched = (
            1
            if (approval_status == "APPROVED_DISPATCHED" and bool(officer))
            else 0
        )

        plot_ids = citations.get("plot_ids") or advisory.get("affected_plot_ids") or []
        sensor_ids = citations.get("sensor_ids") or []
        rule_id = citations.get("kalro_rule_id") or "KALRO-HB-2026-01"
        bulletin_id = citations.get("weather_bulletin_id") or "KMD-2026-10-14"
        voucher = advisory.get("evoucher_package_code") or "PENDING-VERIFICATION"
        sms_en = advisory.get("draft_sms_english") or "Verification required before SMS dispatch."
        sms_sw = advisory.get("draft_sms_swahili") or "Uthibitisho wa WAO unahitajika."
        ussd_code = advisory.get("ussd_menu_payload") or "*384*55#"

        artifact_payloads: list[tuple[str, str, str]] = [
            (
                "field_brief",
                f"{ward} Ward Extension Field Brief ({run_id})",
                (
                    f"# Field Brief — {ward}\n"
                    f"- Run ID: {run_id}\n"
                    f"- Approval Status: {approval_status}\n"
                    f"- Approved By WAO: {officer or 'Pending WAO sign-off'}\n"
                    f"- Citations: Rule {rule_id}, Bulletin {bulletin_id}, Sensors {', '.join(sensor_ids) or 'None'}\n"
                    f"- Target Plots ({len(plot_ids)}): {', '.join(plot_ids) or 'Pending plot verification'}\n"
                    f"- Recommended Action: {sms_en}\n"
                    f"- e-Voucher Package: {voucher}\n"
                ),
            ),
            (
                "sms",
                f"{ward} Farmer SMS Copy ({run_id})",
                (
                    f"[EN] {sms_en} (Ref: {rule_id}, Voucher: {voucher})\n"
                    f"[SW] {sms_sw} (Kumb: {rule_id}, Vocha: {voucher})\n"
                    f"Status: {approval_status} | Officer: {officer or 'UNAPPROVED'}"
                ),
            ),
            (
                "ussd",
                f"{ward} USSD Menu Payload ({run_id})",
                (
                    f"Menu Code: {ussd_code}\n"
                    f"CON Ecovuna {ward}\n"
                    f"Rule: {rule_id} | Voucher: {voucher}\n"
                    f"Plots: {len(plot_ids)} | Status: {approval_status}"
                ),
            ),
            (
                "visit_list",
                f"{ward} Priority Visit List ({run_id})",
                (
                    f"Ward: {ward} | Run: {run_id} | Status: {approval_status}\n"
                    + (
                        "\n".join(
                            f"- Plot {pid} (Sensor: {sensor_ids[0] if sensor_ids else 'N/A'}, Rule: {rule_id})"
                            for pid in plot_ids
                        )
                        if plot_ids
                        else "- Field verification required before plot assignment."
                    )
                ),
            ),
        ]

        now = datetime.now(UTC).isoformat()
        created_artifacts: list[dict[str, Any]] = []
        with connect() as db:
            for art_type, title, content_text in artifact_payloads:
                group_id = f"AGRP-{run_id}-{art_type.upper()}"
                max_ver_row = db.execute(
                    "SELECT COALESCE(MAX(version), 0) FROM field_artifacts WHERE artifact_group_id = ?",
                    (group_id,),
                ).fetchone()
                next_version = int(max_ver_row[0]) + 1
                artifact_id = f"ART-{uuid.uuid4().hex[:10].upper()}"
                metadata = {
                    "copyable": True,
                    "download_filename": f"{run_id.lower()}_{art_type}_v{next_version}.txt",
                    "mime_type": "text/plain; charset=utf-8",
                }
                db.execute(
                    """
                    INSERT INTO field_artifacts
                      (artifact_id, artifact_group_id, version, run_id, session_id, ward,
                       artifact_type, title, content_text, metadata_json, citations_json,
                       approval_status, approved_by_wao, dispatched, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        artifact_id,
                        group_id,
                        next_version,
                        run_id,
                        session_id,
                        ward,
                        art_type,
                        title,
                        content_text,
                        json.dumps(metadata),
                        json.dumps(citations),
                        approval_status,
                        officer,
                        dispatched,
                        now,
                    ),
                )
                created_artifacts.append(
                    {
                        "artifact_id": artifact_id,
                        "artifact_group_id": group_id,
                        "version": next_version,
                        "run_id": run_id,
                        "session_id": session_id,
                        "ward": ward,
                        "artifact_type": art_type,
                        "title": title,
                        "content_text": content_text,
                        "metadata": metadata,
                        "citations": citations,
                        "approval_status": approval_status,
                        "approved_by_wao": officer,
                        "dispatched": bool(dispatched),
                        "created_at": now,
                    }
                )
        return created_artifacts

    def list_artifacts(
        self,
        *,
        run_id: str | None = None,
        session_id: str | None = None,
        ward: str | None = None,
        approval_status: str | None = None,
        latest_only: bool = True,
    ) -> list[dict[str, Any]]:
        initialize()
        clauses: list[str] = []
        params: list[Any] = []
        if run_id:
            clauses.append("run_id = ?")
            params.append(run_id)
        if session_id:
            clauses.append("session_id = ?")
            params.append(session_id)
        if ward:
            clauses.append("ward = ?")
            params.append(ward)
        if approval_status:
            clauses.append("approval_status = ?")
            params.append(approval_status)

        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    f"SELECT * FROM field_artifacts {where_sql} ORDER BY created_at DESC, version DESC",
                    params,
                )
            ]

        parsed: list[dict[str, Any]] = []
        seen_groups: set[str] = set()
        for row in rows:
            group_id = row["artifact_group_id"]
            if latest_only and group_id in seen_groups:
                continue
            seen_groups.add(group_id)
            row["metadata"] = json.loads(row.pop("metadata_json") or "{}")
            row["citations"] = json.loads(row.pop("citations_json") or "{}")
            row["dispatched"] = bool(row["dispatched"])
            parsed.append(row)
        return parsed

    def get_artifact(self, artifact_id: str) -> dict[str, Any]:
        initialize()
        with connect() as db:
            row = db.execute(
                "SELECT * FROM field_artifacts WHERE artifact_id = ?",
                (artifact_id,),
            ).fetchone()
        if not row:
            raise NotFoundError(
                f"Artifact '{artifact_id}' was not found.",
                error_code="ARTIFACT_NOT_FOUND",
            )
        item = dict(row)
        item["metadata"] = json.loads(item.pop("metadata_json") or "{}")
        item["citations"] = json.loads(item.pop("citations_json") or "{}")
        item["dispatched"] = bool(item["dispatched"])
        return item

    def assert_artifact_dispatchable(self, artifact_id: str) -> dict[str, Any]:
        """Enforce that an unapproved artifact can never be treated as dispatched."""
        artifact = self.get_artifact(artifact_id)
        if (
            artifact["approval_status"] != "APPROVED_DISPATCHED"
            or not artifact["approved_by_wao"]
            or not artifact["dispatched"]
        ):
            raise PolicyViolationError(
                f"Artifact '{artifact_id}' is unapproved ({artifact['approval_status']}) and cannot be treated as dispatched.",
                error_code="UNAPPROVED_ARTIFACT_DISPATCH_FORBIDDEN",
                details={
                    "artifact_id": artifact_id,
                    "approval_status": artifact["approval_status"],
                    "dispatched": artifact["dispatched"],
                },
            )
        return artifact

    def list_sessions(
        self,
        *,
        ward: str | None = None,
        date_prefix: str | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        """List persisted sessions filtered by ward, date prefix, or latest run status."""
        initialize()
        clauses: list[str] = []
        params: list[Any] = []
        if ward:
            clauses.append("ward = ?")
            params.append(ward)
        if date_prefix:
            clauses.append("updated_at LIKE ?")
            params.append(f"{date_prefix}%")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        with connect() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    f"SELECT * FROM conversation_sessions {where_sql} ORDER BY updated_at DESC",
                    params,
                )
            ]
            results: list[dict[str, Any]] = []
            for row in rows:
                prior_runs = json.loads(row.pop("prior_run_ids_json") or "[]")
                unresolved = json.loads(row.pop("unresolved_questions_json") or "[]")
                latest_status = "NEW"
                if prior_runs:
                    run_row = db.execute(
                        "SELECT status FROM agent_runs WHERE run_id = ?",
                        (prior_runs[-1],),
                    ).fetchone()
                    if run_row:
                        latest_status = run_row["status"]
                if status and latest_status != status:
                    continue
                results.append(
                    {
                        **row,
                        "prior_run_ids": prior_runs,
                        "unresolved_questions": unresolved,
                        "latest_run_status": latest_status,
                        "can_continue_safely": latest_status in SAFE_RESUME_CHECKPOINTS or latest_status == "NEW",
                    }
                )
        return results

    def verify_safe_checkpoint(self, run_id: str) -> dict[str, Any]:
        """Allow continuing a run only from safe checkpoints."""
        initialize()
        with connect() as db:
            row = db.execute(
                "SELECT run_id, status, current_node FROM agent_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if not row:
            raise NotFoundError(
                f"Run '{run_id}' was not found.",
                error_code="RUN_NOT_FOUND",
            )
        status = row["status"]
        if status not in SAFE_RESUME_CHECKPOINTS:
            raise InvalidRequestError(
                f"Run '{run_id}' is in terminal state '{status}' and cannot be resumed from this checkpoint.",
                error_code="UNSAFE_CHECKPOINT_CONTINUATION",
            )
        return dict(row)


repository = ArtifactSessionRepository()
