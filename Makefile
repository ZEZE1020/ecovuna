.SHELLFLAGS := -eu -o pipefail -c
SHELL := /bin/bash

.PHONY: setup ingest dev telemetry-up telemetry-down test model-task clean

UV ?= uv
VENV ?= .venv
VENV_PYTHON := $(VENV)/bin/python
PYTEST := $(VENV_PYTHON) -m pytest
RUFF := $(VENV_PYTHON) -m ruff

$(VENV_PYTHON):
	@command -v $(UV) >/dev/null 2>&1 || { \
		echo "uv is required. Install it from https://docs.astral.sh/uv/getting-started/installation/"; \
		exit 1; \
	}
	$(UV) venv $(VENV) --python 3.11

setup: $(VENV_PYTHON)
	UV_PROJECT_ENVIRONMENT=$(VENV) $(UV) sync --project backend --active
	$(VENV_PYTHON) -m backend.ingest --offline-fallback
	@run_pnpm() { \
		if pnpm --version >/dev/null 2>&1; then pnpm "$$@"; \
		elif command -v corepack >/dev/null 2>&1 && corepack pnpm --version >/dev/null 2>&1; then corepack pnpm "$$@"; \
		elif command -v npm >/dev/null 2>&1; then npm exec --yes pnpm@9.15.0 -- "$$@"; \
		else echo "A working pnpm, corepack, or npm is required for the frontend."; exit 1; fi; \
	}; \
	run_pnpm --dir frontend install --frozen-lockfile

ingest: $(VENV_PYTHON)
	$(VENV_PYTHON) -m backend.ingest

dev: setup telemetry-up
	$(VENV_PYTHON) -m backend.ingest --offline-fallback
	@backend_pid=0; frontend_pid=0; \
	trap 'kill "$$backend_pid" "$$frontend_pid" 2>/dev/null || true' EXIT INT TERM; \
	OTEL_EXPORTER_OTLP_TRACES_ENDPOINT=$${OTEL_EXPORTER_OTLP_TRACES_ENDPOINT:-http://localhost:4318/v1/traces} \
	$(VENV)/bin/uvicorn backend.main:app --reload --port 8000 & backend_pid=$$!; \
	run_pnpm() { \
		if pnpm --version >/dev/null 2>&1; then pnpm "$$@"; \
		elif command -v corepack >/dev/null 2>&1 && corepack pnpm --version >/dev/null 2>&1; then corepack pnpm "$$@"; \
		elif command -v npm >/dev/null 2>&1; then npm exec --yes pnpm@9.15.0 -- "$$@"; \
		else echo "A working pnpm, corepack, or npm is required for the frontend."; exit 1; fi; \
	}; \
	run_pnpm --dir frontend dev & frontend_pid=$$!; \
	echo "Backend: http://localhost:8000/docs"; \
	echo "Frontend: http://localhost:3000"; \
	echo "Telemetry: http://localhost:16686"; \
	wait -n "$$backend_pid" "$$frontend_pid"

telemetry-up:
	docker compose up -d jaeger
	@echo "Jaeger dashboard: http://localhost:16686"
	@echo "OTLP/HTTP collector: http://localhost:4318/v1/traces"

telemetry-down:
	docker compose stop jaeger

test: setup
	$(RUFF) check backend
	$(PYTEST) backend/tests
	$(VENV_PYTHON) -m backend.evals.run_evals --trials 3

model-task: setup
	$(VENV_PYTHON) -c "import json; from backend.open_weights import run_open_weights_task; r = run_open_weights_task(); print(json.dumps({'run_id': r['run_id'], 'status': r['status'], 'model_execution': r['model_execution']}, indent=2))"

clean:
	rm -rf $(VENV)
