# Ecovuna Desk Architecture

Ecovuna is an offline-first agricultural extension workspace for Ward
Agricultural Officers. The current fixture models Homa Bay County and uses
synthetic KIAMIS-shaped records, cached telemetry, agronomy bulletins, and
verified input partners.

## Agent flow

1. Select a ward and scenario.
2. Fetch KijaniSpace telemetry, weather context, and agronomy guidance.
3. Check citations and derive a localized advisory.
4. Stage SMS, USSD, and voucher outputs.
5. Pause at the named WAO approval gate.

The agent never sends a farmer message or places an order autonomously. Tool
inputs, outputs, timestamps, and decisions are written to the audit trail.

## Tools and servers

`Ecovuna_Telemetry` contains the project-owned tool functions for telemetry,
weather context, agronomy guidance, and advisory staging. `mcp-server-fetch`
is the borrowed reference-fetch server declared in `mcp.json`. The complete
protocol runtime and live borrowed-server recommendation path are tracked as
follow-up work; the current deterministic path uses committed local guidance.

The current deterministic planner is the reliable offline baseline. Ollama and
Gemini metadata are supported, but a full model-backed planner remains an
explicit follow-up.

## Runtime boundary

SQLite is used for local development and offline fixtures. Cloud Run can use
Firestore through `STORAGE_BACKEND=firestore`; this is currently a snapshot
bridge and should be replaced by native collections before concurrent pilots.
The Next.js console displays the plan, evidence, tool provenance, and approval
state rather than hiding them behind a chat response.
