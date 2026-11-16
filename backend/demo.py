"""Reproducible live agent demonstration covering success and safe-failure recovery paths (#19)."""

from __future__ import annotations

import argparse
import json
from typing import Any

from .agent import decide, triage
from .artifacts_repository import repository as artifact_repo
from .conversations import run_conversation_turn
from .db import connect
from .ingest import ingest


def run_reproducible_demo() -> dict[str, Any]:
    """Execute the complete reproducible Ecovuna agent demonstration from synthetic Homa Bay fixtures."""
    ingest(offline_fallback=True)

    # Path A: Focused Ward Question -> Multi-Source Evidence -> Farmer-Ready Artifacts -> WAO Approval
    session_id = "SES-DEMO-LIVE-01"
    turn = run_conversation_turn(
        message="What should I advise germination maize farmers in Homa Bay Central facing a sudden dry spell?",
        ward="Homa Bay Central",
        session_id=session_id,
    )
    success_run = turn["run"]
    run_id = success_run["run_id"]
    advisory = success_run["advisory"]

    mcp_calls = [
        {
            "node": entry["node"],
            "server": entry["server"],
            "tool": entry["tool"],
            "transition": entry.get("transition"),
        }
        for entry in success_run["execution_trace"]
    ]
    research_sources = [
        {
            "source_type": src["source_type"],
            "source_id": src["source_id"],
            "title": src["title"],
            "publisher": src["publisher"],
            "excerpt": src["excerpt"],
            "quality_status": src["quality_status"],
        }
        for src in (success_run.get("evidence") or {}).get("research_sources", [])
    ]

    # Named Ward Agricultural Officer approves the staged advisory
    officer_identity = "Godfrey Ogembo — WAO-KE-043"
    approval_decision = decide(
        run_id,
        True,
        officer_identity,
        "Verified soil moisture deficit (14.2%), KALRO-HB-2026-01, and KMD-2026-10-14.",
    )
    approved_artifacts = artifact_repo.list_artifacts(run_id=run_id, latest_only=True)

    with connect() as db:
        audit_rows = [
            dict(row)
            for row in db.execute(
                "SELECT timestamp, server, tool_name, action FROM mcp_audit_log WHERE run_id = ? ORDER BY id ASC",
                (run_id,),
            )
        ]

    # Path B: Timeout Recovery + Conflicting Signal Safe Failure
    timeout_recovered_run = triage("Homa Bay Central", "simulate_timeout")
    conflict_safe_failure_run = triage("Suba South", "microclimate divergence")

    return {
        "demo_version": "1.0",
        "provenance": "Synthetic Homa Bay County fixture (offline-reproducible)",
        "success_path": {
            "session_id": session_id,
            "run_id": run_id,
            "question": turn["question"],
            "plan": success_run["plan"],
            "mcp_calls": mcp_calls,
            "source_excerpts": research_sources,
            "uncertainty": turn["sections"]["uncertainty"],
            "recommendation": turn["sections"]["recommendation"],
            "citations": advisory["citations"],
            "multilingual_variants_count": len(advisory.get("output_variants", [])),
            "generated_artifacts": [
                {
                    "artifact_id": a["artifact_id"],
                    "artifact_type": a["artifact_type"],
                    "version": a["version"],
                    "approval_status": a["approval_status"],
                    "approved_by_wao": a["approved_by_wao"],
                    "dispatched": a["dispatched"],
                }
                for a in approved_artifacts
            ],
            "wao_decision": {
                "status": approval_decision["status"],
                "wao_officer_name": approval_decision["wao_officer_name"],
                "advisory_id": approval_decision["advisory_id"],
                "dispatched": approval_decision["dispatched"],
            },
            "audit_trail": audit_rows,
        },
        "recovery_and_failure_paths": {
            "timeout_recovery": {
                "run_id": timeout_recovered_run["run_id"],
                "ward": timeout_recovered_run["ward"],
                "recovered_from_cache": timeout_recovered_run["evidence"]["recovered"],
                "status": timeout_recovered_run["status"],
                "transitions": timeout_recovered_run["transitions"],
            },
            "conflicting_signal_safe_failure": {
                "run_id": conflict_safe_failure_run["run_id"],
                "ward": conflict_safe_failure_run["ward"],
                "status": conflict_safe_failure_run["status"],
                "advisory_staged": conflict_safe_failure_run.get("advisory") is not None,
                "confidence": conflict_safe_failure_run["confidence"],
                "conflicts": conflict_safe_failure_run["conflicts"],
                "clarification_question": conflict_safe_failure_run["safety_decision"][
                    "clarification_question"
                ],
                "recommended_verification": conflict_safe_failure_run["safety_decision"][
                    "recommended_verification"
                ],
            },
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the reproducible Ecovuna live agent demonstration."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Output the full machine-readable demonstration report as JSON.",
    )
    args = parser.parse_args()
    report = run_reproducible_demo()
    if args.json:
        print(json.dumps(report, indent=2))
        return

    sp = report["success_path"]
    fp = report["recovery_and_failure_paths"]
    print("=== ECOVUNA REPRODUCIBLE LIVE AGENT DEMONSTRATION ===")
    print(f"Provenance: {report['provenance']}")
    print(f"\n[1] SUCCESS PATH (Session {sp['session_id']} / Run {sp['run_id']})")
    print(f"  Question:       {sp['question']}")
    print(f"  Plan Steps:     {', '.join(sp['plan']['steps'])}")
    print(f"  MCP Calls:      {len(sp['mcp_calls'])} calls across Ecovuna_Telemetry, kalro-reference-fetch, and ecovuna-research-connector")
    for src in sp["source_excerpts"]:
        print(f"  Source Excerpt: [{src['source_type']}] {src['title']} -> \"{src['excerpt']}\"")
    print(f"  Uncertainty:    {sp['uncertainty']}")
    print(f"  Recommendation: {sp['recommendation']}")
    print(f"  Citations:      {json.dumps(sp['citations'])}")
    print(
        f"  WAO Approval:   {sp['wao_decision']['status']} by {sp['wao_decision']['wao_officer_name']} "
        f"(Advisory {sp['wao_decision']['advisory_id']})"
    )
    print(f"  Audit Trail:    {len(sp['audit_trail'])} append-only records verified")

    tr = fp["timeout_recovery"]
    print(f"\n[2] TIMEOUT RECOVERY PATH (Run {tr['run_id']})")
    print(
        f"  Simulated provider timeout -> recovered={tr['recovered_from_cache']} -> status={tr['status']}"
    )

    cf = fp["conflicting_signal_safe_failure"]
    print(f"\n[3] SAFE FAILURE PATH — CONFLICTING SIGNALS (Run {cf['run_id']} in {cf['ward']})")
    print(
        f"  Status:         {cf['status']} (advisory_staged={cf['advisory_staged']}, confidence={cf['confidence']})"
    )
    first_conflict = cf["conflicts"][0]
    conflict_summary = (
        first_conflict.get("detail")
        or first_conflict.get("summary")
        or first_conflict.get("recommended_verification")
        or ""
    )
    print(f"  Conflict:       {first_conflict['code']} — {conflict_summary}")
    print(f"  Clarification:  {cf['clarification_question']}")
    print(f"  Verification:   {cf['recommended_verification']}")


if __name__ == "__main__":
    main()
