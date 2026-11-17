"""Typed Pydantic request and response contracts for the Ecovuna API."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class ErrorEnvelope(BaseModel):
    request_id: str
    error_code: str
    message: str
    detail: str
    retryable: bool
    details: dict[str, Any] = Field(default_factory=dict)


class TriageRequest(BaseModel):
    ward: str = Field(default="Homa Bay Central", min_length=1, max_length=100)
    scenario_override: str = ""


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)
    ward: str | None = Field(default=None, min_length=1, max_length=100)
    session_id: str | None = None
    crop: str | None = None
    season: str | None = None


class DecisionRequest(BaseModel):
    run_id: str
    approved: bool
    wao_officer_name: str
    notes: str = ""
    approval_token: str | None = None


class ConsequentialActionRequest(BaseModel):
    tool_name: str
    run_id: str
    wao_officer_name: str
    approval_token: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class ConsequentialActionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    tool_name: str
    status: str
    wao_officer_name: str
    approval_token: str
    payload: dict[str, Any] = Field(default_factory=dict)
    policy_decision: dict[str, Any] = Field(default_factory=dict)


class RecommendationRequest(BaseModel):
    ward: str | None = None
    crop_type: str | None = None
    category: str | None = None
    limit: int = Field(default=20, ge=1, le=100)


class FarmerOnboardingRequest(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone_number: str = Field(min_length=1, max_length=40)
    ward: str = Field(min_length=1, max_length=100)
    agroclimatic_zone: str = ""
    cooperative_name: str = ""
    preferred_language: str = "en"


class PlotOnboardingRequest(BaseModel):
    farmer_id: str = Field(min_length=1)
    latitude: float
    longitude: float
    crop_type: str = Field(min_length=1)
    planting_date: str = Field(min_length=1)
    current_growth_stage: str = Field(min_length=1)
    acreage: float
    kijanibox_sensor_id: str = ""


class AssignmentRequest(BaseModel):
    plot_id: str = Field(min_length=1)
    partner_id: str = Field(min_length=1)
    input_id: str | None = None
    officer_id: str = "system"
    approval_token: str | None = None


class TelemetryStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    enabled: bool
    service_name: str
    exporter: str
    endpoint: str | None = None


class AgentFoundationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    project: str
    provider: str
    model: str
    mode: str
    grounded: bool
    human_approval_required: bool


class HealthResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    status: str
    release_version: str
    storage_backend: str
    telemetry: TelemetryStatusResponse
    agent_foundation: AgentFoundationResponse


class EvaluationCaseResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    key: str
    description: str
    pass_at_one: bool
    consistent: bool


class EvaluationInterpretationResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    data_grounding: str
    agent_usefulness: str
    model_status: str


class EvaluationSummaryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    trials: int
    passed: int
    total: int
    pass_rate: float
    cases: list[EvaluationCaseResponse]
    interpretation: EvaluationInterpretationResponse


class AdvisoryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    advisory_id: str
    run_id: str
    ward: str
    anomaly_type: str
    target_growth_stage: str
    affected_plot_ids: list[str]
    affected_household_count: int
    draft_sms_swahili: str
    draft_sms_english: str
    ussd_menu_payload: str
    evoucher_package_code: str
    evoucher_total_kes: float
    per_farmer_kes: float
    citations: dict[str, Any]
    status: str
    gate_message: str | None = None


class TraceEntryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    node: str
    tool: str
    server: str
    latency_ms: int | float
    output: dict[str, Any]
    transition: str | None = None


class CostTelemetryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_tokens: int = 0
    output_tokens: int = 0
    local_ollama_cost_usd: float = 0.0
    cloud_equivalent_cost_usd: float = 0.0
    duration_ms: float


class AgentRunResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    ward: str
    scenario_override: str = ""
    telemetry: dict[str, Any] = Field(default_factory=dict)
    advisory: AdvisoryResponse | dict[str, Any] | None = None
    execution_trace: list[TraceEntryResponse] = Field(default_factory=list)
    status: str
    cost_telemetry: CostTelemetryResponse
    agent_foundation: AgentFoundationResponse
    error: str | None = None


class ConversationContextResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str
    ward: str
    crop: str
    season: str
    telemetry_freshness: str
    prior_run_ids: list[str] = Field(default_factory=list)
    unresolved_questions: list[str] = Field(default_factory=list)


class ConversationSectionsResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    observed_facts: list[str] = Field(default_factory=list)
    interpretation: str
    uncertainty: str
    recommendation: str
    approval_state: str
    citations: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    session_id: str | None = None
    message: str
    question: str
    context: ConversationContextResponse | None = None
    sections: ConversationSectionsResponse | None = None
    run: AgentRunResponse


class DecisionResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    run_id: str
    status: str
    wao_officer_name: str


class McpServerStatusResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: str
    name: str
    transport: str
    tools: list[str]
    status: str


class McpActivityEntryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    server: str
    tool_name: str
    timestamp: str


class McpRegistryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    servers: list[McpServerStatusResponse]
    recent_activity: list[McpActivityEntryResponse]


class AuditLogEntryResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int
    timestamp: str
    run_id: str
    server: str
    tool_name: str
    action: str
    input_json: str
    output_json: str


class DashboardCountsResponse(BaseModel):
    households: int
    plots: int
    advisories: int
    pending_advisories: int
    field_visits_due: int


class WardSummaryResponse(BaseModel):
    ward: str
    households: int
    plots: int
    soil_moisture_pct: float | None = None
    last_telemetry_at: str | None = None


class DashboardResponse(BaseModel):
    counts: DashboardCountsResponse
    wards: list[WardSummaryResponse]


class TelemetryReadingResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    id: int | None = None
    ward: str
    sensor_id: str
    timestamp: str
    soil_moisture_pct: float
    soil_temp_c: float
    precipitation_7d_mm: float
    rainfall_anomaly_mm: float
    raw_payload_json: dict[str, Any]
    source: str
    freshness: str


class TelemetryResponse(BaseModel):
    ward: str | None = None
    readings: list[TelemetryReadingResponse]


class FarmerResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    farmer_id: str
    full_name: str
    phone_number: str
    ward: str
    agroclimatic_zone: str
    cooperative_name: str
    preferred_language: str
    plot_count: int | None = None


class PlotResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    plot_id: str
    farmer_id: str
    latitude: float
    longitude: float
    crop_type: str
    planting_date: str
    current_growth_stage: str
    acreage: float
    kijanibox_sensor_id: str
    repayment_score: int
    subsidy_tier_eligible: str


class PartnerResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    partner_id: str
    name: str
    partner_type: str
    ward: str
    latitude: float
    longitude: float
    service_radius_km: float
    verified: int
    contact_name: str
    contact_phone: str


class InputCatalogResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    input_id: str
    name: str
    category: str
    crop_types: list[str]
    soil_profiles: list[str]
    climate_zones: list[str]
    unit: str
    price_kes: float
    partner_id: str
    stock_status: str


class OperationsSummaryResponse(BaseModel):
    verified_partners: int
    in_stock_inputs: int
    recommended_assignments: int
    confirmed_assignments: int


class RecommendationPartnerResponse(BaseModel):
    partner_id: str
    name: str
    partner_type: str


class PhoneMessage(BaseModel):
    """A single SMS message in a farmer's inbox."""

    model_config = ConfigDict(extra="allow")

    sender: str
    timestamp: str
    text_sw: str
    text_en: str
    text_luo: str
    citation: str


class PhoneInboxResponse(BaseModel):
    """The response from the phone inbox endpoint."""

    model_config = ConfigDict(extra="allow")

    messages: list[PhoneMessage]


class RecommendationInputResponse(BaseModel):
    input_id: str
    name: str
    category: str
    unit: str
    price_kes: float


class RecommendationItemResponse(BaseModel):
    plot_id: str
    farmer_id: str
    ward: str
    crop_type: str
    soil_profile: str
    soil_moisture_pct: float | None = None
    agroclimatic_zone: str
    partner: RecommendationPartnerResponse
    input: RecommendationInputResponse
    score: int
    reasons: list[str]


class AssignmentResponse(BaseModel):
    model_config = ConfigDict(extra="allow")

    assignment_id: str
    status: str
    plot_id: str
    partner_id: str
    input_id: str | None = None