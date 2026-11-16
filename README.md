# Ecovuna Desk

Ecovuna is an offline-first agent workspace for agricultural extension
officers. It turns scattered farm records, telemetry, weather, agronomy
guidance, and input information into evidence-backed field advice.

## The problem

Extension teams often serve thousands of smallholder farmers with limited
time, unreliable connectivity, and fragmented information. A rainfall change,
sensor alert, pest report, or input shortage can arrive through a different
channel and still needs to become a household-level decision.

The result is slow manual cross-checking, inconsistent advice, and weak
traceability. Farmers need locally relevant guidance; officers need to know
where a recommendation came from and what still needs verification.

## What Ecovuna does

An officer can ask about a ward or start a field review. Ecovuna:

1. Plans the review and gathers available telemetry, weather context, and
   agronomy guidance.
2. Connects evidence to affected plots and households.
3. Explains facts, assumptions, uncertainty, and the proposed next step.
4. Drafts farmer-ready SMS, USSD, and field-visit outputs.
5. Pauses for named officer approval before any consequential action.
6. Records tool calls, evidence, timestamps, and decisions in an audit trail.

The agent does not autonomously message farmers, place input orders, or raise
credit actions.

## Current product

- Native Ecovuna agent chat with inspectable runs.
- MCP registry view for configured servers and tool activity.
- KijaniSpace telemetry normalization with cached offline fallback.
- Citation-backed agronomy and weather context.
- WAO approval gate and audit trail.
- Farmer registry and verified input-partner matching.
- English and Kiswahili draft outputs, with USSD preview.
- Deterministic offline baseline for reliable demonstrations.

The current fixture represents Homa Bay County, Kenya. Farmer records are
synthetic and clearly marked in the data model.

## Run locally

Requirements:

- Python 3.11+
- [uv](https://docs.astral.sh/uv/)
- Node.js 22+
- pnpm 9.15.0, Corepack, or npm
- Docker only if local tracing is needed

From the repository root:

```bash
make setup
make dev
```

Open:

- Web app: <http://localhost:3000>
- API and OpenAPI docs: <http://localhost:8000/docs>
- Jaeger traces: <http://localhost:16686>

`make setup` installs the locked backend and frontend dependencies and seeds
the offline fixture. It uses `uv` for Python and the locked pnpm version for
the frontend. If a local pnpm shim is broken, it falls back to Corepack or
`npm exec pnpm@9.15.0`.

## Validate the project

```bash
make test
```

This runs backend linting, unit tests, and the deterministic evaluation
harness. Run the evaluation directly with:

```bash
uv run --project backend python -m backend.evals.run_evals --trials 3
```

Read the public evaluation results in [`EVALS.md`](./EVALS.md) and the system
shape in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## Reproducible live agent demonstration

Run the complete end-to-end demonstration (success path + provider timeout recovery + conflicting-signal safe failure) from a single command:

```bash
make demo
```

Or output the machine-readable trace, citations, artifacts, and WAO approval record as JSON:

```bash
uv run --project backend python -m backend.demo --json
```

What the demonstration executes and verifies on synthetic Homa Bay fixtures:

1. **Success path (`Homa Bay Central` germination maize dry spell):**
   - Formulates an explicit state-graph plan (`start -> plan -> plan_and_fetch -> citation_self_check -> stage_write_action -> human_approval`).
   - Invokes project-owned (`Ecovuna_Telemetry`), borrowed (`kalro-reference-fetch`), and document/web research (`ecovuna-research-connector`) MCP tools.
   - Extracts source excerpts from `DOC-KALRO-HB-2026` and `KMD-2026-10-14` with SHA-256 checksums.
   - Generates multilingual (`en`, `sw`, `luo`) SMS, USSD, WhatsApp, and voice variants plus versioned `field_brief`, `sms`, `ussd`, and `visit_list` artifacts.
   - Records named Ward Agricultural Officer approval (`Godfrey Ogembo — WAO-KE-043`) and verifies the append-only audit trail.
2. **Timeout recovery path (`simulate_timeout`):**
   - Simulates an upstream telemetry timeout and transitions cleanly through the `recover` node using cached ward readings.
3. **Conflicting-signal safe failure path (`Suba South` lake-shore vs. hilltop divergence):**
   - Detects a 23% sensor moisture spread (`MICROCLIMATE_DIVERGENCE`), lowers confidence to `0.22`, halts staging (`PAUSED_FOR_CONFLICT_VERIFICATION`), and asks a clarifying verification question rather than dispatching an ungrounded advisory.

## Local tracing

Jaeger is a local development aid, not part of the production web service:

```bash
make telemetry-up
```

The API exports traces only when an OTLP endpoint is configured. Cloud
deployments should use the host platform's managed tracing instead of running
Jaeger inside the request-serving container.

## Configuration

Copy `.env.example` to `.env` for local work. Important settings:

```text
LLM_PROVIDER=deterministic_offline
STORAGE_BACKEND=sqlite
NEXT_PUBLIC_API_BASE_URL=http://localhost:8000
FRONTEND_ORIGIN=http://localhost:3000
```

The deterministic provider is the default. Ollama and Gemini integration
metadata exists, but the complete model-backed planner is still under active
development. Do not treat provider metadata as proof that a model was used.

For Cloud Run, `STORAGE_BACKEND=firestore` enables the current Firestore
snapshot bridge. SQLite remains the local and offline store. Create the
Firestore Native database and grant the Cloud Run runtime service account
`roles/datastore.user` before deploying. This bridge is suitable for a demo;
native collections and transactions are required before concurrent pilots.

## Deployment

The release workflow builds two containers and deploys them to Cloud Run:

- `ecovuna-api`
- `ecovuna-web`

Images are published to GitHub Container Registry with release and immutable
commit tags. Production deployment is triggered by a `v*` tag or manual
workflow dispatch. Configure the repository variables documented in
[`.github/workflows/deploy-cloud-run.yml`](./.github/workflows/deploy-cloud-run.yml)
and keep GHCR packages public for the prototype deployment.

The frontend receives the API URL at image build time. A custom domain such as
`ecovuna.vpasi.app` is mapped separately through Cloud Run domain mapping and
DNS.

### Keeping local and deployed UI identical

`make dev` runs the current checkout; Cloud Run runs an immutable release tag.
Always validate the exact commit you intend to deploy, then create the tag
from that commit:

```bash
git status
git pull --ff-only origin main
make test
git tag -a v0.2.0 -m "Ecovuna release v0.2.0"
git push origin main
git push origin v0.2.0
```

The workflow embeds the release tag in the frontend and API. The UI displays
the release, `/api/health` reports it, and deployment fails if the API reports
a different release. Do not edit production containers manually or deploy
`latest`; use a new version tag for every visible change. If a browser shows
an older screen, check the displayed release first, then hard-refresh after
the Cloud Run revision and domain cache have updated.

## Boundaries and next work

This is a working agentic prototype, not a production agricultural authority.
The main gaps are deliberately tracked in GitHub issues:

- real open-weights model execution;
- a complete MCP protocol runtime and borrowed-server call;
- explicit state-graph orchestration and recovery;
- streaming agent events;
- document and web research connectors;
- persistent conversations and generated artifacts;
- stronger uncertainty handling, multilingual delivery, and evaluation.

Contributions should preserve three invariants: evidence must be inspectable,
unsafe actions must stop at a named human approval gate, and offline fallback
must remain usable.

