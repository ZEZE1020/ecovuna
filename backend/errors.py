"""Centralized application exceptions and credential-safe error formatting."""

from __future__ import annotations

import re
from typing import Any

_SENSITIVE_PATTERNS = (
    re.compile(r"(?i)(api[_-]?key|token|secret|password|authorization)\s*[:=]\s*\S+"),
    re.compile(r"(?i)bearer\s+[a-z0-9._\-]+"),
)


def sanitize_error_message(message: str) -> str:
    """Remove credential tokens or provider secrets from outward-facing error messages."""
    cleaned = message
    for pattern in _SENSITIVE_PATTERNS:
        cleaned = pattern.sub("[REDACTED]", cleaned)
    return cleaned


class EcovunaError(Exception):
    """Base class for application-specific domain and API errors."""

    def __init__(
        self,
        detail: str,
        status_code: int = 400,
        *,
        error_code: str = "BAD_REQUEST",
        retryable: bool = False,
        details: dict[str, Any] | None = None,
    ) -> None:
        sanitized = sanitize_error_message(detail)
        super().__init__(sanitized)
        self.detail = sanitized
        self.message = sanitized
        self.status_code = status_code
        self.error_code = error_code
        self.retryable = retryable
        self.details = details or {}


class NotFoundError(EcovunaError):
    """Raised when a requested domain record is not found."""

    def __init__(
        self,
        detail: str = "Resource not found.",
        *,
        error_code: str = "NOT_FOUND",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            detail,
            status_code=404,
            error_code=error_code,
            retryable=False,
            details=details,
        )


class InvalidRequestError(EcovunaError):
    """Raised for domain validation errors or malformed requests."""

    def __init__(
        self,
        detail: str = "Invalid request.",
        *,
        error_code: str = "VALIDATION_ERROR",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            detail,
            status_code=422,
            error_code=error_code,
            retryable=False,
            details=details,
        )


class ConflictError(EcovunaError):
    """Raised when an operation conflicts with current state or idempotency rules."""

    def __init__(
        self,
        detail: str = "State conflict.",
        *,
        error_code: str = "STATE_CONFLICT",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            detail,
            status_code=409,
            error_code=error_code,
            retryable=False,
            details=details,
        )


class PolicyViolationError(EcovunaError):
    """Raised when an action violates server-side tool or approval policy."""

    def __init__(
        self,
        detail: str = "Policy violation.",
        *,
        error_code: str = "POLICY_VIOLATION",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            detail,
            status_code=403,
            error_code=error_code,
            retryable=False,
            details=details,
        )


class ProviderUnavailableError(EcovunaError):
    """Raised when an upstream provider or external connector fails transiently."""

    def __init__(
        self,
        detail: str = "Upstream provider is temporarily unavailable.",
        *,
        error_code: str = "PROVIDER_UNAVAILABLE",
        retryable: bool = True,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(
            detail,
            status_code=503,
            error_code=error_code,
            retryable=retryable,
            details=details,
        )
