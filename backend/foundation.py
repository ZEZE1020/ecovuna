"""Agentic AI foundation configuration shared by the API and agent workflow."""
from __future__ import annotations

import os
from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class AgentFoundation:
    """Describe the model/tool boundary without hiding offline operation."""

    project: str
    provider: str
    model: str
    mode: str
    grounded: bool
    human_approval_required: bool

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


def get_agent_foundation() -> AgentFoundation:
    provider = os.getenv("LLM_PROVIDER", "deterministic_offline").strip().lower()
    if provider in {"aws", "bedrock", "aws_bedrock"}:
        provider = "aws_bedrock"
        model = os.getenv("BEDROCK_MODEL_ID", "amazon.nova-lite-v1:0")
        mode = "aws_bedrock_model"
    elif provider == "ollama":
        model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
        mode = "local_model"
    elif provider in {"gemini", "google_genai"}:
        provider = "gemini"
        model = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
        mode = "managed_model"
    else:
        provider = "deterministic_offline"
        model = "rule-grounded-planner"
        mode = "offline"

    return AgentFoundation(
        project="Ecovuna Agentic Extension Foundation",
        provider=provider,
        model=model,
        mode=mode,
        grounded=True,
        human_approval_required=True,
    )
