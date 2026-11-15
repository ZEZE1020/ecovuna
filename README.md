# Ecovuna Desk

Offline-first climate-smart advisory workspace for Ward Agricultural Officers in
Homa Bay County, Kenya. Ecovuna turns cached weather and plot telemetry into
localized, citation-backed advisories and **always pauses for named WAO approval
before dispatch**.

## Run it

Run commands from the repository root (the directory containing this README).
If you are currently in `backend/`, `make dev` and the other common targets
forward to the root Makefile automatically.

Requires Python 3.11+, [uv](https://docs.astral.sh/uv/), Node.js, and pnpm.
The first command creates a local `.venv`, installs locked backend/frontend
dependencies, and seeds deterministic offline data:

```bash
make setup
```

Start both the FastAPI backend and Next.js frontend with:

```bash
make dev
```

Then open:

- Frontend: `http://localhost:3000`
- API documentation: `http://localhost:8000/docs`
- Local-only lifecycle, architecture, evaluation, and roadmap notes are kept
  under `.private/` and are intentionally excluded from version control.

### OpenTelemetry

The API is instrumented with OpenTelemetry's FastAPI integration. HTTP server
spans are created automatically, including route, status, and exception
attributes. Start the local Jaeger dashboard and OTLP collector with:

```bash
make telemetry-up
```

Then use the Docker stack:

```bash
docker compose up --build
```

Open `http://localhost:16686`, select the `ecovuna-api` service, and make
requests through `http://localhost:3000` or `http://localhost:8000/docs`.
The Ecovuna header displays `OTEL ON` when export is active.

The local `make dev` workflow starts Jaeger automatically and defaults to the
same local collector. To override the endpoint, set:

```bash
OTEL_SERVICE_NAME=ecovuna-api
OTEL_DEPLOYMENT_ENVIRONMENT=local
OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=http://localhost:4318/v1/traces
make dev
```

The endpoint can also be supplied as `OTEL_EXPORTER_OTLP_ENDPOINT`; Ecovuna
will append `/v1/traces` when needed. `/api/health` reports whether telemetry
export is enabled and which exporter is active. The application does not send
telemetry to a third party unless an endpoint is explicitly configured.

Useful commands:

```bash
make ingest  # refresh the local SQLite database
make telemetry-up  # start Jaeger at http://localhost:16686
make test    # lint, unit tests, and the nine evaluation scenarios
make clean   # remove only the local Python virtual environment
```

### Package managers

Python dependencies are declared in [`backend/pyproject.toml`](./backend/pyproject.toml)
and locked in `backend/uv.lock`. Use `uv sync --project backend` and `uv run
--project backend ...`; do not install backend packages with global `pip`.
Frontend dependencies are managed with pnpm and `frontend/pnpm-lock.yaml`.
Use `pnpm --dir frontend install --frozen-lockfile` and `pnpm --dir frontend
build`. `make setup` validates that pnpm is executable; if a stale pnpm shim is
present, it falls back to Corepack and then `npm exec pnpm@9.15.0` without
changing the project lockfile. `npx` is not a package manager, so it is
intentionally not used for project installation.

### Deployment

Production deployment runs from
[`.github/workflows/deploy-cloud-run.yml`](./.github/workflows/deploy-cloud-run.yml)
after a successful push to `main`, a version tag such as `v0.1.0`, or through
the workflow's manual `workflow_dispatch` trigger. It builds and deploys
independent `ecovuna-api` and `ecovuna-web` Cloud Run services. Authentication
uses GitHub Actions OIDC through Google Workload Identity Federation; no
service-account key is stored in the repository.

Configure these repository variables before enabling deployment:

- `GCP_PROJECT_ID` (recommended prototype project: `alwaays-on-itj`)
- `GCP_REGION` (recommended: `europe-west1`)
- `GCP_WIF_PROVIDER` (full Workload Identity Provider resource name)
- `GCP_DEPLOY_SERVICE_ACCOUNT` (service-account email)

Create the GitHub OIDC provider with an attribute condition. Google Cloud
rejects an unrestricted provider because the condition must reference a claim
from the GitHub token:

```bash
gcloud iam workload-identity-pools providers create-oidc github \
  --project="$GCP_PROJECT_ID" \
  --location=global \
  --workload-identity-pool=github-actions \
  --display-name="GitHub Actions" \
  --issuer-uri="https://token.actions.githubusercontent.com" \
  --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" \
  --attribute-condition="assertion.repository == 'ZEZE1020/ecovuna' && (assertion.ref == 'refs/heads/main' || assertion.ref.startsWith('refs/tags/v'))"
```

If the failed command did not create a provider, rerun it with the same
provider ID after adding `--attribute-condition`; if a provider already
exists, update it instead:

```bash
gcloud iam workload-identity-pools providers update-oidc github \
  --project="$GCP_PROJECT_ID" \
  --location=global \
  --workload-identity-pool=github-actions \
  --attribute-condition="assertion.repository == 'ZEZE1020/ecovuna' && (assertion.ref == 'refs/heads/main' || assertion.ref.startsWith('refs/tags/v'))"
```

Enable Cloud Run and Cloud Build APIs in the project. The deploy service
account needs permission to deploy Cloud Run services, including permission to
act as the runtime service account selected by Cloud Run. The GitHub Actions
identity should be restricted to this repository and its `main` branch.

Images are published to the repository's GitHub Container Registry packages:
`ghcr.io/zeze1020/ecovuna-api` and `ghcr.io/zeze1020/ecovuna-web`. Make both
packages public before the first Cloud Run deployment, because Cloud Run pulls
these external images without a registry credential. Each build receives both
a release tag (`v0.1.0`) or branch tag (`sha-...`) and an immutable commit tag
for rollback.

The workflow first deploys the API, then embeds its generated Cloud Run URL in
the frontend image as `NEXT_PUBLIC_API_BASE_URL`. It keeps both services at
zero minimum instances and caps them at two instances to control prototype
costs. The API is intentionally configured with
`LLM_PROVIDER=deterministic_offline` for a predictable public demo; live
KijaniSpace credentials should be supplied through managed Cloud Run secrets
before enabling live enrichment.

### Commit and release sequence

Keep the history reviewable and deployable in small slices:

1. `feat(backend): add grounded extension service` — backend, migrations/data
   fixtures, tests, and backend container.
2. `feat(frontend): add agentic operator workspace` — frontend, daisyUI theme,
   lockfile, and frontend container.
3. `ci(deploy): publish release images to GHCR` — workflows, deployment
   configuration, and documentation.
4. `git tag -a v0.1.0 -m "Ecovuna first deployable release"` and push the tag.

The tag starts the same deployment workflow and makes the release images
discoverable in GHCR. Use a new tag for every deployable change (`v0.1.1` for
fixes, `v0.2.0` for compatible features, and `v1.0.0` when the pilot contract
is stable). Improvement ideas should become GitHub issues after the first
release, linked to the release or deployment revision they improve. Do not
backdate commits; preserve the real authoring and review timeline.

### `ecovuna.vpasi.app` DNS

The workflow prints the generated Cloud Run service URLs but does not create a
custom domain mapping. In Cloud Run, map `ecovuna.vpasi.app` to `ecovuna-web`
in `europe-west1`, then add the DNS record Cloud Run provides in Cloudflare.
Keep Cloudflare proxying disabled until certificate provisioning succeeds,
then verify:

```bash
curl --fail https://ecovuna.vpasi.app
```

The API service remains directly reachable at the Cloud Run URL printed by the
workflow, and the frontend uses that URL for its API calls. For a stricter
production posture, route API traffic through a custom API domain or gateway
and restrict direct unauthenticated access after the public demo.

This deployment is suitable for a challenge demo, not durable production
operations. The backend currently seeds and writes SQLite inside the container;
Cloud Run's filesystem is ephemeral and revisions can scale to zero or be
replaced. Move audit data, approvals, and farmer records to Firestore, Cloud
SQL, or another managed store before real user pilots.

Pull requests run the full backend, evaluation, and frontend validation job in
[`.github/workflows/ci-cd.yml`](./.github/workflows/ci-cd.yml), but do not
deploy.

### Extension operations

The workspace is not limited to a single advisory or county. Its extension
operations model supports:

- verified partners such as agrovets, seed hubs, and fertiliser providers;
- input catalogs with crop, soil-profile, climate-zone, price, and stock data;
- explainable plot-to-provider recommendations using proximity, crop, soil
  moisture, agroclimatic zone, service radius, and stock;
- officer-confirmed farm assignments recorded in the audit-ready database.

The **Partner matching** workspace exposes this flow through the API. The
current bundled dataset is still a Homa Bay offline fixture; connecting a
county-wide registry, soil laboratory feed, partner stock feed, or GIS service
will populate the same tables and endpoints without changing the workflow.

### Agentic AI foundation

The UI and API expose a shared `Ecovuna Agentic Extension Foundation` contract.
It makes the active provider and model visible to operators while preserving
`deterministic_offline` as the default for low-connectivity environments. Set
`LLM_PROVIDER=ollama` for a local model or `LLM_PROVIDER=gemini` for a managed
provider; grounded tool outputs, citations, audit logging, and named WAO
approval remain required in every mode. The API contract is available at
`GET /api/agent/foundation` and is also included in `GET /api/health`.

The frontend uses daisyUI components with an Ecovuna theme. This keeps the
console accessible and consistent as it expands from the Kenyan fixture to
county and Africa-wide deployments, without implying that an AI model can
replace local officers, agronomists, public agencies, or community knowledge.

The pilot home experience is designed around the WAO's daily workflow:
**Today’s priorities**, **Ask Ecovuna**, and a field briefing appear before
technical telemetry and registry tables. Plain-language prompts launch the same
grounded triage workflow as the detailed controls, so convenience does not
bypass evidence, audit logging, or named officer approval. Channel badges make
the future delivery model explicit: one approved advisory can be adapted for
mobile web, SMS, USSD, WhatsApp, and voice.

The agent workspace follows AAIF-aligned interaction principles: the agent
shows its operating contract, plan, tool/server provenance, returned evidence,
and current pause point instead of presenting an unexplained answer. Operators
can inspect the evidence before choosing **approve**, **flag for field visit**,
or stopping the run. This UI pattern is intentionally compatible with the
open-protocol direction of the Agentic AI Foundation, including MCP-based tool
interoperability and inspectable agent behavior; it does not depend on a
single model vendor.

### Measuring KijaniSpace and model usefulness

The overview visualizes two different questions instead of hiding them behind
one AI score:

- **Data usefulness:** the telemetry card shows live KijaniSpace versus cached
  readings, timestamps, sensor provenance, forecast model run, soil moisture,
  rainfall, and vegetation indicators.
- **Agent usefulness:** the quality strip reads `GET /api/evaluations/summary`
  and shows the deterministic baseline's scenario, grounding, fallback, and
  approval checks. The current fixture baseline is expected to show 8/9 checks:
  the ninth is the intentionally unfixed Suba South microclimate case.

Run a repeatable evaluation with:

```bash
uv run --project backend python -m backend.evals.run_evals --trials 3
```

KijaniSpace normalization is tested independently in
[`backend/tests/test_kijanispace.py`](./backend/tests/test_kijanispace.py).
This matters because a live KijaniSpace reading can improve the evidence while
the current deterministic planner remains unchanged. To test an LLM's actual
usefulness, add it behind the same tool-and-approval contract, then compare it
against this baseline on identical scenarios using grounded accuracy,
unsupported-claim rate, officer acceptance, latency, cost, and offline fallback
success. Changing `LLM_PROVIDER` alone currently changes the reported
foundation metadata; it does not yet change triage decisions.

Network sources are optional and ingestion falls back to deterministic fixture
telemetry. If `uv` is not installed, install it from the official
[installation guide](https://docs.astral.sh/uv/getting-started/installation/);
the Makefile will stop with a direct message instead of attempting a
system-wide Python package install.

To enable live KijaniSpace enrichment, provide the credentials in the runtime
environment (do not commit them):

```bash
export KIJANISPACE_API_BASE_URL=https://api.kijanispace.eu
export KIJANISPACE_USERNAME=...
export KIJANISPACE_PASSWORD=...
make dev
```

The agent calls KijaniSpace's authenticated `/v1/agro_climate/land` endpoint
for a plot coordinate and stores normalized live soil, weather, land-use, and
vegetation provenance in `telemetry_cache`. If the request times out, returns
an error, or credentials are absent, the agent uses the most recent cached
reading and exposes `freshness: cached` plus the upstream error in its trace.
Credentials are never written to the database or returned by the API.

All farmer records are synthetic (`SYNTH-HB-*`) and model the KIAMIS/NVSP
shape. The product is a decision-support prototype, not a replacement for
official agronomic or subsidy policy.
