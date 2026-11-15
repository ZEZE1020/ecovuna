"""OpenTelemetry configuration for the FastAPI service."""
from __future__ import annotations

import os
from dataclasses import dataclass

from fastapi import FastAPI
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


@dataclass(frozen=True)
class TelemetryStatus:
    enabled: bool
    service_name: str
    exporter: str


_status = TelemetryStatus(False, "ecovuna-api", "none")
_configured = False


def configure_fastapi(app: FastAPI) -> TelemetryStatus:
    """Instrument a FastAPI app and export traces when an OTLP endpoint is configured."""
    global _configured, _status
    if _configured:
        return _status

    service_name = os.getenv("OTEL_SERVICE_NAME", "ecovuna-api")
    endpoint = os.getenv("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT") or os.getenv(
        "OTEL_EXPORTER_OTLP_ENDPOINT"
    )
    resource = Resource.create({
        "service.name": service_name,
        "service.version": os.getenv("ECOVUNA_VERSION", "1.0.0"),
        "deployment.environment": os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", "local"),
    })
    provider = TracerProvider(resource=resource)
    if endpoint:
        if endpoint.rstrip("/").endswith("/v1/traces"):
            traces_endpoint = endpoint
        else:
            traces_endpoint = f"{endpoint.rstrip('/')}/v1/traces"
        provider.add_span_processor(BatchSpanProcessor(
            OTLPSpanExporter(endpoint=traces_endpoint)
        ))
        _status = TelemetryStatus(True, service_name, "otlp/http")
    else:
        _status = TelemetryStatus(False, service_name, "none")
    trace.set_tracer_provider(provider)
    FastAPIInstrumentor.instrument_app(app)
    _configured = True
    return _status


def telemetry_status() -> dict[str, str | bool]:
    return {
        "enabled": _status.enabled,
        "service_name": _status.service_name,
        "exporter": _status.exporter,
    }
