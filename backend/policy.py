"""Server-side tool permissions and action policy enforcement (#18)."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from .db import connect, initialize
from .errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    PolicyViolationError,
)


class ToolCategory(StrEnum):
    READ = "read"
    DRAFT = "draft"
    STAGE = "stage"
    EXTERNAL_ACTION = "external_action"


@dataclass(frozen=True)
class ToolPolicyRule:
    tool_name: str
    category: ToolCategory
    required_evidence: tuple[str, ...]
    allowed_callers: tuple[str, ...]
    requires_named_officer: bool
    requires_approval_token: bool
    idempotent_once: bool

    def as_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["category"] = str(self.category)
        return payload


TOOL_POLICIES: dict[str, ToolPolicyRule] = {
    "fetch_kijanibox_telemetry": ToolPolicyRule(
        tool_name="fetch_kijanibox_telemetry",
        category=ToolCategory.READ,
        required_evidence=(),
        allowed_callers=("agent", "api", "mcp", "chat"),
        requires_named_officer=False,
        requires_approval_token=False,
        idempotent_once=False,
    ),
    "fetch_open_meteo_context": ToolPolicyRule(
        tool_name="fetch_open_meteo_context",
        category=ToolCategory.READ,
        required_evidence=(),
        allowed_callers=("agent", "api", "mcp", "chat"),
        requires_named_officer=False,
        requires_approval_token=False,
        idempotent_once=False,
    ),
    "fetch_kalro_guidelines": ToolPolicyRule(
        tool_name="fetch_kalro_guidelines",
        category=ToolCategory.READ,
        required_evidence=(),
        allowed_callers=("agent", "api", "mcp", "chat"),
        requires_named_officer=False,
        requires_approval_token=False,
        idempotent_once=False,
    ),
    "create_execution_plan": ToolPolicyRule(
        tool_name="create_execution_plan",
        category=ToolCategory.DRAFT,
        required_evidence=(),
        allowed_callers=("agent", "api", "mcp", "chat"),
        requires_named_officer=False,
        requires_approval_token=False,
        idempotent_once=False,
    ),
    "stage_advisory_for_wao_approval": ToolPolicyRule(
        tool_name="stage_advisory_for_wao_approval",
        category=ToolCategory.STAGE,
        required_evidence=("sensor_ids", "plot_ids", "kalro_rule_id"),
        allowed_callers=("agent", "api", "mcp", "chat"),
        requires_named_officer=False,
        requires_approval_token=False,
        idempotent_once=True,
    ),
    "wao_decision": ToolPolicyRule(
        tool_name="wao_decision",
        category=ToolCategory.EXTERNAL_ACTION,
        required_evidence=("sensor_ids", "plot_ids", "kalro_rule_id"),
        allowed_callers=("agent", "api", "mcp", "chat", "officer"),
        requires_named_officer=True,
        requires_approval_token=True,
        idempotent_once=True,
    ),
    "dispatch_advisory": ToolPolicyRule(
        tool_name="dispatch_advisory",
        category=ToolCategory.EXTERNAL_ACTION,
        required_evidence=("sensor_ids", "plot_ids", "kalro_rule_id"),
        allowed_callers=("api", "mcp", "officer"),
        requires_named_officer=True,
        requires_approval_token=True,
        idempotent_once=True,
    ),
    "confirm_input_order": ToolPolicyRule(
        tool_name="confirm_input_order",
        category=ToolCategory.EXTERNAL_ACTION,
        required_evidence=("plot_ids", "sensor_ids"),
        allowed_callers=("api", "mcp", "officer"),
        requires_named_officer=True,
        requires_approval_token=True,
        idempotent_once=True,
    ),
    "update_credit_flag": ToolPolicyRule(
        tool_name="update_credit_flag",
        category=ToolCategory.EXTERNAL_ACTION,
        required_evidence=("plot_ids", "sensor_ids"),
        allowed_callers=("api", "mcp", "officer"),
        requires_named_officer=True,
        requires_approval_token=True,
        idempotent_once=True,
    ),
}

_DISALLOWED_OFFICER_TOKENS = {
    "system",
    "anonymous",
    "bot",
    "agent",
    "auto",
    "unknown",
    "farmer",
    "guest",
    "admin",
}


def mint_approval_token(run_id: str, advisory_id: str) -> str:
    """Create a deterministic approval token bound to a specific run and staged advisory."""
    digest = hashlib.sha256(f"{run_id}:{advisory_id}:ecovuna-wao-gate".encode()).hexdigest()
    return f"APR-{run_id}-{digest[:10].upper()}"


def record_policy_decision(
    *,
    run_id: str,
    tool_name: str,
    category: str,
    channel: str,
    officer_id: str,
    approval_token: str,
    allowed: bool,
    error_code: str,
    reason: str,
) -> dict[str, Any]:
    """Persist policy check result in both policy_decisions and mcp_audit_log."""
    initialize()
    decision_id = f"POL-{uuid.uuid4().hex[:10].upper()}"
    now = datetime.now(UTC).isoformat()
    record = {
        "decision_id": decision_id,
        "run_id": run_id,
        "tool_name": tool_name,
        "category": category,
        "channel": channel,
        "officer_id": officer_id,
        "approval_token": approval_token,
        "allowed": allowed,
        "error_code": error_code,
        "reason": reason,
        "created_at": now,
    }
    with connect() as db:
        db.execute(
            """
            INSERT INTO policy_decisions
              (decision_id, run_id, tool_name, category, channel, officer_id,
               approval_token, allowed, error_code, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                decision_id,
                run_id,
                tool_name,
                category,
                channel,
                officer_id,
                approval_token,
                1 if allowed else 0,
                error_code,
                reason,
                now,
            ),
        )
        db.execute(
            """
            INSERT INTO mcp_audit_log
              (timestamp, run_id, server, tool_name, action, input_json, output_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                now,
                run_id,
                "Ecovuna_Policy",
                tool_name,
                "policy_allowed" if allowed else "policy_rejected",
                json.dumps(
                    {
                        "channel": channel,
                        "officer_id": officer_id,
                        "approval_token": approval_token,
                    }
                ),
                json.dumps(
                    {
                        "decision_id": decision_id,
                        "allowed": allowed,
                        "error_code": error_code,
                        "reason": reason,
                    }
                ),
            ),
        )
    return record


def validate_officer_identity(wao_officer_name: str) -> str:
    """Validate that the caller supplies a named Ward Agricultural Officer identity."""
    cleaned = wao_officer_name.strip() if wao_officer_name else ""
    if not cleaned:
        raise InvalidRequestError(
            "wao_officer_name is required for any decision",
            error_code="MISSING_OFFICER",
        )
    lowered = cleaned.lower()
    if lowered in _DISALLOWED_OFFICER_TOKENS or "wao-" not in lowered:
        raise PolicyViolationError(
            "Action requires a named Ward Agricultural Officer with a valid WAO-* badge.",
            error_code="UNAUTHORIZED_OFFICER",
        )
    name_part = cleaned.split("WAO-")[0].replace("—", "").replace("-", "").strip()
    if len(name_part) < 3 or name_part.lower() in _DISALLOWED_OFFICER_TOKENS:
        raise PolicyViolationError(
            "Officer identity must include a full human name alongside the WAO-* badge.",
            error_code="UNAUTHORIZED_OFFICER",
        )
    return cleaned


def enforce_stage_policy(
    *,
    run_id: str,
    plot_ids: list[str],
    citations: dict[str, Any],
    channel: str = "agent",
) -> dict[str, Any]:
    """Enforce evidence and idempotency policy before staging an advisory."""
    rule = TOOL_POLICIES["stage_advisory_for_wao_approval"]
    if channel not in rule.allowed_callers:
        record_policy_decision(
            run_id=run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id="agent",
            approval_token="",
            allowed=False,
            error_code="UNAUTHORIZED_CALLER",
            reason=f"Caller channel '{channel}' is not permitted to stage advisories.",
        )
        raise PolicyViolationError(
            f"Caller channel '{channel}' is not permitted to stage advisories.",
            error_code="UNAUTHORIZED_CALLER",
        )

    missing_keys = [
        key for key in rule.required_evidence if not citations.get(key)
    ]
    if not plot_ids or missing_keys:
        record_policy_decision(
            run_id=run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id="agent",
            approval_token="",
            allowed=False,
            error_code="INSUFFICIENT_EVIDENCE",
            reason="Advisory must include plot_ids, sensor_ids, and kalro_rule_id before staging.",
        )
        raise PolicyViolationError(
            "Advisory must include plot_ids, sensor_ids, and kalro_rule_id before staging",
            error_code="INSUFFICIENT_EVIDENCE",
        )

    with connect() as db:
        existing = db.execute(
            "SELECT advisory_id FROM staged_advisories WHERE run_id = ?",
            (run_id,),
        ).fetchone()
    if existing:
        record_policy_decision(
            run_id=run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id="agent",
            approval_token="",
            allowed=False,
            error_code="DUPLICATE_STAGE_WRITE",
            reason=f"Run '{run_id}' already has a staged advisory.",
        )
        raise ConflictError(
            f"Run '{run_id}' already has a staged advisory.",
            error_code="DUPLICATE_STAGE_WRITE",
        )

    return record_policy_decision(
        run_id=run_id,
        tool_name=rule.tool_name,
        category=rule.category,
        channel=channel,
        officer_id="agent",
        approval_token="",
        allowed=True,
        error_code="OK",
        reason="Grounded evidence verified for staging.",
    )


def enforce_decision_policy(
    *,
    run_id: str,
    approved: bool,
    wao_officer_name: str,
    approval_token: str | None = None,
    channel: str = "api",
    require_explicit_token: bool = False,
) -> dict[str, Any]:
    """Validate run existence, evidence, officer identity, approval token, and replay rules."""
    rule = TOOL_POLICIES["wao_decision"]
    clean_run_id = run_id.strip() if run_id else ""
    if not clean_run_id:
        record_policy_decision(
            run_id="",
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=wao_officer_name or "",
            approval_token=approval_token or "",
            allowed=False,
            error_code="UNKNOWN_RUN",
            reason="run_id is required.",
        )
        raise NotFoundError("Run was not found.", error_code="UNKNOWN_RUN")

    try:
        officer = validate_officer_identity(wao_officer_name)
    except (InvalidRequestError, PolicyViolationError) as exc:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=wao_officer_name or "",
            approval_token=approval_token or "",
            allowed=False,
            error_code=exc.error_code,
            reason=exc.message,
        )
        raise

    if channel not in rule.allowed_callers:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token or "",
            allowed=False,
            error_code="UNAUTHORIZED_CALLER",
            reason=f"Channel '{channel}' is not allowed to record WAO decisions.",
        )
        raise PolicyViolationError(
            f"Channel '{channel}' is not allowed to record WAO decisions.",
            error_code="UNAUTHORIZED_CALLER",
        )

    with connect() as db:
        run_row = db.execute(
            "SELECT status, state_json FROM agent_runs WHERE run_id = ?",
            (clean_run_id,),
        ).fetchone()
        advisory_row = db.execute(
            "SELECT advisory_id, status, affected_plot_ids_json, citations_json "
            "FROM staged_advisories WHERE run_id = ?",
            (clean_run_id,),
        ).fetchone()
        prior_decision = db.execute(
            "SELECT decision_id FROM policy_decisions "
            "WHERE run_id = ? AND tool_name = 'wao_decision' AND allowed = 1",
            (clean_run_id,),
        ).fetchone()

    if not run_row and not advisory_row:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token or "",
            allowed=False,
            error_code="UNKNOWN_RUN",
            reason=f"Run '{clean_run_id}' does not exist.",
        )
        raise NotFoundError(
            f"Run '{clean_run_id}' does not exist.",
            error_code="UNKNOWN_RUN",
        )

    if prior_decision is not None:
        error_code = "REPLAYED_APPROVAL" if approval_token else "RUN_ALREADY_DECIDED"
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token or "",
            allowed=False,
            error_code=error_code,
            reason=f"Run '{clean_run_id}' has already been decided; approval cannot be replayed.",
        )
        raise ConflictError(
            f"Run '{clean_run_id}' has already been decided; approval cannot be replayed.",
            error_code=error_code,
        )

    if run_row and run_row["status"] in {"APPROVED_DISPATCHED", "REJECTED_FIELD_VISIT"}:
        error_code = "REPLAYED_APPROVAL" if approval_token else "RUN_ALREADY_DECIDED"
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token or "",
            allowed=False,
            error_code=error_code,
            reason=f"Run '{clean_run_id}' is already in terminal state '{run_row['status']}'.",
        )
        raise ConflictError(
            f"Run '{clean_run_id}' is already in terminal state '{run_row['status']}'.",
            error_code=error_code,
        )

    if advisory_row is None:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token or "",
            allowed=False,
            error_code="INSUFFICIENT_EVIDENCE",
            reason=f"Run '{clean_run_id}' has no staged advisory due to missing or conflicting evidence.",
        )
        raise PolicyViolationError(
            f"Run '{clean_run_id}' has no staged advisory due to missing or conflicting evidence.",
            error_code="INSUFFICIENT_EVIDENCE",
        )

    if advisory_row["status"] != "PENDING_WAO_APPROVAL":
        error_code = "REPLAYED_APPROVAL" if approval_token else "RUN_ALREADY_DECIDED"
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token or "",
            allowed=False,
            error_code=error_code,
            reason=f"Advisory for run '{clean_run_id}' is already '{advisory_row['status']}'.",
        )
        raise ConflictError(
            f"Advisory for run '{clean_run_id}' is already '{advisory_row['status']}'.",
            error_code=error_code,
        )

    plot_ids = json.loads(advisory_row["affected_plot_ids_json"])
    citations = json.loads(advisory_row["citations_json"])
    missing_evidence = [
        key for key in rule.required_evidence if not citations.get(key)
    ]
    if not plot_ids or missing_evidence:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=rule.tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token or "",
            allowed=False,
            error_code="INSUFFICIENT_EVIDENCE",
            reason="Advisory is missing required citations or plot_ids.",
        )
        raise PolicyViolationError(
            "Advisory is missing required citations or plot_ids.",
            error_code="INSUFFICIENT_EVIDENCE",
        )

    expected_token = mint_approval_token(clean_run_id, advisory_row["advisory_id"])
    if require_explicit_token or approval_token is not None:
        if not approval_token or not approval_token.strip():
            record_policy_decision(
                run_id=clean_run_id,
                tool_name=rule.tool_name,
                category=rule.category,
                channel=channel,
                officer_id=officer,
                approval_token="",
                allowed=False,
                error_code="MISSING_APPROVAL_TOKEN",
                reason="Approval token is required for consequential action.",
            )
            raise PolicyViolationError(
                "Approval token is required for consequential action.",
                error_code="MISSING_APPROVAL_TOKEN",
            )
        if approval_token.strip() != expected_token:
            record_policy_decision(
                run_id=clean_run_id,
                tool_name=rule.tool_name,
                category=rule.category,
                channel=channel,
                officer_id=officer,
                approval_token=approval_token.strip(),
                allowed=False,
                error_code="INVALID_APPROVAL_TOKEN",
                reason="Approval token does not match the staged advisory for this run.",
            )
            raise PolicyViolationError(
                "Approval token does not match the staged advisory for this run.",
                error_code="INVALID_APPROVAL_TOKEN",
            )

    policy_record = record_policy_decision(
        run_id=clean_run_id,
        tool_name=rule.tool_name,
        category=rule.category,
        channel=channel,
        officer_id=officer,
        approval_token=expected_token,
        allowed=True,
        error_code="OK",
        reason="Approved for dispatch." if approved else "Rejected; flagged for field visit.",
    )
    return {
        "officer": officer,
        "advisory_id": advisory_row["advisory_id"],
        "approval_token": expected_token,
        "policy_decision": policy_record,
    }


def execute_consequential_action(
    *,
    tool_name: str,
    run_id: str,
    wao_officer_name: str,
    approval_token: str | None,
    payload: dict[str, Any] | None = None,
    channel: str = "api",
) -> dict[str, Any]:
    """Enforce server-side policy on direct dispatch, input ordering, or credit flag actions."""
    if tool_name not in {
        "dispatch_advisory",
        "confirm_input_order",
        "update_credit_flag",
    }:
        raise InvalidRequestError(
            f"Unsupported consequential tool '{tool_name}'.",
            error_code="UNSUPPORTED_TOOL",
        )
    rule = TOOL_POLICIES[tool_name]
    clean_run_id = run_id.strip() if run_id else ""
    try:
        officer = validate_officer_identity(wao_officer_name)
    except (InvalidRequestError, PolicyViolationError) as exc:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=tool_name,
            category=rule.category,
            channel=channel,
            officer_id=wao_officer_name or "",
            approval_token=approval_token or "",
            allowed=False,
            error_code=exc.error_code,
            reason=exc.message,
        )
        raise

    if not approval_token or not approval_token.strip():
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token="",
            allowed=False,
            error_code="MISSING_APPROVAL_TOKEN",
            reason=f"{tool_name} requires a valid WAO approval token.",
        )
        raise PolicyViolationError(
            f"{tool_name} requires a valid WAO approval token.",
            error_code="MISSING_APPROVAL_TOKEN",
        )

    with connect() as db:
        advisory_row = db.execute(
            "SELECT advisory_id, status, citations_json FROM staged_advisories WHERE run_id = ?",
            (clean_run_id,),
        ).fetchone()
        prior_action = db.execute(
            "SELECT decision_id FROM policy_decisions "
            "WHERE run_id = ? AND tool_name = ? AND allowed = 1",
            (clean_run_id, tool_name),
        ).fetchone()

    if not advisory_row:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token.strip(),
            allowed=False,
            error_code="UNKNOWN_RUN",
            reason=f"Run '{clean_run_id}' does not exist.",
        )
        raise NotFoundError(
            f"Run '{clean_run_id}' does not exist.",
            error_code="UNKNOWN_RUN",
        )

    expected_token = mint_approval_token(clean_run_id, advisory_row["advisory_id"])
    if approval_token.strip() != expected_token:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=approval_token.strip(),
            allowed=False,
            error_code="INVALID_APPROVAL_TOKEN",
            reason="Approval token is invalid for this run.",
        )
        raise PolicyViolationError(
            "Approval token is invalid for this run.",
            error_code="INVALID_APPROVAL_TOKEN",
        )

    if advisory_row["status"] == "REJECTED_FIELD_VISIT":
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=expected_token,
            allowed=False,
            error_code="REJECTED_NOT_DISPATCHABLE",
            reason="Rejected or field-visit advisories cannot execute external actions.",
        )
        raise PolicyViolationError(
            "Rejected or field-visit advisories cannot execute external actions.",
            error_code="REJECTED_NOT_DISPATCHABLE",
        )

    if advisory_row["status"] != "APPROVED_DISPATCHED":
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=expected_token,
            allowed=False,
            error_code="UNAPPROVED_ACTION",
            reason="Run must be approved by a named WAO officer before executing external actions.",
        )
        raise PolicyViolationError(
            "Run must be approved by a named WAO officer before executing external actions.",
            error_code="UNAPPROVED_ACTION",
        )

    if prior_action is not None:
        record_policy_decision(
            run_id=clean_run_id,
            tool_name=tool_name,
            category=rule.category,
            channel=channel,
            officer_id=officer,
            approval_token=expected_token,
            allowed=False,
            error_code="REPLAYED_APPROVAL",
            reason=f"{tool_name} has already been executed for run '{clean_run_id}'.",
        )
        raise ConflictError(
            f"{tool_name} has already been executed for run '{clean_run_id}'.",
            error_code="REPLAYED_APPROVAL",
        )

    policy_record = record_policy_decision(
        run_id=clean_run_id,
        tool_name=tool_name,
        category=rule.category,
        channel=channel,
        officer_id=officer,
        approval_token=expected_token,
        allowed=True,
        error_code="OK",
        reason=f"Consequential action {tool_name} authorized by {officer}.",
    )
    return {
        "run_id": clean_run_id,
        "tool_name": tool_name,
        "status": "EXECUTED",
        "wao_officer_name": officer,
        "approval_token": expected_token,
        "payload": payload or {},
        "policy_decision": policy_record,
    }
