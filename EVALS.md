# Ecovuna Evaluation Report

Run the evaluation harness with:

```bash
uv run --project backend python -m backend.evals.run_evals --trials 3
```

The deterministic fixture suite currently passes eight checks and intentionally
keeps one failure visible.

| Task | Expected result | Status |
|---|---|---|
| EVAL-01 | Germination dry spell and hydrogel guidance | PASS |
| EVAL-02 | Flowering dry spell and foliar guidance | PASS |
| EVAL-03 | Waterlogging drainage and fungicide guidance | PASS |
| EVAL-04 | Unsourced draft rejected before staging | PASS |
| EVAL-05 | Dispatch requires named WAO approval | PASS |
| EVAL-06 | Voucher arithmetic is auditable | PASS |
| EVAL-07 | Telemetry outage uses cached context | PASS |
| EVAL-08 | Localized SMS and USSD output shape | PASS |
| EVAL-09 | Suba South sensor contradiction | FAIL — intentionally unfixed |

EVAL-09 exposes ward-level averaging between humid lake-shore and dry
hilltop readings. The next proposed fix is to partition wards into micro-zones
and bind each plot to its nearest sensor cell. Model-backed comparison,
unsupported-claim rate, uncertainty handling, officer acceptance, latency, and
cost are not yet represented by this deterministic baseline.
