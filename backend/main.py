"""FastAPI HTTP interface and centralized error/router wiring for the agent console."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

from .db import initialize
from .errors import EcovunaError
from .observability import configure_fastapi
from .responses import http_response, resolve_request_id
from .routers import (
    agent_router,
    audit_router,
    health_router,
    mcp_router,
    operations_router,
    registry_router,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize()
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="Ecovuna Desk API",
        version="1.0.0",
        lifespan=lifespan,
    )
    configure_fastapi(application)
    allowed_origins = [
        origin
        for origin in (
            "http://localhost:3000",
            "http://127.0.0.1:3000",
            os.getenv("FRONTEND_ORIGIN", "").rstrip("/"),
        )
        if origin
    ]
    application.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins,
        allow_origin_regex=r"https?://(localhost|127\.0\.0\.1):\d+",
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @application.middleware("http")
    async def attach_request_id(request: Request, call_next):
        request_id = resolve_request_id(request)
        request.state.request_id = request_id
        response = await call_next(request)
        response.headers.setdefault("X-Request-ID", request_id)
        return response

    @application.exception_handler(EcovunaError)
    async def ecovuna_exception_handler(
        request: Request, exc: EcovunaError
    ) -> JSONResponse:
        return http_response(
            request=request,
            message=exc.message,
            status_code=exc.status_code,
            error_code=exc.error_code,
            retryable=exc.retryable,
            details=exc.details,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        fields = [
            ".".join(str(part) for part in item.get("loc", ()))
            for item in exc.errors()
        ]
        return http_response(
            request=request,
            message="Request payload failed schema validation.",
            status_code=422,
            error_code="VALIDATION_ERROR",
            retryable=False,
            details={"invalid_fields": fields},
        )

    @application.exception_handler(Exception)
    async def unhandled_exception_handler(
        request: Request, exc: Exception
    ) -> JSONResponse:
        _ = exc
        return http_response(
            request=request,
            message="An internal error occurred while processing the request.",
            status_code=500,
            error_code="INTERNAL_ERROR",
            retryable=True,
        )

    application.include_router(health_router)
    application.include_router(agent_router)
    application.include_router(mcp_router)
    application.include_router(audit_router)
    application.include_router(registry_router)
    application.include_router(operations_router)
    return application


app = create_app()
