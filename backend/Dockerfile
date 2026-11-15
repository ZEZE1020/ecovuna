FROM ghcr.io/astral-sh/uv:0.6.14-python3.11-bookworm-slim
WORKDIR /app
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/uv.lock backend/uv.lock
RUN UV_PROJECT_ENVIRONMENT=/app/.venv uv sync --project backend --locked --no-dev
COPY backend backend
COPY data data
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
CMD ["sh", "-c", "python -m backend.ingest --offline-fallback && uvicorn backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
