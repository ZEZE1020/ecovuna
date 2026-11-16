"""Tests for multilingual farmer-ready agent responses across channels (#6)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.agent import decide, triage
from backend.ingest import ingest
from backend.main import app
from backend.multilingual import CHANNEL_MAX_LENGTHS, generate_advisory_variants


def setup_module() -> None:
    ingest(offline_fallback=True)


def test_canonical_advisory_produces_deterministic_en_sw_luo_variants() -> None:
    state = triage("Homa Bay Central")
    advisory = state["advisory"]
    assert advisory is not None
    variants = advisory["output_variants"]
    assert len(variants) == 12  # 3 languages x 4 channels

    by_pair = {(v["language"], v["channel"]): v for v in variants}
    for lang in ("en", "sw", "luo"):
        for channel in ("sms", "ussd", "whatsapp", "voice"):
            v = by_pair[(lang, channel)]
            assert v["status"] == "READY"
            assert v["within_length_limit"] is True
            assert v["character_length"] <= CHANNEL_MAX_LENGTHS[channel]
            assert v["has_required_warning"] is True
            assert v["citations"]["kalro_rule_id"] == "KALRO-HB-2026-01"
            assert v["dispatched"] is False
            assert v["approved_by_wao"] is None
            # Local units and crop names preserved
            assert ("WH-505" in v["text"]) or ("W H" in v["text"])
            assert "EV-HYDRO-2026" in v["text"]


def test_no_channel_dispatched_before_named_wao_approval_and_updates_after() -> None:
    client = TestClient(app)
    run = triage("Homa Bay Central", "flowering maize")
    run_id = run["run_id"]

    pre_resp = client.get(f"/api/agent/runs/{run_id}/variants")
    assert pre_resp.status_code == 200
    pre_payload = pre_resp.json()
    assert pre_payload["approval_status"] == "PENDING_WAO_APPROVAL"
    assert pre_payload["approved_by_wao"] is None
    assert all(v["dispatched"] is False for v in pre_payload["variants"])

    # Named WAO approves the run
    officer = "Sarah Ochieng — WAO-001"
    decide(run_id, True, officer, "Verified flowering maize foliar K")

    post_resp = client.get(f"/api/agent/runs/{run_id}/variants")
    assert post_resp.status_code == 200
    post_payload = post_resp.json()
    assert post_payload["approval_status"] == "APPROVED_DISPATCHED"
    assert post_payload["approved_by_wao"] == officer
    assert all(v["dispatched"] is True for v in post_payload["variants"])
    assert all(
        v["approved_by_wao"] == officer for v in post_payload["variants"]
    )


def test_unreviewed_language_or_rule_marks_explicit_unavailable_status() -> None:
    advisory = {
        "advisory_id": "ADV-TEST-UNAVAIL",
        "ward": "Homa Bay Central",
        "evoucher_package_code": "EV-HYDRO-2026",
        "evoucher_total_kes": 1800.0,
        "per_farmer_kes": 225.0,
        "status": "PENDING_WAO_APPROVAL",
        "citations": {"kalro_rule_id": "KALRO-HB-2026-01"},
    }
    variants = generate_advisory_variants(
        advisory,
        requested_languages=("en", "fr"),
        requested_channels=("sms",),
    )
    by_lang = {v["language"]: v for v in variants}
    assert by_lang["en"]["status"] == "READY"
    assert by_lang["fr"]["status"] == "UNAVAILABLE_REVIEW_REQUIRED"
    assert by_lang["fr"]["dispatched"] is False
    assert "No human-reviewed translation template" in by_lang["fr"]["fallback_reason"]
