"""Tests for MCP server runtime discovery, tool invocation, and borrowed-server call (#11)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.agent import triage
from backend.db import connect
from backend.ingest import ingest
from backend.main import app
from backend.mcp_server import build_fastmcp_server


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_stranger_can_list_and_invoke_project_tools_through_mcp() -> None:
    server = build_fastmcp_server()
    assert server is not None

    client = TestClient(app)
    tools_resp = client.get("/api/mcp/tools")
    assert tools_resp.status_code == 200
    tools = tools_resp.json()["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert {
        "fetch_kijanibox_telemetry",
        "fetch_open_meteo_context",
        "fetch_kalro_guidelines",
        "stage_advisory_for_wao_approval",
        "fetch",
    }.issubset(tool_names)

    for tool in tools:
        assert "description" in tool
        assert "inputSchema" in tool

    call_resp = client.post(
        "/api/mcp/call",
        json={
            "server_id": "ecovuna-telemetry",
            "tool_name": "fetch_kalro_guidelines",
            "arguments": {
                "crop": "Maize WH-505",
                "growth_stage": "Flowering_Tasseling_41_65d",
            },
            "run_id": "RUN-MCP-TEST-01",
        },
    )
    assert call_resp.status_code == 200
    assert call_resp.json()["output"]["rule_id"] == "KALRO-HB-2026-02"


def test_end_to_end_recommendation_uses_project_owned_and_borrowed_servers() -> None:
    state = triage("Homa Bay Central")
    assert state["status"] == "PAUSED_AT_WAO_GATE"
    servers_in_trace = {entry["server"] for entry in state["execution_trace"]}
    assert "Ecovuna_Telemetry" in servers_in_trace
    assert "kalro-reference-fetch" in servers_in_trace

    with connect() as db:
        borrowed_audit = db.execute(
            "SELECT * FROM mcp_audit_log WHERE run_id = ? AND server = 'kalro-reference-fetch'",
            (state["run_id"],),
        ).fetchone()
    assert borrowed_audit is not None
    assert "KALRO-HB-2026-01" in borrowed_audit["output_json"]


def test_registry_endpoint_uses_runtime_discovery_and_offline_fallback_works() -> None:
    client = TestClient(app)
    registry_resp = client.get("/api/mcp/registry")
    assert registry_resp.status_code == 200
    payload = registry_resp.json()
    servers = {item["id"]: item for item in payload["servers"]}
    assert "ecovuna-telemetry" in servers
    assert "kalro-reference-fetch" in servers
    assert "capabilities" in servers["ecovuna-telemetry"]
    assert "tool_schemas" in servers["ecovuna-telemetry"]

    # Simulate borrowed server unavailable -> offline mode remains usable
    offline_state = triage("Homa Bay Central", "borrowed_offline")
    assert offline_state["status"] == "PAUSED_AT_WAO_GATE"
    ref = offline_state["evidence"]["borrowed_reference"]
    assert ref["status"] == "offline_fallback"
    assert "KALRO-HB-2026-01" in ref["matched_excerpt"]
