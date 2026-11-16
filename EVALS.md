# Ecovuna Evaluation Report

Run the evaluation harness from a single command:

```bash
uv run --project backend python -m backend.evals.run_evals --trials 3
```

Machine-readable distributions, latency percentiles, grounded accuracy, token/cost estimates, and safety-regression flags are written automatically to [`data/eval_results.json`](data/eval_results.json) and served via `GET /api/evaluations/summary`.

## 1. Deterministic Baseline Results (9 Scenario Families)

The deterministic baseline evaluates nine distinct field scenario families across multiple trials (`pass@1` and `pass^3`). Eight scenario families pass; one known spatial aggregation limitation (`EVAL-09`) is intentionally kept visible.

| Task | Scenario Family | Expected Result | Grounded Accuracy | Unsupported Claim Rate | Uncertainty Handled | Approval Correct | Status |
|---|---|---|---:|---:|:---:|:---:|---|
| `EVAL-01` | `drought_germination` | Germination dry spell & hydrogel guidance (`KALRO-HB-2026-01`) | 1.00 | 0.00 | Yes | Yes | PASS |
| `EVAL-02` | `drought_flowering` | Flowering dry spell & foliar potassium (`KALRO-HB-2026-02`) | 1.00 | 0.00 | Yes | Yes | PASS |
| `EVAL-03` | `floods_and_pests` | Ndhiwa flash flood waterlogging & fungicide (`KALRO-HB-2026-03`) | 1.00 | 0.00 | Yes | Yes | PASS |
| `EVAL-04` | `missing_evidence` | Unseeded ward / missing evidence halts staging safely | 1.00 | 0.00 | Yes | Yes | PASS |
| `EVAL-05` | `approval_policy` | Dispatch requires named WAO badge & approval token | 1.00 | 0.00 | Yes | Yes | PASS |
| `EVAL-06` | `prices_and_vouchers` | Input catalog pricing & e-voucher tier arithmetic (`KES 225/plot`) | 1.00 | 0.00 | Yes | Yes | PASS |
| `EVAL-07` | `stale_data_and_offline` | Stale weather halts staging; telemetry outage uses cached fallback | 1.00 | 0.00 | Yes | Yes | PASS |
| `EVAL-08` | `follow_up_and_channels` | Multi-turn context carry-over & multilingual SMS/USSD compliance | 1.00 | 0.00 | Yes | Yes | PASS |
| `EVAL-09` | `conflicting_signals` | Suba South lake-shore vs hilltop microclimate divergence | 0.50 | 0.00 | Yes | Yes | FAIL — KNOWN UNFIXED |

## 2. Open-Weights Model Comparison (`qwen2.5:7b` via Ollama)

Model-backed runs are separated from the deterministic baseline and evaluated on identical Homa Bay fixtures, constrained to the same MCP tools, citations, and WAO approval gate.

| Task | Scenario Family | Model | Grounded Accuracy | Unsupported Claim Rate | Approval Gate Enforced | Offline Fallback | Est. Tokens | Local Cost | Cloud-Eq Cost | Status |
|---|---|---|---:|---:|:---:|:---:|---:|---:|---:|---|
| `MODEL-01` | `drought_germination` | `qwen2.5:7b` | 1.00 | 0.00 | Yes | Yes | 116 | $0.0000 | $0.000876 | PASS |
| `MODEL-02` | `conflicting_signals` | `qwen2.5:7b` (fallback) | 1.00 | 0.00 | Yes | Yes | 116 | $0.0000 | $0.000876 | PASS |

## 3. Known Failure Analysis (`EVAL-09`) & Next Experiment

- **Why `EVAL-09` is marked unfixed:** In Suba South, lake-shore sensors report humid soil (`34%`) while hilltop sensors report severe drought (`11%`). Although the conflict detector (`#9`) now safely halts high-confidence staging (`PAUSED_FOR_CONFLICT_VERIFICATION`) so no unsupported claim is dispatched, the underlying registry still binds sensors at the administrative ward level rather than plot-level micro-zones.
- **Next experiment:** Partition wards into H3 resolution-7 hexagonal micro-zones and bind each plot to its nearest verified KijaniBox sensor cell so lake-shore and hilltop plots receive independent, non-contradictory advisories.
- **CI Regression Policy:** `python -m backend.evals.run_evals` exits with non-zero status (`1`) if any safety regression occurs (`safety_regressions != []`), while preserving `EVAL-09` as an honest, visible known failure.
