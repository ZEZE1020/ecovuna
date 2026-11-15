"""Structured evaluation summary for the operator console."""
from __future__ import annotations

from typing import Any

from .run_evals import run


def summary(trials: int = 1) -> dict[str, Any]:
    results = run(max(1, min(trials, 5)))
    by_key: dict[str, list[bool]] = {}
    descriptions: dict[str, str] = {}
    for result in results:
        by_key.setdefault(result.key, []).append(result.passed)
        descriptions[result.key] = result.description
    cases = [
        {
            "key": key,
            "description": descriptions[key],
            "pass_at_one": values[0],
            "consistent": all(values),
        }
        for key, values in by_key.items()
    ]
    passed = sum(case["pass_at_one"] for case in cases)
    return {
        "trials": trials,
        "passed": passed,
        "total": len(cases),
        "pass_rate": round(passed / len(cases), 2) if cases else 0,
        "cases": cases,
        "interpretation": {
            "data_grounding": "Measured by telemetry, KALRO citation, and offline fallback cases.",
            "agent_usefulness": "Measured by scenario routing, advisory staging, and approval safety cases.",
            "model_status": "The deterministic planner is the active evaluator baseline; no LLM is used in this run.",
        },
    }
