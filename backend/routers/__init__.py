"""Modular FastAPI routers for the Ecovuna API."""

from __future__ import annotations

from .agent import router as agent_router
from .audit import router as audit_router
from .health import router as health_router
from .mcp import router as mcp_router
from .operations import router as operations_router
from .registry import router as registry_router

__all__ = [
    "agent_router",
    "audit_router",
    "health_router",
    "mcp_router",
    "operations_router",
    "registry_router",
]
