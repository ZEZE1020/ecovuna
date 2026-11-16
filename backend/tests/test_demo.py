"""Tests for the reproducible live agent demonstration (#19)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.demo import run_reproducible_demo
from backend.main import app


def test_reproducible_demo_covers_success_path_recovery_and_safe_failure() -> None:
    report = run_reproducible_demo()
    assert "Synthetic Homa Bay" in report["provenance"]

    # 1. Success path traces recommendation to evidence and named WAO decision
    sp = report["success_path"]
    assert sp["plan"]["steps"]
    assert len(sp["mcp_calls"]) >= 5
    assert len(sp["source_excerpts"]) >= 2
    assert sp["citations"]["kalro_rule_id"] == "KALRO-HB-2026-01"
    assert sp["multilingual_variants_count"] == 12
    assert len(sp["generated_artifacts"]) == 4
    assert sp["wao_decision"]["status"] == "APPROVED_DISPATCHED"
    assert sp["wao_decision"]["wao_officer_name"] == "Godfrey Ogembo — WAO-KE-043"
    assert len(sp["audit_trail"]) >= 6

    # 2. Timeout recovery path
    tr = report["recovery_and_failure_paths"]["timeout_recovery"]
    assert tr["recovered_from_cache"] is True
    assert tr["status"] == "PAUSED_AT_WAO_GATE"

    # 3. Conflicting-signal safe failure path
    cf = report["recovery_and_failure_paths"]["conflicting_signal_safe_failure"]
    assert cf["status"] == "PAUSED_FOR_CONFLICT_VERIFICATION"
    assert cf["advisory_staged"] is False
    assert cf["confidence"] < 0.5
    assert len(cf["conflicts"]) >= 1
    assert cf["clarification_question"]

    # API endpoint parity
    client = TestClient(app)
    resp = client.post("/api/agent/demo")
    assert resp.status_code == 200
    assert resp.json()["success_path"]["wao_decision"]["status"] == "APPROVED_DISPATCHED"
