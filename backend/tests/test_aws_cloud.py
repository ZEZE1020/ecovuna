"""Tests for AWS Bedrock AI model runner and AWS S3 agronomy document/artifact vault."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.ingest import ingest
from backend.main import app


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_aws_status_and_bedrock_agent_task_with_fallback() -> None:
    client = TestClient(app)
    status_resp = client.get("/api/aws/status")
    assert status_resp.status_code == 200
    status_data = status_resp.json()
    assert status_data["provider"] == "aws"
    assert "amazon.nova-pro-v1:0" in status_data["supported_models"]
    assert "amazon.nova-micro-v1:0" in status_data["supported_models"]
    assert "ecovuna-ward-state" in status_data["dynamodb_tables"]

    # Automated telemetry ingest webhook for Rachuonyo North
    auto_resp = client.post(
        "/api/v1/automations/ingest-telemetry",
        json={
            "ward": "Rachuonyo North",
            "soil_moisture_pct": 13.4,
            "moisture_delta_pct": -28.0,
        },
    )
    assert auto_resp.status_code == 200
    assert auto_resp.json()["automation_status"] == "TRIGGERED_AND_STAGED_AT_HITL_GATE"
    assert auto_resp.json()["lead_persona"] == "Mama Atieno"

    # FastMCP tool registry at /mcp/tools
    mcp_resp = client.get("/mcp/tools")
    assert mcp_resp.status_code == 200
    tool_names = {t["name"] for t in mcp_resp.json()["tools"]}
    assert {
        "fetch_ward_telemetry",
        "search_agronomy_protocols",
        "draft_localized_advisory",
        "prepare_evoucher_batch",
        "request_wao_approval",
        "dispatch_sms_ussd_campaign",
    }.issubset(tool_names)

    # Zero-JSON UI audit (no <pre>, <code>, or JSX {JSON.stringify(...)})
    from pathlib import Path

    page_code = Path("frontend/src/app/page.tsx").read_text(encoding="utf-8")
    assert "{JSON.stringify" not in page_code
    assert "<pre" not in page_code
    assert "<code" not in page_code

    # Simulated live Bedrock response
    live_resp = client.post(
        "/api/agent/bedrock-task",
        json={
            "ward": "Homa Bay Central",
            "prompt": "Check flowering maize moisture deficit",
            "model_id": "amazon.nova-lite-v1:0",
            "simulated_bedrock_response": {
                "action": "stage_advisory",
                "ward": "Homa Bay Central",
                "scenario_override": "flowering maize",
                "cited_rule_id": "KALRO-HB-2026-02",
                "rationale": "Apply foliar potassium under flowering moisture stress.",
            },
        },
    )
    assert live_resp.status_code == 200
    live_data = live_resp.json()
    assert live_data["status"] == "PAUSED_AT_WAO_GATE"
    assert live_data["bedrock_execution"]["status"] == "BEDROCK_LIVE_GROUNDED"
    assert live_data["bedrock_execution"]["model_id"] == "amazon.nova-lite-v1:0"
    assert live_data["advisory"]["citations"]["kalro_rule_id"] == "KALRO-HB-2026-02"

    # Offline fallback path
    fb_resp = client.post(
        "/api/agent/bedrock-task",
        json={
            "ward": "Homa Bay Central",
            "prompt": "Check germination maize dry spell",
            "force_fallback": True,
        },
    )
    assert fb_resp.status_code == 200
    assert fb_resp.json()["bedrock_execution"]["fallback_used"] is True
    assert fb_resp.json()["bedrock_execution"]["status"] == "FALLBACK_DETERMINISTIC"


def test_s3_document_upload_indexing_and_artifact_sync() -> None:
    client = TestClient(app)
    upload_resp = client.post(
        "/api/documents/upload",
        json={
            "title": "Homa Bay County Short Rains Bulletin 2026",
            "publisher": "KALRO Homa Bay Research Centre",
            "ward": "Homa Bay Central",
            "filename": "homabay_short_rains_2026.md",
            "content": (
                "Official KALRO-HB-2026-01 & KMD-2026-10-14 bulletin: "
                "Hold nitrogen top-dressing and apply root-zone hydrogel at 5 kg/acre."
            ),
            "force_local": True,
        },
    )
    assert upload_resp.status_code == 200
    doc = upload_resp.json()
    assert doc["document_id"].startswith("DOC-S3-")
    assert doc["s3_uri"].startswith("s3://")
    assert "KALRO-HB-2026-01" in doc["citation_tokens"]
    assert doc["research_citation"]["citation_matched"] is True

    # Verify document appears in /api/documents and in subsequent agent runs
    list_resp = client.get("/api/documents", params={"ward": "Homa Bay Central"})
    assert list_resp.status_code == 200
    doc_ids = {d["document_id"] for d in list_resp.json()["documents"]}
    assert doc["document_id"] in doc_ids

    # Run triage and sync generated artifact to S3
    triage_resp = client.post("/api/agent/triage", json={"ward": "Homa Bay Central"})
    assert triage_resp.status_code == 200
    run_data = triage_resp.json()
    sources = run_data["evidence"]["research_sources"]
    assert any(s["source_id"] == doc["document_id"] for s in sources)

    first_artifact_id = run_data["artifacts"][0]["artifact_id"]
    sync_resp = client.post(
        f"/api/agent/artifacts/{first_artifact_id}/sync-s3",
        json={"force_local": True},
    )
    assert sync_resp.status_code == 200
    assert sync_resp.json()["s3_uri"].startswith("s3://")
