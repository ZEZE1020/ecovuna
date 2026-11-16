"""MCP server registry and recent tool activity router."""

from __future__ import annotations

from fastapi import APIRouter

from ..contracts import (
    McpActivityEntryResponse,
    McpRegistryResponse,
    McpServerStatusResponse,
)
from ..db import connect

router = APIRouter(tags=["mcp"])


@router.get("/api/mcp/registry", response_model=McpRegistryResponse)
def mcp_registry() -> McpRegistryResponse:
    """Expose the configured MCP servers and recent tool activity."""
    servers = [
        McpServerStatusResponse(
            id="ecovuna-telemetry",
            name="Ecovuna Telemetry",
            transport="local process",
            tools=[
                "fetch_kijanibox_telemetry",
                "fetch_open_meteo_context",
                "fetch_kalro_guidelines",
                "stage_advisory_for_wao_approval",
            ],
            status="ready",
        ),
        McpServerStatusResponse(
            id="kalro-reference-fetch",
            name="KALRO Reference Fetch",
            transport="MCP subprocess",
            tools=["fetch"],
            status="configured",
        ),
    ]
    with connect() as db:
        activity = [
            McpActivityEntryResponse.model_validate(dict(row))
            for row in db.execute(
                "SELECT server, tool_name, timestamp FROM mcp_audit_log ORDER BY id DESC LIMIT 10"
            )
        ]
    return McpRegistryResponse(servers=servers, recent_activity=activity)
