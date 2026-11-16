"""Health and runtime configuration router."""

from __future__ import annotations

import os

from fastapi import APIRouter

from ..contracts import AgentFoundationResponse, HealthResponse, TelemetryStatusResponse
from ..db import storage_backend
from ..foundation import get_agent_foundation
from ..observability import telemetry_status

router = APIRouter(tags=["health"])


@router.get("/api/health", response_model=HealthResponse)
def health() -> HealthResponse:
    release_version = os.getenv("RELEASE_VERSION", "local")
    return HealthResponse(
        status="ok",
        release_version=release_version,
        storage_backend=storage_backend(),
        telemetry=TelemetryStatusResponse.model_validate(telemetry_status()),
        agent_foundation=AgentFoundationResponse.model_validate(
            get_agent_foundation().as_dict()
        ),
    )
