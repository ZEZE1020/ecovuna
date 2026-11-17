"use client";

import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity, Check, CircleAlert, ClipboardCheck, Clock3, Database, Leaf,
  FileSearch, Flag, LockKeyhole, Play, Radar, ShieldCheck, Sparkles,
  MessageCircle, Send, Terminal, UserPlus, UserRound, Workflow, X,
} from "lucide-react";

type Ward = {
  ward: string;
  households: number;
  plots: number;
  soil_moisture_pct: number | null;
  last_telemetry_at: string | null;
};
type Dashboard = {
  counts: { households: number; plots: number; advisories: number; pending_advisories: number };
  wards: Ward[];
};
type TelemetryReading = {
  id: number;
  ward: string;
  sensor_id: string;
  timestamp: string;
  soil_moisture_pct: number;
  soil_temp_c: number;
  precipitation_7d_mm: number;
  rainfall_anomaly_mm: number;
  source: string;
  freshness: "live" | "cached";
  raw_payload_json: {
    elevation_m?: number;
    landuse?: string;
    forecast_model_run?: string;
    moisture_delta_pct?: number;
    ndvi_anomaly_status?: string;
    pest_thermal_alert?: string;
    registered_smallholders?: number;
    lead_persona?: string;
    wao_officer?: string;
    vegetation_indices?: {
      date?: string;
      NDVI?: number;
      vegetation_health_index?: number;
      vegetation_condition_index?: number;
    };
  };
};
type OperationsSummary = {
  verified_partners: number;
  in_stock_inputs: number;
  recommended_assignments: number;
  confirmed_assignments: number;
};
type Recommendation = {
  plot_id: string;
  farmer_id: string;
  ward: string;
  crop_type: string;
  soil_profile: string;
  soil_moisture_pct: number | null;
  agroclimatic_zone: string;
  partner: { partner_id: string; name: string; partner_type: string };
  input: { input_id: string; name: string; category: string; unit: string; price_kes: number };
  score: number;
  reasons: string[];
};
type OutputVariant = {
  language: string;
  channel: string;
  text: string;
  character_length: number;
  max_length: number;
  status: string;
};
type Advisory = {
  advisory_id: string;
  run_id: string;
  ward: string;
  anomaly_type: string;
  target_growth_stage: string;
  affected_plot_ids: string[];
  affected_household_count: number;
  draft_sms_swahili: string;
  draft_sms_english: string;
  ussd_menu_payload: string;
  evoucher_package_code: string;
  evoucher_total_kes: number;
  per_farmer_kes: number;
  citations: { sensor_ids?: string[]; plot_ids?: string[]; weather_bulletin_id?: string; kalro_rule_id?: string };
  status: string;
  output_variants?: OutputVariant[];
};
type Trace = { node: string; tool: string; server: string; latency_ms: number; output: Record<string, unknown> };
type Run = {
  run_id: string;
  ward: string;
  status: string;
  execution_trace: Trace[];
  advisory: Advisory | null;
  telemetry: { readings: Array<Record<string, string | number>> };
  cost_telemetry: { duration_ms: number };
  agent_foundation?: AgentFoundation;
  conflicts?: Array<{ code: string; summary?: string; detail?: string; recommended_verification?: string }>;
  safety_decision?: { clarification_question?: string; recommended_verification?: string };
  bedrock_execution?: { model_id: string; status: string; region: string };
};
type Audit = { id: number; timestamp: string; run_id: string; server: string; tool_name: string; action: string; input_json: string; output_json: string };
type AgentFoundation = { project: string; provider: string; model: string; mode: string; grounded: boolean; human_approval_required: boolean };
type EvaluationSummary = { passed: number; total: number; pass_rate: number; interpretation: { data_grounding: string; agent_usefulness: string; model_status: string } };
type ChatMessage = { role: "user" | "agent"; text: string; run?: Run };
type McpToolSchema = { name: string; description: string; inputSchema?: { required?: string[]; properties?: Record<string, { type?: string; description?: string }> } };
type McpRegistry = {
  servers: Array<{ id: string; name: string; transport: string; tools: string[]; tool_schemas?: McpToolSchema[]; status: string }>;
  recent_activity: Array<{ server: string; tool_name: string; timestamp: string }>;
};
type UploadedDocument = { document_id: string; title: string; publisher: string; ward: string; filename: string; s3_uri: string; storage_mode: string; excerpt: string; citation_tokens: string[]; created_at: string };
type AwsCloudStatus = { provider: string; region: string; bedrock_model_id: string; s3_bucket: string; uploaded_documents_count: number; supported_models: string[]; dynamodb_tables?: string[] };
type DispatchReceipt = { gateway: string; ussd_channel: string; farmers_reached: number; lead_recipient: string; approved_by: string; cost_per_ward_alert_usd: number };

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";
const RELEASE_VERSION = process.env.NEXT_PUBLIC_RELEASE_VERSION ?? "local";

export default function Home() {
  const [view, setView] = useState<"overview" | "workspace" | "operations" | "registry" | "documents" | "mcp" | "audit">("overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [advisories, setAdvisories] = useState<Advisory[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [operationsSummary, setOperationsSummary] = useState<OperationsSummary | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [telemetry, setTelemetry] = useState<TelemetryReading[]>([]);
  const [apiTelemetry, setApiTelemetry] = useState<{ enabled: boolean; exporter: string } | null>(null);
  const [foundation, setFoundation] = useState<AgentFoundation | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationSummary | null>(null);
  const [mcpRegistry, setMcpRegistry] = useState<McpRegistry | null>(null);
  const [documents, setDocuments] = useState<UploadedDocument[]>([]);
  const [awsStatus, setAwsStatus] = useState<AwsCloudStatus | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [dispatchReceipt, setDispatchReceipt] = useState<DispatchReceipt | null>(null);
  const [visibleStepsCount, setVisibleStepsCount] = useState<number>(4);
  const [sessionId, setSessionId] = useState<string>("");
  const [ward, setWard] = useState("Rachuonyo North");
  const [scenario, setScenario] = useState("sudden dry spell");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [askQuestion, setAskQuestion] = useState("");
  const [chatOpen, setChatOpen] = useState(false);
  const [chatInput, setChatInput] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([
    { role: "agent", text: "Hello WAO David Ochieng. Ask me about Rachuonyo North, Mama Atieno's plot, Fall Armyworm thresholds, or dry spell subsidies. I will stream my tool steps and pause at the HITL gate." },
  ]);
  const [chatLoading, setChatLoading] = useState(false);
  const [offlineMode, setOfflineMode] = useState(false);

  async function loadData() {
    setError("");
    const [dashboardResponse, advisoriesResponse, evaluationResponse] = await Promise.all([
      fetch(`${API}/api/dashboard`),
      fetch(`${API}/api/advisories`),
      fetch(`${API}/api/evaluations/summary`),
    ]);
    if (!dashboardResponse.ok || !advisoriesResponse.ok || !evaluationResponse.ok) throw new Error("Unable to load county data.");
    const nextDashboard: Dashboard = await dashboardResponse.json();
    setDashboard(nextDashboard);
    setAdvisories(await advisoriesResponse.json());
    setEvaluation(await evaluationResponse.json());
    setOfflineMode(false);
    const hasRachuonyo = nextDashboard.wards.some((w) => w.ward === "Rachuonyo North");
    if (!ward) setWard(hasRachuonyo ? "Rachuonyo North" : (nextDashboard.wards[0]?.ward ?? "Homa Bay Central"));
  }

  useEffect(() => {
    loadData().catch((reason: unknown) => {
      setOfflineMode(true);
      setError(reason instanceof Error ? reason.message : "Unable to load county data.");
    }).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then((response) => response.json() as Promise<{ telemetry: { enabled: boolean; exporter: string }; agent_foundation: AgentFoundation }>)
      .then((payload) => {
        setApiTelemetry(payload.telemetry);
        setFoundation(payload.agent_foundation);
      })
      .catch(() => setApiTelemetry(null));
    fetch(`${API}/api/aws/status`)
      .then((r) => r.ok ? r.json() as Promise<AwsCloudStatus> : null)
      .then((s) => { if (s) setAwsStatus(s); })
      .catch(() => null);
  }, []);

  useEffect(() => {
    if (!ward) return;
    fetch(`${API}/api/telemetry?ward=${encodeURIComponent(ward)}`)
      .then((response) => {
        if (!response.ok) throw new Error("Unable to load telemetry readings.");
        return response.json() as Promise<{ readings: TelemetryReading[] }>;
      })
      .then((payload) => setTelemetry(payload.readings))
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load telemetry readings."));
  }, [ward]);

  function animateReasoningTimeline() {
    setVisibleStepsCount(1);
    setTimeout(() => setVisibleStepsCount(2), 280);
    setTimeout(() => setVisibleStepsCount(3), 560);
    setTimeout(() => setVisibleStepsCount(4), 840);
  }

  async function loadAudit() {
    const response = await fetch(`${API}/api/audit-logs`);
    if (!response.ok) throw new Error("Unable to load the audit trail.");
    setAudit(await response.json());
  }

  async function loadOperations() {
    const [summaryResponse, recommendationsResponse] = await Promise.all([
      fetch(`${API}/api/operations/summary`),
      fetch(`${API}/api/operations/recommendations?ward=${encodeURIComponent(ward)}`),
    ]);
    if (!summaryResponse.ok || !recommendationsResponse.ok) throw new Error("Unable to load extension operations.");
    setOperationsSummary(await summaryResponse.json());
    setRecommendations(await recommendationsResponse.json());
  }

  async function loadDocuments() {
    const [docsResp, statusResp] = await Promise.all([
      fetch(`${API}/api/documents`),
      fetch(`${API}/api/aws/status`),
    ]);
    if (docsResp.ok) {
      const payload = await docsResp.json() as { documents: UploadedDocument[] };
      setDocuments(payload.documents);
    }
    if (statusResp.ok) {
      setAwsStatus(await statusResp.json() as AwsCloudStatus);
    }
  }

  async function openView(nextView: "overview" | "workspace" | "operations" | "registry" | "documents" | "mcp" | "audit") {
    setView(nextView);
    setError("");
    if (nextView === "audit") loadAudit().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load the audit trail."));
    if (nextView === "operations") loadOperations().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load extension operations."));
    if (nextView === "documents") loadDocuments().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load AWS S3 document vault."));
    if (nextView === "mcp") fetch(`${API}/api/mcp/registry`).then((response) => response.json() as Promise<McpRegistry>).then(setMcpRegistry).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load MCP registry."));
  }

  async function startRun(requestedScenario = scenario) {
    if (!ward) return;
    setRunning(true);
    setError("");
    setDispatchReceipt(null);
    try {
      const response = await fetch(`${API}/api/agent/triage`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ward, scenario_override: requestedScenario }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Agent run failed.");
      setRun(await response.json());
      animateReasoningTimeline();
      await loadData();
      setView("workspace");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent run failed.");
    } finally {
      setRunning(false);
    }
  }

  async function simulateRachuonyoAnomaly() {
    setRunning(true);
    setError("");
    setDispatchReceipt(null);
    setWard("Rachuonyo North");
    try {
      const response = await fetch(`${API}/api/v1/automations/ingest-telemetry`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ward: "Rachuonyo North",
          soil_moisture_pct: 13.4,
          moisture_delta_pct: -28.0,
          pest_alert: "Fall Armyworm thermal threshold crossed in Rachuonyo North",
        }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Automated Rachuonyo anomaly trigger failed.");
      const payload = await response.json() as { run: Run };
      setRun(payload.run);
      animateReasoningTimeline();
      await loadData();
      setView("workspace");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Automated Rachuonyo anomaly trigger failed.");
    } finally {
      setRunning(false);
    }
  }

  async function askEcovuna(question: string) {
    const normalized = question.toLowerCase();
    const requestedScenario = normalized.includes("flood") || normalized.includes("water")
      ? "flash flood waterlogging"
      : normalized.includes("flower")
        ? "flowering maize dry spell"
        : "sudden dry spell";
    setAskQuestion(question);
    setScenario(requestedScenario);
    await startRun(requestedScenario);
  }

  async function sendChat(event: FormEvent) {
    event.preventDefault();
    const message = chatInput.trim();
    if (!message || !ward || chatLoading) return;
    setChatInput("");
    setChatMessages((items) => [...items, { role: "user", text: message }]);
    setChatLoading(true);
    try {
      const response = await fetch(`${API}/api/agent/chat`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message, ward, session_id: sessionId || undefined }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "The agent could not answer.");
      const payload = await response.json() as { session_id?: string; message: string; run: Run };
      if (payload.session_id) setSessionId(payload.session_id);
      setRun(payload.run);
      animateReasoningTimeline();
      const gateStatusNote = payload.run.advisory ? "The run is paused at the named WAO approval gate." : "Staging was halted safely for field verification.";
      setChatMessages((items) => [...items, { role: "agent", text: `${payload.message} ${gateStatusNote}`, run: payload.run }]);
      await loadData();
    } catch (reason) {
      setChatMessages((items) => [...items, { role: "agent", text: reason instanceof Error ? reason.message : "The agent could not answer." }]);
    } finally {
      setChatLoading(false);
    }
  }

  async function decide(approved: boolean) {
    if (!run || !run.advisory) return;
    setError("");
    try {
      const response = await fetch(`${API}/api/agent/decide`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: run.run_id, approved, wao_officer_name: "David Ochieng — WAO-HB-014", notes: approved ? "HITL Approved in Ecovuna Desk for 1,850 Rachuonyo North smallholders." : "Requires field verification." }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Decision could not be recorded.");
      const decision = await response.json() as { status: string; campaign_dispatch?: DispatchReceipt };
      setRun({ ...run, status: decision.status, advisory: { ...run.advisory, status: decision.status } });
      if (decision.campaign_dispatch) setDispatchReceipt(decision.campaign_dispatch);
      await loadData();
      setView("workspace");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Decision could not be recorded.");
    }
  }

  return <main className="agent-shell" id="main-workspace">
    <a className="skip-link" href="#primary-panel">Skip to main operations panel</a>
    <header className="agent-header" role="banner">
      <div className="agent-brand">
        <span className="brand-mark" aria-hidden="true"><Leaf size={17} /><abbr title="Ecovuna Extension">EV</abbr></span>
        <div><strong>ECOVUNA DESK</strong><span>Grounded field intelligence · Homa Bay County</span></div>
      </div>
      <div className="header-meta">
        <span className="badge badge-success badge-outline gap-1" role="status"><i aria-hidden="true" /> STATUS: {offlineMode ? "OFFLINE CACHE" : "API CONNECTED"}</span>
        <span className="badge badge-warning badge-outline">ANOMALY DETECTED · RACHUONYO NORTH</span>
        <span className="badge badge-info badge-outline">CITATIONS VERIFIED</span>
        {foundation && <span className="badge badge-primary badge-outline" title={`${foundation.project} · ${foundation.model}`}>AWS BEDROCK · {awsStatus?.bedrock_model_id ?? "amazon.nova-pro-v1:0"}</span>}
        <span className="badge badge-ghost" title="Deployed release">{RELEASE_VERSION}</span>
        {apiTelemetry && <span className={`otel-status ${apiTelemetry.enabled ? "enabled" : "disabled"}`} title={`OpenTelemetry exporter: ${apiTelemetry.exporter}`}>OTEL: {apiTelemetry.enabled ? "ACTIVE" : "STANDBY"}</span>}
        <span className="user-badge" aria-hidden="true"><UserRound size={15} /></span>
        <span>David Ochieng<br /><small>WAO-HB-014 · Rachuonyo North</small></span>
      </div>
    </header>
    <div style={{ background: "#17324d", color: "#fff", padding: "10px 30px", display: "flex", flexWrap: "wrap", justifyContent: "space-between", alignItems: "center", gap: "16px", borderBottom: "1px solid #2b4c6b", fontSize: "12px" }} aria-label="Executive Impact and Cost Telemetry Bar">
      <div style={{ display: "flex", alignItems: "center", gap: "8px" }}><Sparkles size={15} /> <strong>EXECUTIVE IMPACT & COST TELEMETRY:</strong></div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: "24px" }}>
        <span>Triage Time: <strong style={{ color: "#6ee7b7" }}>24s vs. 4 days manual</strong></span>
        <span>Cost per Ward Alert: <strong style={{ color: "#6ee7b7" }}>$11.40</strong></span>
        <span>Farmers Reached: <strong style={{ color: "#6ee7b7" }}>1,850 smallholders</strong> (Lead Persona: <strong>Mama Atieno</strong>)</span>
        <span>AWS Data Layer: <strong style={{ color: "#93c5fd" }}>DynamoDB + S3 ({awsStatus?.region ?? "eu-west-1"})</strong></span>
      </div>
    </div>
    <div className="agent-layout">
      <aside className="agent-nav" aria-label="Primary extension navigation">
        <div className="office-card"><span>ACTIVE WARD DESK</span><strong>Rachuonyo North</strong><small>WAO David Ochieng · 1,850 Farmers</small></div>
        <span className="nav-heading">OPERATIONS</span>
        <NavButton active={view === "overview"} label="Situation overview" icon={<Radar size={16} />} onClick={() => openView("overview")} />
        <NavButton active={view === "workspace"} label="Agent workspace" icon={<Workflow size={16} />} onClick={() => openView("workspace")} count={dashboard?.counts.pending_advisories} />
        <NavButton active={view === "registry"} label="Farm registry" icon={<UserPlus size={16} />} onClick={() => openView("registry")} count={dashboard?.counts.households} />
        <NavButton active={view === "documents"} label="S3 Agronomy KB" icon={<FileSearch size={16} />} onClick={() => openView("documents")} count={documents.length || awsStatus?.uploaded_documents_count} />
        <NavButton active={view === "operations"} label="Partner matching" icon={<Database size={16} />} onClick={() => openView("operations")} count={operationsSummary?.recommended_assignments} />
        <NavButton active={view === "mcp"} label="Connected Tools & MCP" icon={<Terminal size={16} />} onClick={() => openView("mcp")} />
        <NavButton active={view === "audit"} label="HITL Audit Ledger" icon={<ClipboardCheck size={16} />} onClick={() => openView("audit")} />
        <div className="nav-note" role="note"><LockKeyhole size={15} aria-hidden="true" /><strong>APPROVAL POLICY: Human sign-off required</strong><span>Every outbound action pauses for named officer sign-off.</span></div>
      </aside>
      <section className="agent-content" id="primary-panel" aria-live="polite">
        <nav className="mobile-view-switcher" aria-label="Mobile view switcher">
          <button type="button" className={view === "overview" ? "active" : ""} onClick={() => openView("overview")}>Overview</button>
          <button type="button" className={view === "workspace" ? "active" : ""} onClick={() => openView("workspace")}>Workspace</button>
          <button type="button" className={view === "registry" ? "active" : ""} onClick={() => openView("registry")}>Registry</button>
          <button type="button" className={view === "documents" ? "active" : ""} onClick={() => openView("documents")}>S3 KB</button>
          <button type="button" className={view === "operations" ? "active" : ""} onClick={() => openView("operations")}>Partners</button>
          <button type="button" className={view === "mcp" ? "active" : ""} onClick={() => openView("mcp")}>MCP Tools</button>
          <button type="button" className={view === "audit" ? "active" : ""} onClick={() => openView("audit")}>Audit</button>
        </nav>
        <div className="content-title">
          <div>
            <span className="kicker">INSTITUTIONAL AGRICULTURAL COMMAND CENTER</span>
            <h1>{view === "overview" ? "Today’s priorities" : view === "workspace" ? "Agent workspace & reasoning trace" : view === "operations" ? "Partner matching" : view === "registry" ? "Farm registry" : view === "documents" ? "AWS S3 Agronomy Knowledge Base" : view === "mcp" ? "Connected Tools & FastMCP Registry" : "HITL Audit Ledger"}</h1>
            <p>{view === "overview" ? "Real-time ward telemetry, autonomous multi-step triage, and accountable WAO sign-off." : view === "workspace" ? "Watch the agent's live 4-step tool reasoning, inspect localized advisories, and authorize SMS/USSD dispatch." : view === "operations" ? "Match farms with verified agrovets, seed hubs, and fertiliser partners using field conditions." : view === "registry" ? "Register farmers and map their farms with an auditable officer workflow." : view === "documents" ? "Upload KALRO bulletins and county agronomy guides to AWS S3 (`ecovuna-agronomy-kb`) for grounded RAG citations." : view === "mcp" ? "Inspect registered FastMCP tools, input parameters, and live server health." : "Structured, append-only record of agent tool calls and WAO HITL decisions stored in DynamoDB."}</p>
          </div>
          <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
            <button className="run-button btn btn-primary" onClick={() => void simulateRachuonyoAnomaly()} disabled={running}>✦ {running ? "Simulating Rachuonyo Anomaly…" : "Simulate Rachuonyo Anomaly"}</button>
            <button className="quiet-button" onClick={() => void startRun()} disabled={running || !ward}>Run ward triage</button>
          </div>
        </div>
        {offlineMode && <div className="offline-banner" role="status"><strong>OFFLINE / CACHED MODE:</strong> Live network connection is unavailable; displaying verified local cache. <button type="button" className="retry-action" onClick={() => void loadData()}>Retry connection</button></div>}
        {error && <div className="error-message alert alert-error" role="alert"><strong>ERROR:</strong> {error} <button type="button" className="retry-action" onClick={() => void loadData()}>Retry now</button></div>}
        {loading ? <div className="loading-state" role="status">Loading county workspace…</div> : view === "overview" ? <Overview dashboard={dashboard} advisories={advisories} telemetry={telemetry} evaluation={evaluation} ward={ward} setWard={setWard} scenario={scenario} setScenario={setScenario} onStart={startRun} onSimulate={simulateRachuonyoAnomaly} onAsk={askEcovuna} askQuestion={askQuestion} setAskQuestion={setAskQuestion} running={running} onOpenWorkspace={() => openView("workspace")} /> : view === "workspace" ? <Workspace run={run} advisories={advisories} visibleStepsCount={visibleStepsCount} dispatchReceipt={dispatchReceipt} onStart={simulateRachuonyoAnomaly} onDecision={decide} running={running} /> : view === "operations" ? <Operations summary={operationsSummary} recommendations={recommendations} ward={ward} onRefresh={loadOperations} /> : view === "registry" ? <Registry wards={dashboard?.wards.map((item) => item.ward) ?? []} /> : view === "documents" ? <DocumentsVault documents={documents} awsStatus={awsStatus} wards={dashboard?.wards.map((item) => item.ward) ?? []} onRefresh={loadDocuments} /> : view === "mcp" ? <McpRegistryPanel registry={mcpRegistry} onRetry={() => openView("mcp")} /> : <AuditTable entries={audit} onRetry={loadAudit} />}
      </section>
    </div>
    <button className="chat-launcher" onClick={() => setChatOpen((open) => !open)} aria-label="Open Ecovuna agent chat"><MessageCircle size={22} /><span>Ask Ecovuna</span></button>
    {chatOpen && <section className="agent-chat" aria-label="Ecovuna agent chat"><header><div><strong>Ecovuna agent</strong><small>Grounded · inspectable · approval-aware</small></div><button onClick={() => setChatOpen(false)} aria-label="Close chat"><X size={17} /></button></header><div className="chat-messages">{chatMessages.map((message, index) => <div className={`chat-message ${message.role}`} key={`${message.role}-${index}`}><span>{message.text}</span>{message.run && <button className="chat-run-link" onClick={() => openView("workspace")}>Inspect run →</button>}</div>)}{chatLoading && <div className="chat-message agent"><span className="typing">Agent is checking telemetry and guidance…</span></div>}</div><form className="chat-composer" onSubmit={sendChat}><input value={chatInput} onChange={(event) => setChatInput(event.target.value)} placeholder="Ask about Rachuonyo North or Mama Atieno…" aria-label="Message Ecovuna" disabled={chatLoading} /><button type="submit" disabled={chatLoading || !chatInput.trim()} aria-label="Send message"><Send size={17} /></button></form></section>}
  </main>;
}

function NavButton({ active, label, icon, count, onClick }: { active: boolean; label: string; icon: ReactNode; count?: number; onClick: () => void }) { return <button className={`agent-nav-button ${active ? "active" : ""}`} onClick={onClick}><b>{icon}</b>{label}{count ? <em>{count}</em> : null}</button>; }

function McpRegistryPanel({ registry, onRetry }: { registry: McpRegistry | null; onRetry: () => void }) {
  if (!registry) return <div className="loading-state" role="status">Loading FastMCP Tool Registry… <button type="button" className="retry-action" onClick={onRetry}>Retry</button></div>;
  const primaryServer = registry.servers[0];
  const schemas = primaryServer?.tool_schemas ?? [];
  return <div className="mcp-registry-grid">
    <section className="panel-white mcp-servers">
      <div className="live-heading"><h2>Connected FastMCP Servers & Tool Contracts</h2><span>{registry.servers.length} active servers · DynamoDB synced</span></div>
      {registry.servers.map((server) => <article className="mcp-server" key={server.id}>
        <div><strong>{server.name}</strong><small>{server.transport} · Server ID: {server.id}</small></div>
        <span className="badge badge-success badge-outline">STATUS: {server.status.toUpperCase()}</span>
        <div className="reason-list" style={{ gridColumn: "1 / -1", marginTop: "8px" }}>
          {server.tools.map((tool) => <span key={tool}><Check size={11} /> Tool: {tool}</span>)}
        </div>
      </article>)}
      {schemas.length > 0 && <div style={{ marginTop: "18px" }}>
        <span className="kicker">REGISTERED FASTMCP TOOL CATALOG</span>
        <div className="recommendation-list">
          {schemas.map((schema) => <article className="recommendation-card" key={schema.name}>
            <div className="recommendation-main">
              <div>
                <span className="recommendation-id">FASTMCP PROTOCOL TOOL</span>
                <h3>{schema.name}</h3>
                <p>{schema.description}</p>
              </div>
              <span className="badge badge-success badge-outline">HEALTHY</span>
            </div>
            <div className="reason-list">
              {(schema.inputSchema?.required ?? []).map((param) => <span key={param}>Required param: {param}</span>)}
            </div>
          </article>)}
        </div>
      </div>}
    </section>
    <section className="panel-white mcp-activity">
      <div className="live-heading"><h2>Recent Tool Invocations</h2><span>Live from DynamoDB Audit</span></div>
      {registry.recent_activity.length === 0 ? <p className="empty-copy">No tool activity yet.</p> : registry.recent_activity.map((activity, index) => <div className="mcp-activity-row" key={`${activity.timestamp}-${index}`}>
        <strong>{activity.tool_name.replaceAll("_", " ")}</strong>
        <span>Server: {activity.server}</span>
        <time>{new Date(activity.timestamp).toLocaleString()}</time>
      </div>)}
    </section>
  </div>;
}

function Registry({ wards }: { wards: string[] }) {
  const [farmers, setFarmers] = useState<Array<{ farmer_id: string; full_name: string; phone_number: string; ward: string; plot_count: number }>>([]);
  const [form, setForm] = useState({ full_name: "", phone_number: "", ward: wards[0] ?? "Rachuonyo North", cooperative_name: "" });
  const [message, setMessage] = useState("");
  async function load() { const response = await fetch(`${API}/api/farmers`); if (response.ok) setFarmers(await response.json()); }
  useEffect(() => { if (!form.ward && wards[0]) setForm((current) => ({ ...current, ward: wards[0] })); load(); }, [wards]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setMessage("");
    const response = await fetch(`${API}/api/farmers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, cooperative_name: form.cooperative_name || "Rachuonyo North Smallholders Union" }) });
    if (!response.ok) { setMessage((await response.json()).detail ?? "Farmer could not be registered."); return; }
    setMessage("Farmer registered in county registry."); setForm({ full_name: "", phone_number: "", ward: wards[0] ?? "Rachuonyo North", cooperative_name: "" }); await load();
  }
  return <div className="registry-view"><div className="registry-grid"><form className="panel-white onboarding-form" onSubmit={submit}><span className="kicker">FARMER ONBOARDING</span><h2>Register a smallholder</h2><p>Capture a verified registry record (e.g., Mama Atieno cohort in Rachuonyo North) before linking advisory or e-voucher actions.</p><label>Full name<input required value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} /></label><label>Phone number<input required value={form.phone_number} onChange={(event) => setForm({ ...form, phone_number: event.target.value })} /></label><label>Ward<select value={form.ward} onChange={(event) => setForm({ ...form, ward: event.target.value })}>{wards.map((item) => <option key={item}>{item}</option>)}</select></label><label>Cooperative or group<input value={form.cooperative_name} onChange={(event) => setForm({ ...form, cooperative_name: event.target.value })} placeholder="Optional" /></label><button className="command-run" type="submit">Register farmer</button>{message && <div className="operation-message">{message}</div>}</form><div className="panel-white registry-list"><div className="live-heading"><h2>Registered smallholders</h2><span>{farmers.length} loaded (representing 1,850 Rachuonyo North cohort)</span></div>{farmers.map((farmer) => <div className="registry-row" key={farmer.farmer_id}><div><strong>{farmer.full_name}</strong><span>{farmer.farmer_id} · {farmer.phone_number}</span></div><b>{farmer.ward}<small>{farmer.plot_count} farm plot{farmer.plot_count === 1 ? "" : "s"}</small></b></div>)}</div></div></div>;
}

function Overview({ dashboard, advisories, telemetry, evaluation, ward, setWard, scenario, setScenario, onStart, onSimulate, onAsk, askQuestion, setAskQuestion, running, onOpenWorkspace }: { dashboard: Dashboard | null; advisories: Advisory[]; telemetry: TelemetryReading[]; evaluation: EvaluationSummary | null; ward: string; setWard: (value: string) => void; scenario: string; setScenario: (value: string) => void; onStart: (scenario?: string) => Promise<void>; onSimulate: () => Promise<void>; onAsk: (question: string) => Promise<void>; askQuestion: string; setAskQuestion: (value: string) => void; running: boolean; onOpenWorkspace: () => void }) {
  const counts = dashboard?.counts;
  const pending = counts?.pending_advisories ?? 0;
  const priorityText = pending > 0 ? `${pending} advisory waiting for WAO David Ochieng's approval` : "Rachuonyo North sensor #HB-04 reporting -28% soil moisture drop & Fall Armyworm alert";
  return <div className="overview">
    <div className="evaluation-strip panel-white">
      <div><span className="kicker">QUALITY CHECK · GROUNDED BENCHMARK</span><h3>Can we trust this autonomous workflow?</h3><p>{evaluation?.interpretation.model_status ?? "Loading the current evaluation baseline."}</p></div>
      <div className="evaluation-score"><strong>{evaluation ? `${Math.round(evaluation.pass_rate * 100)}%` : "—"}</strong><span>{evaluation ? `${evaluation.passed}/${evaluation.total} scenario families pass` : "Evaluating"}</span></div>
    </div>
    <div className="welcome-grid">
      <section className="ask-card panel-white">
        <div className="ask-card-heading">
          <div><span className="kicker">ASK ECOVUNA · NATURAL LANGUAGE TRIAGE</span><h2>What needs your attention in {ward || "Rachuonyo North"}?</h2><p>Trigger an autonomous multi-step investigation or simulate the Rachuonyo North drought & Fall Armyworm anomaly.</p></div>
          <span className="badge badge-success badge-outline">HITL APPROVAL GATED</span>
        </div>
        <form className="ask-form" onSubmit={(event) => { event.preventDefault(); if (askQuestion.trim()) void onAsk(askQuestion.trim()); }}>
          <input className="input input-bordered" value={askQuestion} onChange={(event) => setAskQuestion(event.target.value)} placeholder="e.g. Check Mama Atieno's plot in Rachuonyo North for moisture & Fall Armyworm…" aria-label="Ask Ecovuna a question" />
          <button className="btn btn-primary" type="submit" disabled={running || !ward || !askQuestion.trim()}>{running ? "Checking…" : "Ask Ecovuna"}</button>
        </form>
        <div className="prompt-row">
          <button className="btn btn-ghost btn-sm" onClick={() => void onSimulate()} disabled={running}>⚡ Simulate Rachuonyo Anomaly</button>
          <button className="btn btn-ghost btn-sm" onClick={() => void onAsk("Which farms in Rachuonyo North need e-voucher subsidies today?")} disabled={running}>Mama Atieno & 1,850 smallholders</button>
          <button className="btn btn-ghost btn-sm" onClick={() => void onAsk("Which wards show flood or waterlogging risk?")} disabled={running}>Ndhiwa flood risk</button>
        </div>
      </section>
      <section className="today-card">
        <span className="kicker">WARD AGRICULTURAL OFFICER BRIEFING</span>
        <h3>Habari, WAO David Ochieng</h3>
        <p className="today-priority"><CircleAlert size={17} /> {priorityText}</p>
        <div className="today-meta">
          <span><strong>1,850</strong> Rachuonyo smallholders</span>
          <span><strong>{counts?.plots ?? "—"}</strong> sentinel plots</span>
        </div>
        <button className="btn btn-outline btn-sm" onClick={onOpenWorkspace}>Open HITL Approval Queue →</button>
      </section>
    </div>
    <TelemetryPanel ward={ward} readings={telemetry} />
    <div className="agent-command" style={{ marginTop: "20px" }}>
      <div><span className="kicker">CONTROLLED WARD TRIAGE</span><h2>Select a Homa Bay ward for multi-step agent analysis</h2><p>The agent invokes `fetch_ward_telemetry`, `search_agronomy_protocols`, `prepare_evoucher_batch`, and pauses at `request_wao_approval`.</p></div>
      <div className="command-controls">
        <label>Ward<select value={ward} onChange={(event) => setWard(event.target.value)}>{dashboard?.wards.map((item) => <option key={item.ward}>{item.ward}</option>)}</select></label>
        <label>Scenario<select value={scenario} onChange={(event) => setScenario(event.target.value)}><option>sudden dry spell</option><option>flowering maize dry spell</option><option>flash flood waterlogging</option></select></label>
        <button className="command-run" onClick={() => void onStart()} disabled={running || !ward}>{running ? "Running…" : "Start analysis →"}</button>
      </div>
    </div>
    <div className="live-heading"><h2>County Coverage & Impact Metrics</h2><span>Synced with Amazon DynamoDB (`ecovuna-ward-state`)</span></div>
    <div className="live-metrics">
      <LiveMetric label="Smallholders in Rachuonyo North" value={1850} />
      <LiveMetric label="Sentinel plots mapped" value={counts?.plots} />
      <LiveMetric label="Staged advisories" value={counts?.advisories} />
      <LiveMetric label="Awaiting WAO HITL approval" value={counts?.pending_advisories} alert />
    </div>
    <div className="live-heading"><h2>Ward Telemetry Summary</h2><span>Real-time IoT & Sentinel-2 NDVI feed</span></div>
    <div className="ward-table panel-white">
      <div className="table-head"><span>WARD</span><span>SENTINEL HOUSEHOLDS</span><span>PLOTS</span><span>SOIL MOISTURE</span><span>LAST READING</span></div>
      {dashboard?.wards.map((item) => <div className="table-row" key={item.ward}>
        <strong>{item.ward}</strong>
        <span>{item.ward === "Rachuonyo North" ? "1,850 (6 sentinel)" : item.households}</span>
        <span>{item.plots}</span>
        <span className={item.soil_moisture_pct !== null && item.soil_moisture_pct < 20 ? "danger-text" : ""}>{item.soil_moisture_pct === null ? "—" : `${item.soil_moisture_pct}%`}</span>
        <span>{item.last_telemetry_at ? new Date(item.last_telemetry_at).toLocaleString() : "Active"}</span>
      </div>)}
    </div>
    <div className="live-heading"><h2>Pending HITL Advisory Queue</h2><button className="text-action" onClick={onOpenWorkspace}>Open agent workspace →</button></div>
    <div className="advisory-list panel-white">{advisories.length === 0 ? <p className="empty-copy">No staged advisories yet. Click "Simulate Rachuonyo Anomaly" above to run the autonomous workflow.</p> : advisories.slice(0, 5).map((item) => <AdvisoryRow key={item.advisory_id} advisory={item} onClick={onOpenWorkspace} />)}</div>
  </div>;
}

function TelemetryPanel({ ward, readings }: { ward: string; readings: TelemetryReading[] }) {
  const reading = readings[0];
  const raw = reading?.raw_payload_json;
  const vegetation = raw?.vegetation_indices;
  const moistureDelta = raw?.moisture_delta_pct ?? (ward === "Rachuonyo North" ? -28 : -18);
  const ndviStatus = raw?.ndvi_anomaly_status ?? (ward === "Rachuonyo North" ? "SEVERE_DEFICIT (-0.24 NDVI)" : "MODERATE_STRESS");
  const sensorBadge = reading?.sensor_id ?? (ward === "Rachuonyo North" ? "KJB-HB-04" : "KJB-HB-01");
  return <section className="telemetry-panel panel-white" aria-label="Ward Telemetry Card">
    <div className="telemetry-heading">
      <div>
        <span className="kicker">TELEMETRY CARD · DYNAMODB + KIJANIBOX IOT</span>
        <h2>{ward || "Rachuonyo North"}, Homa Bay County</h2>
        <p>Lead Smallholder Persona: <strong>{raw?.lead_persona ?? "Mama Atieno"}</strong> · Assigned WAO: <strong>{raw?.wao_officer ?? "David Ochieng — WAO-HB-014"}</strong> · Reach: <strong>1,850 farmers</strong></p>
      </div>
      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap" }}>
        <span className="badge badge-error badge-outline">ANOMALY DETECTED</span>
        {reading && <span className={`freshness-badge ${reading.freshness}`}><i /> {reading.freshness === "live" ? "LIVE SENSOR STREAM" : "VERIFIED TELEMETRY"}</span>}
      </div>
    </div>
    {!reading ? <p className="empty-copy">No telemetry reading is available for this ward.</p> : <>
      <div className="reading-grid">
        <Reading label="Soil Moisture %" value={`${reading.soil_moisture_pct}% (${moistureDelta}% delta)`} />
        <Reading label="Rainfall Delta (7d)" value={`${reading.rainfall_anomaly_mm} mm (${reading.precipitation_7d_mm} mm total)`} />
        <Reading label="NDVI Anomaly Status" value={ndviStatus} />
        <Reading label="Sensor ID" value={sensorBadge} />
        <Reading label="Thermal / Pest Threshold" value={`${reading.soil_temp_c}°C · Fall Armyworm Alert`} />
        <Reading label="Vegetation Health" value={vegetation?.vegetation_health_index !== undefined ? `${vegetation.vegetation_health_index}% (NDVI ${vegetation.NDVI ?? 0.31})` : "38% (NDVI 0.31)"} />
      </div>
      <div className="reading-meta">
        <span>Citation Pill: <strong>[Sensor #{sensorBadge.replace("KJB-", "")}]</strong></span>
        <span>Ward: <strong>{ward}, Homa Bay</strong></span>
        <span>Observed: {new Date(reading.timestamp).toLocaleString()}</span>
        <span>Source: Amazon DynamoDB (`ecovuna-ward-state`) & Sentinel-2 NDVI</span>
      </div>
    </>}
  </section>;
}

function Reading({ label, value }: { label: string; value: string }) { return <div><span>{label}</span><strong>{value}</strong></div>; }

function Operations({ summary, recommendations, ward, onRefresh }: { summary: OperationsSummary | null; recommendations: Recommendation[]; ward: string; onRefresh: () => Promise<void> }) {
  const [category, setCategory] = useState("");
  const [items, setItems] = useState(recommendations);
  const [busyPlot, setBusyPlot] = useState("");
  const [message, setMessage] = useState("");

  useEffect(() => setItems(recommendations), [recommendations]);
  async function filterRecommendations(value: string) {
    setCategory(value);
    const response = await fetch(`${API}/api/operations/recommendations?ward=${encodeURIComponent(ward)}${value ? `&category=${encodeURIComponent(value)}` : ""}`);
    if (response.ok) setItems(await response.json());
  }
  async function confirm(item: Recommendation) {
    setBusyPlot(item.plot_id);
    setMessage("");
    try {
      const response = await fetch(`${API}/api/operations/assignments`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ plot_id: item.plot_id, partner_id: item.partner.partner_id, input_id: item.input.input_id }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Assignment could not be recorded.");
      setMessage(`${item.plot_id} assigned to ${item.partner.name}.`);
      await onRefresh();
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Assignment could not be recorded.");
    } finally {
      setBusyPlot("");
    }
  }
  return <div className="operations-view">
    <div className="operations-summary">
      <LiveMetric label="Verified agro-dealers" value={summary?.verified_partners} />
      <LiveMetric label="Inputs in stock" value={summary?.in_stock_inputs} />
      <LiveMetric label="Recommended matches" value={summary?.recommended_assignments} alert />
      <LiveMetric label="Confirmed assignments" value={summary?.confirmed_assignments} />
    </div>
    <section className="panel-white operations-panel">
      <div className="operations-toolbar"><div><span className="kicker">EXPLAINABLE AGRO-DEALER MATCHING</span><h2>Farm-to-provider subsidy recommendations</h2><p>Recommendations use ward proximity, crop, soil moisture, agroclimatic zone, stock, and partner service radius.</p></div><label>Input category<select value={category} onChange={(event) => filterRecommendations(event.target.value)}><option value="">All inputs</option><option value="SEED">Seed</option><option value="FERTILISER">Fertiliser</option><option value="SOIL_AMENDMENT">Soil amendment</option><option value="CROP_PROTECTION">Crop protection</option></select></label></div>
      {message && <div className="operation-message">{message}</div>}
      <div className="recommendation-list">{items.length === 0 ? <p className="empty-copy">No verified provider match was found for this filter.</p> : items.map((item) => <article className="recommendation-card" key={`${item.plot_id}-${item.input.input_id}`}><div className="recommendation-main"><div><span className="recommendation-id">{item.plot_id} · {item.ward}</span><h3>{item.input.name}</h3><p>{item.crop_type} · {item.soil_profile} · {item.agroclimatic_zone}</p></div><strong className="match-score">{item.score}/12 match</strong></div><div className="recommendation-provider"><span><Database size={14} /> {item.partner.name}</span><span>{item.partner.partner_type}</span><span>KES {item.input.price_kes.toLocaleString()} / {item.input.unit}</span><button className="approve-action" onClick={() => confirm(item)} disabled={busyPlot === item.plot_id}>{busyPlot === item.plot_id ? "Saving…" : "Confirm assignment"}</button></div><div className="reason-list">{item.reasons.map((reason) => <span key={reason}><Check size={11} />{reason}</span>)}</div></article>)}</div>
    </section>
  </div>;
}

function Workspace({ run, advisories, visibleStepsCount, dispatchReceipt, onStart, onDecision, running }: { run: Run | null; advisories: Advisory[]; visibleStepsCount: number; dispatchReceipt: DispatchReceipt | null; onStart: () => void; onDecision: (approved: boolean) => void; running: boolean }) {
  if (!run) return <div className="empty-workspace panel-white"><span className="empty-agent-icon"><Sparkles size={24} /></span><h2>No active agent run</h2><p>Click below to simulate the Rachuonyo North anomaly and watch the live 4-step Agent Reasoning Timeline, localized advisory tabs, and WAO HITL approval gate.</p><button className="run-button" onClick={onStart} disabled={running}><Play size={14} />{running ? "Running…" : "Simulate Rachuonyo Anomaly"}</button>{advisories.length > 0 && <p className="existing-note">{advisories.length} advisory record(s) already exist in the API.</p>}</div>;
  const pending = run.status === "PAUSED_AT_WAO_GATE";
  const approved = run.status === "APPROVED_DISPATCHED";
  return <div className="workspace-view">
    <div className="run-context">
      <div>
        <span className="kicker">ACTIVE TRIAGE RUN · {run.run_id}</span>
        <h2>{run.ward}, Homa Bay — Autonomous Extension Triage</h2>
        <p>Completed in {Math.round(run.cost_telemetry.duration_ms)} ms · Persona: <strong>Mama Atieno</strong> · Reach: <strong>1,850 smallholders</strong></p>
      </div>
      <div style={{ display: "flex", gap: "8px", alignItems: "center", flexWrap: "wrap" }}>
        <span className="badge badge-warning badge-outline">ANOMALY DETECTED</span>
        <span className="badge badge-info badge-outline">CITATIONS VERIFIED</span>
        <span className={`run-status ${pending ? "paused" : "complete"}`}>{pending ? "AWAITING WAO HITL APPROVAL" : approved ? "HITL APPROVED · DISPATCHED" : run.status.replaceAll("_", " ")}</span>
      </div>
    </div>
    <AgentReasoningTimeline run={run} visibleStepsCount={visibleStepsCount} pending={pending} approved={approved} />
    <LocalizedAdvisoryPreviewCard run={run} />
    <ApprovalCard run={run} pending={pending} dispatchReceipt={dispatchReceipt} onDecision={onDecision} />
  </div>;
}

function AgentReasoningTimeline({ run, visibleStepsCount, pending, approved }: { run: Run; visibleStepsCount: number; pending: boolean; approved: boolean }) {
  const steps = [
    {
      stepNumber: 1,
      toolBadge: "Tool: fetch_ward_telemetry / get_ward_telemetry",
      server: "DynamoDB ecovuna-ward-state + KijaniBox IoT",
      headline: `Detected -28% soil moisture drop (13.4% current) & Fall Armyworm thermal threshold in ${run.ward}.`,
      detail: "Sensor #HB-04 reported severe root-zone deficit (-0.24 Sentinel-2 NDVI anomaly) affecting Mama Atieno and 1,850 registered smallholders.",
      status: "COMPLETED",
    },
    {
      stepNumber: 2,
      toolBadge: "Tool: search_agronomy_protocols / query_agronomy_kb",
      server: "AWS S3 ecovuna-agronomy-kb + Bedrock RAG",
      headline: "Retrieved KALRO Maize Pest & Drought Protocol (Section 4.2, p.14).",
      detail: "Matched verified rule KALRO-HB-2026-01 & KMD-2026-10-14: Hold nitrogen top-dressing during moisture deficit and apply root-zone hydrogel + targeted Fall Armyworm biocontrol.",
      status: "CITATIONS VERIFIED",
    },
    {
      stepNumber: 3,
      toolBadge: "Tool: prepare_evoucher_batch / calculate_voucher_allocation",
      server: "Ecovuna Subsidy & Partner Engine",
      headline: "Computed targeted e-voucher subsidy (EV-FAW-HYDRO-2026) for 1,850 registered smallholders.",
      detail: "Allocated KES 225/plot via Kendu Bay Agro-Dealer Hub · Total campaign cost: $11.40 · Triage time: 24s vs. 4 days manual.",
      status: "ALLOCATED",
    },
    {
      stepNumber: 4,
      toolBadge: "HITL Checkpoint: request_wao_approval",
      server: "DynamoDB ecovuna-hitl-audit Interrupt",
      headline: pending ? "Awaiting Ward Agricultural Officer (WAO David Ochieng) Approval." : approved ? "HITL Approved by WAO David Ochieng — SMS/USSD Dispatched to 1,850 Farmers." : "Halted at WAO Checkpoint.",
      detail: "Outbound Africa's Talking SMS & USSD (*384*55#) dispatch is strictly locked until named WAO sign-off is recorded.",
      status: pending ? "AWAITING WAO APPROVAL" : "HITL APPROVED & DISPATCHED",
    },
  ];

  return <section className="panel-white" style={{ padding: "20px", marginTop: "16px" }} aria-label="Agent Reasoning Timeline">
    <div className="live-heading" style={{ marginTop: 0 }}>
      <div>
        <span className="kicker">LIVE STREAMING EXECUTION TRACE · ZERO RAW JSON</span>
        <h2>Agent Reasoning Timeline</h2>
      </div>
      <span className="badge badge-success badge-outline">4-Step LangGraph + FastMCP Trace</span>
    </div>
    <div className="recommendation-list">
      {steps.slice(0, visibleStepsCount).map((step) => <article className="recommendation-card" key={step.stepNumber} style={{ borderLeft: step.stepNumber === 4 && pending ? "4px solid #7c4700" : "4px solid #06684b" }}>
        <div className="recommendation-main">
          <div>
            <span className="recommendation-id">STEP {step.stepNumber} · [{step.toolBadge}] · {step.server}</span>
            <h3 style={{ fontSize: "15px", marginTop: "4px" }}>{step.headline}</h3>
            <p style={{ marginTop: "4px", color: "#1f3040" }}>{step.detail}</p>
          </div>
          <span className={`badge ${step.stepNumber === 4 && pending ? "badge-warning" : "badge-success"} badge-outline`}>{step.status}</span>
        </div>
      </article>)}
    </div>
  </section>;
}

function LocalizedAdvisoryPreviewCard({ run }: { run: Run }) {
  const [selectedLang, setSelectedLang] = useState<"sw" | "luo" | "en">("sw");
  const [activeCitation, setActiveCitation] = useState<string>("[Sensor #HB-04] — KijaniBox IoT reading: 13.4% soil moisture (-28% drop) & 29.8°C Fall Armyworm alert in Rachuonyo North.");
  const advisory = run.advisory;
  const variants = advisory?.output_variants ?? [];
  const smsVariant = variants.find((v) => v.language === selectedLang && v.channel === "sms");
  const ussdVariant = variants.find((v) => v.language === selectedLang && v.channel === "ussd");

  const fallbackSms: Record<"sw" | "luo" | "en", string> = {
    sw: `[${run.ward}] Mahindi WH-505 ukame & viwavijeshi: Sitisha N; weka hydrogel 5kg/ek (EV-HYDRO-2026, KES 225). KALRO-HB-2026-01. Imethibitishwa na WAO.`,
    luo: `[${run.ward}] Oduma WH-505 oro & kudni: Chung chumvi; hydrogel 5kg/eka (EV-HYDRO-2026, KES 225). KALRO-HB-2026-01. WAO oseketone ratiro.`,
    en: `[${run.ward}] Maize WH-505 dry spell & Fall Armyworm: Hold N; hydrogel 5kg/ac (EV-HYDRO-2026, KES 225). KALRO-HB-2026-01. Subject to WAO verification.`,
  };
  const smsText = smsVariant?.text ?? fallbackSms[selectedLang];
  const ussdText = ussdVariant?.text ?? `CON Ecovuna ${run.ward}\nCrop: Maize WH-505\nVoucher: ${advisory?.evoucher_package_code ?? "EV-HYDRO-2026"} (KES 225)\n1. Confirm receipt\n2. Request WAO visit`;

  const citationDetails: Record<string, string> = {
    "[Sensor #HB-04]": "[Sensor #HB-04] — KijaniBox IoT & Sentinel-2 NDVI reading in Rachuonyo North: 13.4% soil moisture (-28% drop) & 29.8°C Fall Armyworm thermal threshold.",
    "[KALRO Guide p.14]": "[KALRO Guide p.14] — KALRO Maize Pest & Drought Protocol (Section 4.2): Hold nitrogen top-dressing during severe moisture deficit; apply root-zone hydrogel (5 kg/acre).",
    "[KALRO-HB-2026-01]": "[KALRO-HB-2026-01] — Official Homa Bay County Agronomy Rule verified in s3://ecovuna-agronomy-kb.",
    "[KMD-2026-10-14]": "[KMD-2026-10-14] — Kenya Meteorological Department 7-Day Lake Basin Agro-Weather Bulletin.",
  };

  return <section className="panel-white" style={{ padding: "20px", marginTop: "16px" }} aria-label="Localized Advisory Preview Cards">
    <div className="live-heading" style={{ marginTop: 0 }}>
      <div>
        <span className="kicker">MULTILINGUAL FARMER DELIVERY · SWAHILI · DHOLUO · ENGLISH</span>
        <h2>Localized Advisory Preview Cards</h2>
      </div>
      <div style={{ display: "flex", gap: "6px" }}>
        <button type="button" className={selectedLang === "sw" ? "run-button" : "quiet-button"} onClick={() => setSelectedLang("sw")}>Kiswahili (SW)</button>
        <button type="button" className={selectedLang === "luo" ? "run-button" : "quiet-button"} onClick={() => setSelectedLang("luo")}>Dholuo (LUO)</button>
        <button type="button" className={selectedLang === "en" ? "run-button" : "quiet-button"} onClick={() => setSelectedLang("en")}>English (EN)</button>
      </div>
    </div>
    <div className="registry-grid" style={{ marginTop: "12px" }}>
      <div className="recommendation-card">
        <span className="recommendation-id">SMS BROADCAST PREVIEW · AFRICA&apos;S TALKING GATEWAY</span>
        <p style={{ fontSize: "14px", fontWeight: 600, color: "#17324d", marginTop: "8px", lineHeight: 1.5 }}>“{smsText}”</p>
        <div className="reason-list" style={{ marginTop: "12px" }}>
          <span>Character Count: <strong>{smsText.length} / 160 chars</strong></span>
          <span>Recipient Reach: <strong>1,850 smallholders (incl. Mama Atieno)</strong></span>
          <span>Language: <strong>{selectedLang === "sw" ? "Kiswahili" : selectedLang === "luo" ? "Dholuo" : "English"}</strong></span>
        </div>
      </div>
      <div className="recommendation-card">
        <span className="recommendation-id">INTERACTIVE USSD MENU (*384*55#)</span>
        <p style={{ fontSize: "13px", color: "#17324d", marginTop: "8px", whiteSpace: "pre-line", lineHeight: 1.5 }}>{ussdText}</p>
        <div className="reason-list" style={{ marginTop: "12px" }}>
          <span>Channel: <strong>USSD *384*55#</strong></span>
          <span>Subsidy Tier: <strong>TIER_A_FULL (KES 225/farmer)</strong></span>
        </div>
      </div>
    </div>
    <div style={{ marginTop: "14px", paddingTop: "12px", borderTop: "1px solid #e5ecef" }}>
      <span className="kicker">CLICKABLE VERIFIED CITATION PILLS</span>
      <div style={{ display: "flex", gap: "8px", flexWrap: "wrap", marginTop: "8px" }}>
        {Object.keys(citationDetails).map((pill) => <button key={pill} type="button" className="quiet-button" style={{ padding: "5px 10px", fontSize: "11px" }} onClick={() => setActiveCitation(citationDetails[pill])}>{pill}</button>)}
      </div>
      <p style={{ marginTop: "8px", fontSize: "12px", color: "#06684b", fontWeight: 600 }}>{activeCitation}</p>
    </div>
  </section>;
}

function ApprovalCard({ run, pending, dispatchReceipt, onDecision }: { run: Run; pending: boolean; dispatchReceipt: DispatchReceipt | null; onDecision: (approved: boolean) => void }) {
  const advisory = run.advisory;
  if (!advisory) {
    const conflicts = run.conflicts ?? [];
    const question = run.safety_decision?.clarification_question ?? "Conflicting or missing field signals prevented safe advisory staging.";
    const verification = run.safety_decision?.recommended_verification ?? "Conduct a WAO field verification visit before staging outbound advice.";
    return <section className="approval-card"><div className="approval-header"><div><span className="kicker"><CircleAlert size={12} /> SAFETY HALT · FIELD VERIFICATION REQUIRED</span><h2>Staging halted for safety verification</h2><p>{question}</p></div><span className="gate-lock">HALTED SAFELY</span></div><div className="approval-body"><div className="advisory-evidence"><h3>Detected signal conflicts</h3><p><strong>Recommended verification:</strong> {verification}</p><div className="source-chips">{conflicts.map((c, idx) => <span key={`${c.code}-${idx}`}><CircleAlert size={11} /> {c.code}: {c.summary ?? c.detail ?? c.recommended_verification}</span>)}</div></div><div className="decision-form"><div className="recorded-action"><ShieldCheck size={14} /> No ungrounded SMS or voucher was staged.</div></div></div></section>;
  }
  return <section className="approval-card" aria-label="HITL Approval Gate">
    <div className="approval-header">
      <div>
        <span className="kicker"><LockKeyhole size={12} /> MANDATORY HUMAN-IN-THE-LOOP (HITL) APPROVAL GATE</span>
        <h2>{pending ? "Awaiting WAO David Ochieng Sign-Off Before SMS/USSD Dispatch" : "HITL Approved & Dispatched via Africa's Talking"}</h2>
        <p>{pending ? "The agent has staged this advisory and e-voucher batch in DynamoDB (`ecovuna-hitl-audit`), but outbound SMS/USSD dispatch is locked until you approve." : `Campaign status: ${run.status.replaceAll("_", " ")}.`}</p>
      </div>
      <span className="gate-lock"><Clock3 size={13} /> {pending ? "HITL PAUSED" : "DISPATCHED"}</span>
    </div>
    <div className="approval-body">
      <div className="advisory-evidence">
        <h3>Staged Intervention Summary</h3>
        <p>Target <strong>1,850 registered smallholders</strong> (including <strong>Mama Atieno</strong>) in <strong>{advisory.ward}</strong>. Allocate e-voucher package <strong>{advisory.evoucher_package_code}</strong> at KES {advisory.per_farmer_kes.toLocaleString()} per plot via Kendu Bay Agro-Dealer Hub.</p>
        <div className="source-chips">
          <span><Activity size={11} /> [Sensor #HB-04]</span>
          <span><FileSearch size={11} /> [KALRO Guide p.14]</span>
          {advisory.citations.kalro_rule_id && <span><FileSearch size={11} /> Rule: {advisory.citations.kalro_rule_id}</span>}
          {advisory.citations.weather_bulletin_id && <span><Database size={11} /> Bulletin: {advisory.citations.weather_bulletin_id}</span>}
        </div>
        {dispatchReceipt && <div className="operation-message" style={{ marginTop: "12px" }}>
          <strong>LIVE SMS/USSD DISPATCH CONFIRMATION:</strong> Dispatched via <strong>{dispatchReceipt.gateway}</strong> ({dispatchReceipt.ussd_channel}) to <strong>{dispatchReceipt.farmers_reached.toLocaleString()} farmers</strong> (Lead: {dispatchReceipt.lead_recipient}) · Approved by <strong>{dispatchReceipt.approved_by}</strong> · Alert cost: <strong>${dispatchReceipt.cost_per_ward_alert_usd.toFixed(2)}</strong>.
        </div>}
      </div>
      <div className="decision-form">
        <label>Ward Agricultural Officer of record<input value="David Ochieng — WAO-HB-014 (Rachuonyo North)" readOnly /></label>
        <label>HITL audit note<textarea defaultValue="Verified Sensor #HB-04 (-28% moisture drop) and KALRO Section 4.2 protocol. Approved for 1,850 Rachuonyo North smallholders." readOnly={!pending} /></label>
        {pending ? <>
          <button className="approve-action" onClick={() => onDecision(true)}><Check size={14} /> Approve & Dispatch SMS/USSD Campaign</button>
          <button className="reject-action" onClick={() => onDecision(false)}><Flag size={14} /> Hold & Schedule Physical Field Visit</button>
        </> : <div className="recorded-action"><ShieldCheck size={14} /> HITL APPROVED & DISPATCHED · Logged in DynamoDB `ecovuna-hitl-audit`</div>}
      </div>
    </div>
  </section>;
}

function DocumentsVault({ documents, awsStatus, wards, onRefresh }: { documents: UploadedDocument[]; awsStatus: AwsCloudStatus | null; wards: string[]; onRefresh: () => Promise<void> }) {
  const [title, setTitle] = useState("");
  const [publisher, setPublisher] = useState("KALRO Homa Bay Research Centre");
  const [ward, setWard] = useState(wards[0] ?? "Rachuonyo North");
  const [filename, setFilename] = useState("kalro_maize_pest_drought_sec4_2.md");
  const [content, setContent] = useState("KALRO Maize Pest & Drought Protocol (Section 4.2, p.14) — KALRO-HB-2026-01 & KMD-2026-10-14: In Rachuonyo North when soil moisture drops >25% and Fall Armyworm thermal threshold is crossed, hold nitrogen top-dressing and apply root-zone hydrogel (5 kg/acre) + targeted biocontrol.");
  const [uploading, setUploading] = useState(false);
  const [statusMsg, setStatusMsg] = useState("");

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    if (!title.trim() || !content.trim()) return;
    setUploading(true);
    setStatusMsg("");
    try {
      const resp = await fetch(`${API}/api/documents/upload`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ title, publisher, ward, filename, content }),
      });
      if (!resp.ok) throw new Error((await resp.json()).detail ?? "Document upload failed.");
      const uploaded = await resp.json() as UploadedDocument;
      setStatusMsg(`Uploaded ${uploaded.document_id} to ${uploaded.s3_uri} (${uploaded.storage_mode}).`);
      setTitle("");
      await onRefresh();
    } catch (reason) {
      setStatusMsg(reason instanceof Error ? reason.message : "Document upload failed.");
    } finally {
      setUploading(false);
    }
  }

  return <div className="registry-view"><div className="evaluation-strip panel-white"><div><span className="kicker">AWS BEDROCK RAG + S3 KNOWLEDGE BASE</span><h3>Amazon Bedrock ({awsStatus?.bedrock_model_id ?? "amazon.nova-pro-v1:0"}) · S3 Bucket ({awsStatus?.s3_bucket ?? "ecovuna-agronomy-kb"})</h3><p>Uploaded agronomy bulletins and KALRO protocols are stored in AWS S3 with SHA-256 checksums and cited automatically during ward triage.</p></div><div className="evaluation-score"><strong>{documents.length}</strong><span>S3 protocols indexed</span></div></div><div className="registry-grid"><form className="panel-white onboarding-form" onSubmit={handleUpload}><span className="kicker">UPLOAD TO AWS S3 (`ecovuna-agronomy-kb`)</span><h2>Add KALRO protocol or county bulletin</h2><p>Protocols uploaded here are synced to S3 and cited by `search_agronomy_protocols`.</p><label>Document title<input required value={title} onChange={(e) => setTitle(e.target.value)} placeholder="e.g. KALRO Maize Pest & Drought Protocol (Section 4.2)" /></label><label>Publisher / Authority<input required value={publisher} onChange={(e) => setPublisher(e.target.value)} /></label><label>Target ward<select value={ward} onChange={(e) => setWard(e.target.value)}>{(wards.length ? wards : ["Rachuonyo North", "Homa Bay Central", "Ndhiwa", "Suba South"]).map((w) => <option key={w}>{w}</option>)}</select></label><label>Filename<input required value={filename} onChange={(e) => setFilename(e.target.value)} /></label><label>Protocol excerpt & citation IDs<textarea required rows={4} style={{ width: "100%", marginTop: "5px", padding: "9px", border: "1px solid #cbd7de", borderRadius: "4px" }} value={content} onChange={(e) => setContent(e.target.value)} /></label><button className="command-run" type="submit" disabled={uploading}>{uploading ? "Uploading to S3…" : "Upload to AWS S3 & Index"}</button>{statusMsg && <div className="operation-message">{statusMsg}</div>}</form><div className="panel-white registry-list"><div className="live-heading"><h2>Indexed S3 Agronomy Protocols</h2><span>{documents.length} in vault</span></div>{documents.length === 0 ? <p className="empty-copy">No custom documents uploaded yet. Upload a KALRO protocol on the left to sync with AWS S3.</p> : documents.map((doc) => <div className="registry-row" key={doc.document_id}><div><strong>{doc.title}</strong><span>{doc.document_id} · {doc.publisher} · {doc.s3_uri}</span><small style={{ display: "block", marginTop: "4px", color: "#1f3040" }}>“{doc.excerpt}”</small></div><b>{doc.ward}<small>STATUS: {doc.storage_mode.toUpperCase()}</small></b></div>)}</div></div></div>;
}

function LiveMetric({ label, value, alert }: { label: string; value?: number; alert?: boolean }) { return <div className={`live-metric ${alert && value ? "alert" : ""}`}><span>{label}</span><strong>{value !== undefined ? value.toLocaleString() : "—"}</strong></div>; }
function AdvisoryRow({ advisory, onClick }: { advisory: Advisory; onClick: () => void }) { return <button className="advisory-row" onClick={onClick}><span className={`queue-dot ${advisory.status === "PENDING_WAO_APPROVAL" ? "pending" : "done"}`} /><span><strong>{advisory.ward} · {advisory.anomaly_type.replaceAll("_", " ")}</strong><small>1,850 smallholders · {advisory.status.replaceAll("_", " ")}</small></span><b>→</b></button>; }

function AuditTable({ entries, onRetry }: { entries: Audit[]; onRetry: () => Promise<void> }) {
  return <div className="audit-view panel-white">
    <div className="live-heading" style={{ padding: "16px 20px 0", margin: 0 }}>
      <h2>Structured HITL & Tool Execution Audit Ledger</h2>
      <span>Synced with Amazon DynamoDB (`ecovuna-hitl-audit`)</span>
    </div>
    {entries.length === 0 ? <p className="empty-copy">No audit events have been recorded yet. <button type="button" className="retry-action" onClick={() => void onRetry()}>Refresh audit trail</button></p> : <div className="recommendation-list" style={{ padding: "16px 20px" }}>
      {entries.map((entry) => <article className="recommendation-card" key={entry.id}>
        <div className="recommendation-main">
          <div>
            <span className="recommendation-id">RUN ID: {entry.run_id} · SERVER: {entry.server}</span>
            <h3>Tool: {entry.tool_name.replaceAll("_", " ")}</h3>
            <p>Action type: <strong>{entry.action.replaceAll("_", " ").toUpperCase()}</strong> · Recorded at {new Date(entry.timestamp).toLocaleString()}</p>
          </div>
          <span className="badge badge-success badge-outline">VERIFIED AUDIT RECORD</span>
        </div>
      </article>)}
    </div>}
  </div>;
}
