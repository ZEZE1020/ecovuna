"""Agent orchestration, chat, evaluation, and HITL decision router."""

from __future__ import annotations

from fastapi import APIRouter

from ..agent import decide, triage
from ..contracts import (
    AgentFoundationResponse,
    AgentRunResponse,
    ChatRequest,
    ChatResponse,
    ConsequentialActionRequest,
    ConsequentialActionResponse,
    DecisionRequest,
    DecisionResponse,
    EvaluationSummaryResponse,
    TriageRequest,
)
from ..conversations import get_conversation_session, run_conversation_turn
from ..errors import EcovunaError, InvalidRequestError, ProviderUnavailableError
from ..evals.summary import summary as evaluation_summary
from ..foundation import get_agent_foundation
from ..kijanispace import KijaniSpaceError
from ..policy import TOOL_POLICIES, execute_consequential_action

router = APIRouter(tags=["agent"])


@router.get("/api/agent/foundation", response_model=AgentFoundationResponse)
def agent_foundation() -> AgentFoundationResponse:
    """Expose the active model, grounding, and approval contract to operators."""
    return AgentFoundationResponse.model_validate(get_agent_foundation().as_dict())


@router.get("/api/evaluations/summary", response_model=EvaluationSummaryResponse)
def evaluations_summary(trials: int = 1) -> EvaluationSummaryResponse:
    """Return small, repeatable quality signals for the operator console."""
    if trials < 1 or trials > 20:
        raise InvalidRequestError(
            "trials must be between 1 and 20.",
            error_code="INVALID_TRIALS",
        )
    return EvaluationSummaryResponse.model_validate(evaluation_summary(trials))


@router.post("/api/agent/triage", response_model=AgentRunResponse)
def run_triage(request: TriageRequest) -> AgentRunResponse:
    if not request.ward.strip():
        raise InvalidRequestError("ward is required.", error_code="INVALID_WARD")
    try:
        result = triage(request.ward.strip(), request.scenario_override)
    except EcovunaError:
        raise
    except KijaniSpaceError as exc:
        raise ProviderUnavailableError(
            "Telemetry provider failed transiently; retry or use cached readings.",
            details={"provider": "kijanispace", "reason": str(exc)},
        ) from exc
    except (ValueError, KeyError) as exc:
        raise InvalidRequestError(str(exc)) from exc
    return AgentRunResponse.model_validate(result)


@router.post("/api/agent/chat", response_model=ChatResponse)
def agent_chat(request: ChatRequest) -> ChatResponse:
    """Translate a plain-language question into a grounded, context-aware run."""
    if not request.message.strip():
        raise InvalidRequestError("message is required.", error_code="EMPTY_MESSAGE")
    try:
        turn = run_conversation_turn(
            message=request.message.strip(),
            ward=request.ward,
            session_id=request.session_id,
            crop=request.crop,
            season=request.season,
        )
    except EcovunaError:
        raise
    except KijaniSpaceError as exc:
        raise ProviderUnavailableError(
            "Telemetry provider failed transiently; retry or use cached readings.",
            details={"provider": "kijanispace", "reason": str(exc)},
        ) from exc
    except (ValueError, KeyError) as exc:
        raise InvalidRequestError(str(exc)) from exc
    return ChatResponse.model_validate(turn)


@router.get("/api/agent/sessions/{session_id}")
def get_session(session_id: str) -> dict[str, object]:
    """Return persisted conversation session context and turn history."""
    return get_conversation_session(session_id)


@router.post("/api/agent/decide", response_model=DecisionResponse)
def make_decision(request: DecisionRequest) -> DecisionResponse:
    try:
        result = decide(
            request.run_id,
            request.approved,
            request.wao_officer_name,
            request.notes,
            approval_token=request.approval_token,
            channel="api",
        )
    except EcovunaError:
        raise
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    return DecisionResponse.model_validate(result)


@router.get("/api/agent/policies")
def list_tool_policies() -> dict[str, object]:
    """Expose server-side tool categories and approval policy rules."""
    return {
        "policies": [rule.as_dict() for rule in TOOL_POLICIES.values()],
    }


@router.post("/api/agent/actions", response_model=ConsequentialActionResponse)
def run_consequential_action(
    request: ConsequentialActionRequest,
) -> ConsequentialActionResponse:
    """Execute a consequential external action only after policy and token verification."""
    result = execute_consequential_action(
        tool_name=request.tool_name,
        run_id=request.run_id,
        wao_officer_name=request.wao_officer_name,
        approval_token=request.approval_token,
        payload=request.payload,
        channel="api",
    )
    return ConsequentialActionResponse.model_validate(result)
