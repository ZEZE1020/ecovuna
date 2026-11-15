"""Optional stdio client seam for the borrowed reference-fetch MCP server."""
from __future__ import annotations

from typing import Any


async def fetch_reference(uri: str) -> dict[str, Any]:
    """Return a reference payload when the MCP client runtime is available.

    Offline deployments use the committed KALRO bulletin instead of failing
    the whole ingestion run when the borrowed server is unavailable.
    """
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError("MCP client dependencies are not installed") from exc
    params = StdioServerParameters(command="python", args=["-m", "mcp_server_fetch"])
    async with stdio_client(params) as (read, write), ClientSession(read, write) as session:
        await session.initialize()
        return {"uri": uri, "tools": [tool.name for tool in (await session.list_tools()).tools]}
