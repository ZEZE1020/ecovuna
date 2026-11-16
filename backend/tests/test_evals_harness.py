"""Tests for the field scenario evaluation harness and baseline/model separation (#7)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.evals.run_evals import EVAL_RESULTS_PATH, run_detailed
from backend.main import app


def test_eval_harness_executes_nine_families_separates_model_and_preserves_known_failure() -> None:
    report = run_detailed(trials=2)
    assert report["scenario_families_count"] >= 8
    assert report["safety_regressions"] == []

    # Baseline and model results are separated
    assert "baseline" in report
    assert "model_backed" in report
    assert report["baseline"]["passed"] == 8
    assert report["baseline"]["total"] == 9
    assert report["baseline"]["known_failures"] == ["EVAL-09"]

    assert report["model_backed"]["passed"] == 2
    assert report["model_backed"]["total"] == 2

    # Machine-readable file written
    assert EVAL_RESULTS_PATH.exists()

    # Check latency distributions and metrics exist on each case
    for case in report["baseline"]["cases"]:
        assert "latency_distribution_ms" in case
        assert "grounded_accuracy" in case
        assert "unsupported_claim_rate" in case

    client = TestClient(app)
    resp = client.get("/api/evaluations/summary?trials=2")
    assert resp.status_code == 200
    summary_data = resp.json()
    assert summary_data["passed"] == 8
    assert summary_data["total"] == 9
    assert "model_backed" in summary_data
    assert summary_data["safety_regressions"] == []
