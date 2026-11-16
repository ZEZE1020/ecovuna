"""MCP server registry, runtime discovery, and tool invocation router (#11)."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from pydantic import BaseModel, Field

from ..contracts import McpRegistryResponse
from ..errors import EcovunaError, InvalidRequestError, NotFoundError
from ..mcp_client import call_mcp_tool, discover_mcp_runtime
from ..mcp_server import list_registered_mcp_tools

router = APIRouter(tags=["mcp"])


class McpToolCallRequest(BaseModel):
    server_id: str = Field(default="ecovuna-telemetry", min_length=1)
    tool_name: str = Field(min_length=1)
    arguments: dict[str, Any] = Field(default_factory=dict)
    run_id: str | None = None


@router.get("/api/mcp/registry", response_model=McpRegistryResponse)
def mcp_registry() -> McpRegistryResponse:
    """Expose runtime-discovered MCP servers, capabilities, and recent tool activity."""
    return McpRegistryResponse.model_validate(discover_mcp_runtime())


@router.get("/api/mcp/tools")
def mcp_tools() -> dict[str, Any]:
    """List registered MCP tools, descriptions, and JSON input schemas."""
    runtime = discover_mcp_runtime()
    all_schemas: list[dict[str, Any]] = []
    for server in runtime["servers"]:
        all_schemas.extend(server.get("tool_schemas", []))
    return {
        "tools": all_schemas or list_registered_mcp_tools(),
    }


@router.post("/api/mcp/call")
def mcp_call(request: McpToolCallRequest) -> dict[str, Any]:
    """Invoke a project-owned or borrowed MCP tool through the runtime boundary."""
    try:
        output = call_mcp_tool(
            request.server_id,
            request.tool_name,
            request.arguments,
            run_id=request.run_id,
        )
    except EcovunaError:
        raise
    except KeyError as exc:
        raise NotFoundError(str(exc), error_code="MCP_TOOL_NOT_FOUND") from exc
    except (ValueError, TypeError) as exc:
        raise InvalidRequestError(str(exc), error_code="MCP_INVALID_ARGUMENTS") from exc
    return {
        "server_id": request.server_id,
        "tool_name": request.tool_name,
        "output": output,
    }
