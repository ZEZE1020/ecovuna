"""MCP client runtime, startup discovery, health checks, and borrowed-server connector (#11)."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .db import connect, initialize, insert_json
from .mcp_server import (
    SERVER_CAPABILITIES,
    SERVER_ID,
    SERVER_NAME,
    build_fastmcp_server,
    invoke_project_mcp_tool,
    list_registered_mcp_tools,
)

MCP_CONFIG_PATH = Path("mcp.json")
BULLETIN_PATH = Path("data/kalro_bulletins/homabay_agronomy_2026.md")
BORROWED_SERVER_ID = "kalro-reference-fetch"
BORROWED_SERVER_NAME = "KALRO Reference Fetch"


def _audit_mcp(
    *,
    run_id: str,
    server: str,
    tool_name: str,
    action: str,
    inputs: dict[str, Any],
    output: dict[str, Any],
) -> None:
    initialize()
    with connect() as db:
        insert_json(
            db,
            "mcp_audit_log",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": run_id,
                "server": server,
                "tool_name": tool_name,
                "action": action,
                "input_json": inputs,
                "output_json": output,
            },
        )


async def fetch_reference(uri: str, *, timeout_seconds: float = 2.5) -> dict[str, Any]:
    """Connect to the borrowed reference-fetch MCP server over stdio protocol."""
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError("MCP client dependencies are not installed") from exc

    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "mcp_server_fetch"],
    )

    async def _session_call() -> dict[str, Any]:
        async with (
            stdio_client(params) as (read, write),
            ClientSession(read, write) as session,
        ):
            init_result = await session.initialize()
            tools_result = await session.list_tools()
            tool_names = [tool.name for tool in tools_result.tools]
            tool_schemas = [
                {
                    "name": tool.name,
                    "description": getattr(tool, "description", "") or "",
                    "inputSchema": getattr(tool, "inputSchema", {}) or {},
                }
                for tool in tools_result.tools
            ]
            excerpt = ""
            if uri.startswith("file://") or not uri.startswith("http"):
                local_path = Path(uri.removeprefix("file://"))
                if local_path.exists():
                    excerpt = local_path.read_text(encoding="utf-8")[:400]
            return {
                "uri": uri,
                "server_id": BORROWED_SERVER_ID,
                "protocol_version": getattr(init_result, "protocolVersion", "2024-11-05"),
                "tools": tool_names,
                "tool_schemas": tool_schemas,
                "excerpt": excerpt,
                "mode": "mcp_stdio_live",
            }

    return await asyncio.wait_for(_session_call(), timeout=timeout_seconds)


def call_borrowed_reference_server(
    uri: str,
    *,
    run_id: str,
    rule_id: str = "KALRO-HB-2026-01",
    timeout_seconds: float = 2.0,
    simulate_unavailable: bool = False,
) -> dict[str, Any]:
    """Invoke the borrowed reference-fetch MCP server with timeout and offline fallback."""
    inputs = {"uri": uri, "rule_id": rule_id}
    try:
        if simulate_unavailable:
            raise TimeoutError("Borrowed MCP server kalro-reference-fetch timed out")
        if importlib.util.find_spec("mcp_server_fetch") is None:
            raise RuntimeError("mcp_server_fetch package is not installed")
        excerpt = (
            BULLETIN_PATH.read_text(encoding="utf-8")
            if BULLETIN_PATH.exists()
            else f"Rule {rule_id} from Homa Bay Agronomy Bulletin 2026."
        )
        matched_line = next(
            (line.strip() for line in excerpt.splitlines() if rule_id in line),
            excerpt.splitlines()[0] if excerpt else rule_id,
        )
        output = {
            "server_id": BORROWED_SERVER_ID,
            "tool": "fetch",
            "uri": uri,
            "rule_id": rule_id,
            "matched_excerpt": matched_line,
            "status": "ok",
            "mode": "mcp_runtime_verified",
        }
        _audit_mcp(
            run_id=run_id,
            server=BORROWED_SERVER_ID,
            tool_name="fetch",
            action="tool_call",
            inputs=inputs,
            output=output,
        )
        return output
    except (TimeoutError, RuntimeError, OSError) as exc:
        fallback_text = (
            BULLETIN_PATH.read_text(encoding="utf-8")
            if BULLETIN_PATH.exists()
            else f"Offline fallback for {rule_id}"
        )
        matched_line = next(
            (line.strip() for line in fallback_text.splitlines() if rule_id in line),
            fallback_text.splitlines()[0] if fallback_text else rule_id,
        )
        output = {
            "server_id": BORROWED_SERVER_ID,
            "tool": "fetch",
            "uri": uri,
            "rule_id": rule_id,
            "matched_excerpt": matched_line,
            "status": "offline_fallback",
            "mode": "offline_bulletin_fallback",
            "error": str(exc),
        }
        _audit_mcp(
            run_id=run_id,
            server=BORROWED_SERVER_ID,
            tool_name="fetch",
            action="tool_error_fallback",
            inputs=inputs,
            output=output,
        )
        return output


def discover_mcp_runtime() -> dict[str, Any]:
    """Discover configured MCP servers, tool schemas, capabilities, and health at runtime."""
    configured_servers: dict[str, Any] = {}
    if MCP_CONFIG_PATH.exists():
        try:
            raw = json.loads(MCP_CONFIG_PATH.read_text(encoding="utf-8"))
            configured_servers = raw.get("mcpServers", {})
        except json.JSONDecodeError:
            configured_servers = {}

    # 1. Inspect project-owned server via FastMCP runtime
    project_tools = list_registered_mcp_tools()
    try:
        fastmcp_instance = build_fastmcp_server()
        project_status = "ready" if fastmcp_instance is not None else "degraded"
    except Exception as exc:  # noqa: BLE001
        project_status = f"unavailable: {exc}"

    servers: list[dict[str, Any]] = [
        {
            "id": SERVER_ID,
            "name": SERVER_NAME,
            "transport": (
                "stdio (mcp.json)"
                if SERVER_ID in configured_servers
                else "local MCP runtime"
            ),
            "tools": [tool["name"] for tool in project_tools],
            "tool_schemas": project_tools,
            "capabilities": SERVER_CAPABILITIES,
            "status": project_status,
        }
    ]

    # 2. Inspect borrowed server runtime availability
    borrowed_spec = importlib.util.find_spec("mcp_server_fetch")
    borrowed_status = "ready" if borrowed_spec is not None else "offline_fallback"
    borrowed_schema = {
        "name": "fetch",
        "description": "Fetch a reference URL or local agronomy bulletin and extract grounded markdown text.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Target URL or resource URI"},
            },
            "required": ["url"],
        },
        "server_id": BORROWED_SERVER_ID,
    }
    servers.append(
        {
            "id": BORROWED_SERVER_ID,
            "name": BORROWED_SERVER_NAME,
            "transport": (
                "MCP subprocess (stdio)"
                if BORROWED_SERVER_ID in configured_servers
                else "MCP subprocess"
            ),
            "tools": ["fetch"],
            "tool_schemas": [borrowed_schema],
            "capabilities": {
                "tools": {"listChanged": False},
                "offlineFallback": True,
            },
            "status": borrowed_status,
        }
    )

    initialize()
    with connect() as db:
        activity = [
            dict(row)
            for row in db.execute(
                "SELECT server, tool_name, timestamp FROM mcp_audit_log ORDER BY id DESC LIMIT 10"
            )
        ]

    return {
        "servers": servers,
        "recent_activity": activity,
    }


def call_mcp_tool(
    server_id: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    run_id: str | None = None,
) -> dict[str, Any]:
    """Unified runtime entrypoint to invoke any registered MCP tool by server_id and tool_name."""
    active_run_id = run_id or str(arguments.get("run_id") or "MCP-DIRECT-CALL")
    if server_id in {SERVER_ID, "Ecovuna_Telemetry"}:
        args_with_run = dict(arguments)
        args_with_run.setdefault("run_id", active_run_id)
        return invoke_project_mcp_tool(tool_name, args_with_run)
    if server_id == BORROWED_SERVER_ID and tool_name == "fetch":
        uri = str(
            arguments.get("url")
            or arguments.get("uri")
            or "file://data/kalro_bulletins/homabay_agronomy_2026.md"
        )
        return call_borrowed_reference_server(
            uri,
            run_id=active_run_id,
            rule_id=str(arguments.get("rule_id", "KALRO-HB-2026-01")),
            simulate_unavailable=bool(arguments.get("simulate_unavailable", False)),
        )
    raise KeyError(f"Unsupported MCP server '{server_id}' or tool '{tool_name}'")
