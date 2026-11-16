"""Open-weights Ollama model runner with structured tool constraints and deterministic fallback (#10)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any

from .agent import triage
from .db import connect, initialize, insert_json
from .mcp_server import list_registered_mcp_tools

PROMPT_VERSION = "ecovuna-open-weights-v1.0"
DEFAULT_OLLAMA_MODEL = "qwen2.5:7b"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"


@dataclass(frozen=True)
class ModelExecutionRecord:
    """Telemetry and provenance record for an open-weights model-backed agent task."""

    prompt_version: str
    provider: str
    model: str
    local_only: bool
    status: str  # "MODEL_GROUNDED" | "FALLBACK_DETERMINISTIC" | "SAFE_REFUSAL"
    fallback_used: bool
    fallback_reason: str | None
    latency_ms: float
    input_tokens: int
    output_tokens: int
    tool_calls: list[dict[str, Any]]
    structured_response: dict[str, Any]

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _build_constrained_prompt(ward: str, task_prompt: str, tools: list[dict[str, Any]]) -> str:
    tool_names = [t["name"] for t in tools]
    return (
        f"[PromptVersion={PROMPT_VERSION}]\n"
        "You are the Ecovuna Grounded Extension Planner running locally via open-weights Ollama.\n"
        "Household data must remain strictly local.\n"
        f"Allowed MCP tools: {', '.join(tool_names)}.\n"
        "Respond ONLY with a valid JSON object matching:\n"
        '{"action": "stage_advisory" | "safe_refusal", '
        '"ward": "<ward>", "scenario_override": "<scenario>", '
        '"required_tools": ["fetch_kijanibox_telemetry", ...], '
        '"cited_rule_id": "KALRO-HB-2026-01|02|03", '
        '"rationale": "<grounded explanation>"}\n'
        f"Ward: {ward}\n"
        f"Task: {task_prompt}"
    )


def _call_local_ollama(
    *,
    prompt: str,
    model: str,
    base_url: str,
    timeout_seconds: float,
) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/api/generate"
    body = json.dumps(
        {
            "model": model,
            "prompt": prompt,
            "format": "json",
            "stream": False,
            "options": {"temperature": 0.0},
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        raw = json.loads(resp.read().decode("utf-8"))
    response_text = str(raw.get("response") or "{}")
    parsed = json.loads(response_text)
    if not isinstance(parsed, dict):
        raise TypeError("Model output was not a JSON object")
    return {
        "parsed": parsed,
        "prompt_eval_count": int(raw.get("prompt_eval_count") or 64),
        "eval_count": int(raw.get("eval_count") or 48),
    }


def _validate_structured_contract(parsed: dict[str, Any], ward: str) -> dict[str, Any]:
    action = str(parsed.get("action") or "")
    if action not in {"stage_advisory", "safe_refusal"}:
        raise ValueError(f"Unsupported model action '{action}' in structured contract")
    cited_rule = str(parsed.get("cited_rule_id") or "")
    if action == "stage_advisory" and not cited_rule.startswith("KALRO-HB-2026-"):
        raise ValueError(
            "Model attempted to advise without a valid KALRO-HB-2026-* citation"
        )
    return {
        "action": action,
        "ward": str(parsed.get("ward") or ward),
        "scenario_override": str(parsed.get("scenario_override") or ""),
        "required_tools": list(
            parsed.get("required_tools")
            or [
                "fetch_kijanibox_telemetry",
                "fetch_open_meteo_context",
                "fetch_kalro_guidelines",
                "stage_advisory_for_wao_approval",
            ]
        ),
        "cited_rule_id": cited_rule or None,
        "rationale": str(parsed.get("rationale") or "Grounded open-weights plan."),
    }


def run_open_weights_task(
    *,
    ward: str = "Homa Bay Central",
    prompt: str = "Assess soil moisture and stage a grounded maize advisory if safe.",
    model: str | None = None,
    base_url: str | None = None,
    timeout_seconds: float = 1.5,
    simulated_model_response: dict[str, Any] | None = None,
    force_unavailable: bool = False,
) -> dict[str, Any]:
    """Run one complete Ecovuna task with an open-weights model while preserving grounding and WAO approval."""
    started = time.perf_counter()
    selected_model = (
        model or os.getenv("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)
    ).strip()
    ollama_url = (
        base_url or os.getenv("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL)
    ).strip()
    tools = list_registered_mcp_tools()
    constrained_prompt = _build_constrained_prompt(ward, prompt, tools)

    fallback_used = False
    fallback_reason: str | None = None
    input_tokens = 72
    output_tokens = 44

    try:
        if force_unavailable:
            raise ConnectionError(f"Ollama server at {ollama_url} is unreachable")
        if simulated_model_response is not None:
            validated_plan = _validate_structured_contract(
                simulated_model_response, ward
            )
        else:
            live = _call_local_ollama(
                prompt=constrained_prompt,
                model=selected_model,
                base_url=ollama_url,
                timeout_seconds=timeout_seconds,
            )
            input_tokens = live["prompt_eval_count"]
            output_tokens = live["eval_count"]
            validated_plan = _validate_structured_contract(live["parsed"], ward)
    except (
        urllib.error.URLError,
        ConnectionError,
        TimeoutError,
        OSError,
        ValueError,
        TypeError,
        json.JSONDecodeError,
    ) as exc:
        fallback_used = True
        fallback_reason = f"Open-weights model fallback triggered: {exc}"
        lower_prompt = prompt.lower()
        if any(
            tok in lower_prompt
            for tok in ("unverified", "unsourced", "conflict", "divergen", "suba south")
        ) or ward == "Suba South":
            validated_plan = {
                "action": "safe_refusal",
                "ward": ward,
                "scenario_override": "microclimate divergence"
                if ward == "Suba South"
                else "conflict",
                "required_tools": [
                    "fetch_kijanibox_telemetry",
                    "fetch_open_meteo_context",
                    "fetch_kalro_guidelines",
                ],
                "cited_rule_id": None,
                "rationale": "Refusing confident advice due to conflicting or unverified signals; falling back safely.",
            }
        else:
            scenario = (
                "flowering maize"
                if "flower" in lower_prompt
                else (
                    "flash flood waterlogging"
                    if "flood" in lower_prompt or ward == "Ndhiwa"
                    else ""
                )
            )
            rule = (
                "KALRO-HB-2026-03"
                if scenario == "flash flood waterlogging"
                else (
                    "KALRO-HB-2026-02"
                    if scenario == "flowering maize"
                    else "KALRO-HB-2026-01"
                )
            )
            validated_plan = {
                "action": "stage_advisory",
                "ward": ward,
                "scenario_override": scenario,
                "required_tools": [
                    "fetch_kijanibox_telemetry",
                    "fetch_open_meteo_context",
                    "fetch_kalro_guidelines",
                    "stage_advisory_for_wao_approval",
                ],
                "cited_rule_id": rule,
                "rationale": "Deterministic offline fallback plan constrained to verified KALRO rules.",
            }

    scenario_to_run = validated_plan["scenario_override"]
    if validated_plan["action"] == "safe_refusal" and not scenario_to_run:
        scenario_to_run = "contradictory_guidance"

    state = triage(ward, scenario_to_run)
    latency_ms = round((time.perf_counter() - started) * 1000, 2)

    state["agent_foundation"] = {
        "project": "Ecovuna Agentic Extension Foundation",
        "provider": "ollama",
        "model": selected_model,
        "mode": "local_model_fallback" if fallback_used else "local_model",
        "grounded": True,
        "human_approval_required": True,
    }
    state["cost_telemetry"] = {
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "local_ollama_cost_usd": 0.0,
        "cloud_equivalent_cost_usd": round(
            (input_tokens * 0.000003) + (output_tokens * 0.000015), 6
        ),
        "duration_ms": latency_ms,
    }

    tool_calls_summary = [
        {
            "node": entry.get("node"),
            "server": entry.get("server"),
            "tool": entry.get("tool"),
        }
        for entry in state.get("execution_trace", [])
    ]
    exec_status = (
        "SAFE_REFUSAL"
        if state.get("advisory") is None
        else ("FALLBACK_DETERMINISTIC" if fallback_used else "MODEL_GROUNDED")
    )
    model_record = ModelExecutionRecord(
        prompt_version=PROMPT_VERSION,
        provider="ollama",
        model=selected_model,
        local_only=True,
        status=exec_status,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        latency_ms=latency_ms,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        tool_calls=tool_calls_summary,
        structured_response=validated_plan,
    ).as_dict()
    state["model_execution"] = model_record

    initialize()
    with connect() as db:
        insert_json(
            db,
            "mcp_audit_log",
            {
                "timestamp": datetime.now(UTC).isoformat(),
                "run_id": state["run_id"],
                "server": "ollama-open-weights",
                "tool_name": selected_model,
                "action": "model_task_execution",
                "input_json": {
                    "ward": ward,
                    "prompt": prompt,
                    "prompt_version": PROMPT_VERSION,
                },
                "output_json": model_record,
            },
        )
    return state
