"""Structured evaluation summary separating deterministic baseline and model-backed runs (#7)."""

from __future__ import annotations

from typing import Any

from .run_evals import run_detailed


def summary(trials: int = 1) -> dict[str, Any]:
    detailed = run_detailed(max(1, min(trials, 5)))
    baseline_cases = detailed["baseline"]["cases"]
    passed = detailed["baseline"]["passed"]
    total = detailed["baseline"]["total"]
    return {
        "trials": trials,
        "passed": passed,
        "total": total,
        "pass_rate": round(passed / total, 2) if total else 0,
        "cases": baseline_cases,
        "baseline": detailed["baseline"],
        "model_backed": detailed["model_backed"],
        "scenario_families_count": detailed["scenario_families_count"],
        "safety_regressions": detailed["safety_regressions"],
        "next_experiment": detailed["next_experiment"],
        "interpretation": {
            "data_grounding": "Measured by telemetry, KALRO citation, document/web verification, and offline fallback cases.",
            "agent_usefulness": "Measured across 9 scenario families: germination drought, flowering drought, floods/pests, missing evidence, approval policy, prices/vouchers, stale data, follow-ups, and conflicting signals.",
            "model_status": "The deterministic planner baseline and open-weights (qwen2.5:7b) runs are reported separately with latency and token/cost distributions.",
        },
    }
