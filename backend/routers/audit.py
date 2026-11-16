"""Append-only audit trail router."""

from __future__ import annotations

from fastapi import APIRouter

from ..contracts import AuditLogEntryResponse
from ..db import connect

router = APIRouter(tags=["audit"])


@router.get("/api/audit-logs", response_model=list[AuditLogEntryResponse])
def audit_logs() -> list[AuditLogEntryResponse]:
    with connect() as db:
        return [
            AuditLogEntryResponse.model_validate(dict(row))
            for row in db.execute(
                "SELECT * FROM mcp_audit_log ORDER BY id DESC LIMIT 100"
            )
        ]
