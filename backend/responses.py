"""Standard structured API error responses."""

from __future__ import annotations

import uuid
from typing import Any

from fastapi.responses import JSONResponse
from starlette.requests import Request

from .errors import sanitize_error_message


def resolve_request_id(request: Request | None) -> str:
    if request is not None:
        header_id = request.headers.get("x-request-id", "").strip()
        if header_id:
            return header_id
        state_id = getattr(request.state, "request_id", None)
        if isinstance(state_id, str) and state_id:
            return state_id
    return f"REQ-{uuid.uuid4().hex[:12].upper()}"


def http_response(
    detail: str | None = None,
    status_code: int = 400,
    *,
    request: Request | None = None,
    message: str | None = None,
    error_code: str = "BAD_REQUEST",
    retryable: bool = False,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    request_id = resolve_request_id(request)
    safe_message = sanitize_error_message(message or detail or "Request failed.")
    safe_details: dict[str, Any] = {}
    for key, value in (details or {}).items():
        if isinstance(value, str):
            safe_details[key] = sanitize_error_message(value)
        else:
            safe_details[key] = value
    payload = {
        "request_id": request_id,
        "error_code": error_code,
        "message": safe_message,
        "detail": safe_message,
        "retryable": retryable,
        "details": safe_details,
    }
    return JSONResponse(
        content=payload,
        status_code=status_code,
        headers={"X-Request-ID": request_id},
    )
