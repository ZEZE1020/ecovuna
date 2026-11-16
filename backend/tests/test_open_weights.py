"""Tests for open-weights Ollama model runner, grounding constraints, and fallback (#10)."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.agent import decide
from backend.errors import PolicyViolationError
from backend.ingest import ingest
from backend.main import app
from backend.open_weights import run_open_weights_task


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_model_backed_task_produces_cited_advisory_and_requires_wao_approval() -> None:
    simulated_plan = {
        "action": "stage_advisory",
        "ward": "Homa Bay Central",
        "scenario_override": "flowering maize",
        "required_tools": [
            "fetch_kijanibox_telemetry",
            "fetch_open_meteo_context",
            "fetch_kalro_guidelines",
            "stage_advisory_for_wao_approval",
        ],
        "cited_rule_id": "KALRO-HB-2026-02",
        "rationale": "Flowering maize requires foliar potassium under moisture stress.",
    }
    state = run_open_weights_task(
        ward="Homa Bay Central",
        prompt="Check flowering maize moisture stress",
        model="qwen2.5:7b",
        simulated_model_response=simulated_plan,
    )
    assert state["status"] == "PAUSED_AT_WAO_GATE"
    assert state["advisory"]["dispatched"] is False
    assert state["advisory"]["citations"]["kalro_rule_id"] == "KALRO-HB-2026-02"

    meta = state["model_execution"]
    assert meta["provider"] == "ollama"
    assert meta["model"] == "qwen2.5:7b"
    assert meta["local_only"] is True
    assert meta["status"] == "MODEL_GROUNDED"
    assert meta["fallback_used"] is False
    assert len(meta["tool_calls"]) >= 4

    # Approval is still strictly required
    with pytest.raises(PolicyViolationError):
        decide(state["run_id"], True, "Unauthorized User")

    approved = decide(state["run_id"], True, "Peter Ouma — WAO-003")
    assert approved["status"] == "APPROVED_DISPATCHED"


def test_unavailable_or_ungrounded_model_falls_back_safely_or_refuses() -> None:
    client = TestClient(app)

    # 1. Model unavailable -> deterministic offline fallback works
    fallback_resp = client.post(
        "/api/agent/model-task",
        json={
            "ward": "Homa Bay Central",
            "prompt": "Check germination maize dry spell",
            "model": "gemma2:9b",
            "force_unavailable": True,
        },
    )
    assert fallback_resp.status_code == 200
    fb_data = fallback_resp.json()
    assert fb_data["status"] == "PAUSED_AT_WAO_GATE"
    assert fb_data["model_execution"]["fallback_used"] is True
    assert fb_data["model_execution"]["status"] == "FALLBACK_DETERMINISTIC"
    assert fb_data["advisory"]["citations"]["kalro_rule_id"] == "KALRO-HB-2026-01"

    # 2. Conflicting ward (Suba South) -> produces a safe refusal, never an ungrounded answer
    refusal_resp = client.post(
        "/api/agent/model-task",
        json={
            "ward": "Suba South",
            "prompt": "Give confident advice despite sensor divergence",
            "force_unavailable": True,
        },
    )
    assert refusal_resp.status_code == 200
    ref_data = refusal_resp.json()
    assert ref_data["advisory"] is None
    assert ref_data["status"] == "PAUSED_FOR_CONFLICT_VERIFICATION"
    assert ref_data["model_execution"]["status"] == "SAFE_REFUSAL"
