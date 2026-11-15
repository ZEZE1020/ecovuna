"use client";

import { useEffect, useState } from "react";
import type { FormEvent, ReactNode } from "react";
import {
  Activity, Check, CircleAlert, ClipboardCheck, Clock3, Database,
  FileSearch, Flag, LockKeyhole, Play, Radar, ShieldCheck, Sparkles,
  Terminal, UserPlus, UserRound, Workflow, X,
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
};
type Trace = { node: string; tool: string; server: string; latency_ms: number; output: Record<string, unknown> };
type Run = {
  run_id: string;
  ward: string;
  status: string;
  execution_trace: Trace[];
  advisory: Advisory;
  telemetry: { readings: Array<Record<string, string | number>> };
  cost_telemetry: { duration_ms: number };
  agent_foundation?: AgentFoundation;
};
type Audit = { id: number; timestamp: string; run_id: string; server: string; tool_name: string; action: string; input_json: string; output_json: string };
type AgentFoundation = { project: string; provider: string; model: string; mode: string; grounded: boolean; human_approval_required: boolean };
type EvaluationSummary = { passed: number; total: number; pass_rate: number; interpretation: { data_grounding: string; agent_usefulness: string; model_status: string } };

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://localhost:8000";

export default function Home() {
  const [view, setView] = useState<"overview" | "workspace" | "operations" | "registry" | "audit">("overview");
  const [dashboard, setDashboard] = useState<Dashboard | null>(null);
  const [advisories, setAdvisories] = useState<Advisory[]>([]);
  const [audit, setAudit] = useState<Audit[]>([]);
  const [operationsSummary, setOperationsSummary] = useState<OperationsSummary | null>(null);
  const [recommendations, setRecommendations] = useState<Recommendation[]>([]);
  const [telemetry, setTelemetry] = useState<TelemetryReading[]>([]);
  const [apiTelemetry, setApiTelemetry] = useState<{ enabled: boolean; exporter: string } | null>(null);
  const [foundation, setFoundation] = useState<AgentFoundation | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationSummary | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [ward, setWard] = useState("");
  const [scenario, setScenario] = useState("sudden dry spell");
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState("");
  const [askQuestion, setAskQuestion] = useState("");

  async function loadData() {
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
    if (!ward && nextDashboard.wards[0]) setWard(nextDashboard.wards[0].ward);
  }

  useEffect(() => {
    loadData().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load county data.")).finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    fetch(`${API}/api/health`)
      .then((response) => response.json() as Promise<{ telemetry: { enabled: boolean; exporter: string }; agent_foundation: AgentFoundation }>)
      .then((payload) => {
        setApiTelemetry(payload.telemetry);
        setFoundation(payload.agent_foundation);
      })
      .catch(() => setApiTelemetry(null));
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

  async function openView(nextView: "overview" | "workspace" | "operations" | "registry" | "audit") {
    setView(nextView);
    setError("");
    if (nextView === "audit") loadAudit().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load the audit trail."));
    if (nextView === "operations") loadOperations().catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Unable to load extension operations."));
  }

  async function startRun(requestedScenario = scenario) {
    if (!ward) return;
    setRunning(true);
    setError("");
    try {
      const response = await fetch(`${API}/api/agent/triage`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ward, scenario_override: requestedScenario }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Agent run failed.");
      setRun(await response.json());
      await loadData();
      setView("workspace");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Agent run failed.");
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

  async function decide(approved: boolean) {
    if (!run) return;
    setError("");
    try {
      const response = await fetch(`${API}/api/agent/decide`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ run_id: run.run_id, approved, wao_officer_name: "Godfrey Ogembo — WAO-KE-043", notes: approved ? "Reviewed in Ecovuna Desk." : "Requires field verification." }),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "Decision could not be recorded.");
      const decision = await response.json();
      setRun({ ...run, status: decision.status, advisory: { ...run.advisory, status: decision.status } });
      await loadData();
      setView("workspace");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Decision could not be recorded.");
    }
  }

  return <main className="agent-shell">
    <header className="agent-header"><div className="agent-brand"><span className="brand-mark"><Sparkles size={17} /></span><div><strong>ECOVUNA DESK</strong><span>Agent operations · Homa Bay County</span></div></div><div className="header-meta"><span className="badge badge-success badge-outline gap-1"><i /> API connected</span>{foundation && <span className="badge badge-primary badge-outline" title={`${foundation.project} · ${foundation.model}`}>FOUNDATION · {foundation.mode.replace("_", " ")}</span>}{apiTelemetry && <span className={`otel-status ${apiTelemetry.enabled ? "enabled" : "disabled"}`} title={`OpenTelemetry exporter: ${apiTelemetry.exporter}`}>OTEL {apiTelemetry.enabled ? "ON" : "OFF"}</span>}<span className="user-badge"><UserRound size={15} /></span><span>Godfrey Ogembo<br /><small>WAO-KE-043</small></span></div></header>
    <div className="agent-layout">
      <aside className="agent-nav"><div className="office-card"><span>ACTIVE OFFICE</span><strong>Extension network</strong><small>County operations workspace</small></div><span className="nav-heading">OPERATIONS</span><NavButton active={view === "overview"} label="Situation overview" icon={<Radar size={16} />} onClick={() => openView("overview")} /><NavButton active={view === "workspace"} label="Agent workspace" icon={<Workflow size={16} />} onClick={() => openView("workspace")} count={dashboard?.counts.pending_advisories} /><NavButton active={view === "registry"} label="Farm registry" icon={<UserPlus size={16} />} onClick={() => openView("registry")} count={dashboard?.counts.households} /><NavButton active={view === "operations"} label="Partner matching" icon={<Database size={16} />} onClick={() => openView("operations")} count={operationsSummary?.recommended_assignments} /><NavButton active={view === "audit"} label="Audit trail" icon={<ClipboardCheck size={16} />} onClick={() => openView("audit")} /><div className="nav-note"><LockKeyhole size={15} /><strong>Human approval required</strong><span>Every outbound action pauses for named officer sign-off.</span></div></aside>
      <section className="agent-content"><div className="content-title"><div><span className="kicker">EXTENSION OPERATIONS CONSOLE</span><h1>{view === "overview" ? "Today’s priorities" : view === "workspace" ? "Agent workspace" : view === "operations" ? "Partner matching" : view === "registry" ? "Farm registry" : "Audit trail"}</h1><p>{view === "overview" ? "A simple starting point for field decisions, farmer follow-up, and trusted advice." : view === "workspace" ? "Inspect the agent's evidence, then make the accountable human decision." : view === "operations" ? "Match farms with verified agrovets, seed hubs, and fertiliser partners using field conditions." : view === "registry" ? "Register farmers and map their farms with an auditable officer workflow." : "Append-only record of agent tool calls and officer decisions."}</p></div>{view !== "audit" && view !== "operations" && view !== "registry" && <button className="run-button btn btn-primary" onClick={() => startRun()} disabled={running || !ward}>✦ {running ? "Agent is working…" : "Run agent analysis"}</button>}</div>{error && <div className="error-message alert alert-error">! {error}</div>}{loading ? <div className="loading-state">Loading county workspace…</div> : view === "overview" ?       <Overview dashboard={dashboard} advisories={advisories} telemetry={telemetry} evaluation={evaluation} ward={ward} setWard={setWard} scenario={scenario} setScenario={setScenario} onStart={startRun} onAsk={askEcovuna} askQuestion={askQuestion} setAskQuestion={setAskQuestion} running={running} onOpenWorkspace={() => openView("workspace")} /> : view === "workspace" ? <Workspace run={run} advisories={advisories} onStart={startRun} onDecision={decide} running={running} /> : view === "operations" ? <Operations summary={operationsSummary} recommendations={recommendations} ward={ward} onRefresh={loadOperations} /> : view === "registry" ? <Registry wards={dashboard?.wards.map((item) => item.ward) ?? []} /> : <AuditTable entries={audit} />}</section>
    </div>
  </main>;
}

function NavButton({ active, label, icon, count, onClick }: { active: boolean; label: string; icon: ReactNode; count?: number; onClick: () => void }) { return <button className={`agent-nav-button ${active ? "active" : ""}`} onClick={onClick}><b>{icon}</b>{label}{count ? <em>{count}</em> : null}</button>; }

function Registry({ wards }: { wards: string[] }) {
  const [farmers, setFarmers] = useState<Array<{ farmer_id: string; full_name: string; phone_number: string; ward: string; plot_count: number }>>([]);
  const [form, setForm] = useState({ full_name: "", phone_number: "", ward: wards[0] ?? "", cooperative_name: "" });
  const [message, setMessage] = useState("");
  async function load() { const response = await fetch(`${API}/api/farmers`); if (response.ok) setFarmers(await response.json()); }
  useEffect(() => { if (!form.ward && wards[0]) setForm((current) => ({ ...current, ward: wards[0] })); load(); }, [wards]);
  async function submit(event: FormEvent) {
    event.preventDefault(); setMessage("");
    const response = await fetch(`${API}/api/farmers`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ ...form, cooperative_name: form.cooperative_name || "Independent farmer" }) });
    if (!response.ok) { setMessage((await response.json()).detail ?? "Farmer could not be registered."); return; }
    setMessage("Farmer registered. Add the farm plot from the registry workflow next."); setForm({ full_name: "", phone_number: "", ward: wards[0] ?? "", cooperative_name: "" }); await load();
  }
  return <div className="registry-view"><div className="registry-grid"><form className="panel-white onboarding-form" onSubmit={submit}><span className="kicker">FARMER ONBOARDING</span><h2>Register a farmer</h2><p>Capture a verified registry record before linking advisory, input, or partner actions.</p><label>Full name<input required value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} /></label><label>Phone number<input required value={form.phone_number} onChange={(event) => setForm({ ...form, phone_number: event.target.value })} /></label><label>Ward<select value={form.ward} onChange={(event) => setForm({ ...form, ward: event.target.value })}>{wards.map((item) => <option key={item}>{item}</option>)}</select></label><label>Cooperative or group<input value={form.cooperative_name} onChange={(event) => setForm({ ...form, cooperative_name: event.target.value })} placeholder="Optional" /></label><button className="command-run" type="submit">Register farmer</button>{message && <div className="operation-message">{message}</div>}</form><div className="panel-white registry-list"><div className="live-heading"><h2>Registered farmers</h2><span>{farmers.length} loaded from API</span></div>{farmers.map((farmer) => <div className="registry-row" key={farmer.farmer_id}><div><strong>{farmer.full_name}</strong><span>{farmer.farmer_id} · {farmer.phone_number}</span></div><b>{farmer.ward}<small>{farmer.plot_count} farm plot{farmer.plot_count === 1 ? "" : "s"}</small></b></div>)}</div></div></div>;
}

function Overview({ dashboard, advisories, telemetry, evaluation, ward, setWard, scenario, setScenario, onStart, onAsk, askQuestion, setAskQuestion, running, onOpenWorkspace }: { dashboard: Dashboard | null; advisories: Advisory[]; telemetry: TelemetryReading[]; evaluation: EvaluationSummary | null; ward: string; setWard: (value: string) => void; scenario: string; setScenario: (value: string) => void; onStart: (scenario?: string) => Promise<void>; onAsk: (question: string) => Promise<void>; askQuestion: string; setAskQuestion: (value: string) => void; running: boolean; onOpenWorkspace: () => void }) {
  const counts = dashboard?.counts;
  const pending = counts?.pending_advisories ?? 0;
  const latestReading = telemetry[0];
  const priorityText = pending > 0 ? `${pending} advisory${pending === 1 ? "" : "ies"} waiting for your decision` : latestReading?.freshness === "cached" ? "Review cached telemetry before your next field visit" : "No urgent approvals waiting";
  return <div className="overview"><div className="evaluation-strip panel-white"><div><span className="kicker">QUALITY CHECK · BASELINE</span><h3>Can we trust this run?</h3><p>{evaluation?.interpretation.model_status ?? "Loading the current evaluation baseline."}</p></div><div className="evaluation-score"><strong>{evaluation ? `${Math.round(evaluation.pass_rate * 100)}%` : "—"}</strong><span>{evaluation ? `${evaluation.passed}/${evaluation.total} checks pass` : "Evaluating"}</span></div></div><div className="welcome-grid"><section className="ask-card panel-white"><div className="ask-card-heading"><div><span className="kicker">ASK ECOVUNA</span><h2>What needs your attention today?</h2><p>Ask in plain language. Ecovuna will find evidence, suggest a next step, and wait for your approval.</p></div><span className="badge badge-success badge-outline">Grounded + human-led</span></div><form className="ask-form" onSubmit={(event) => { event.preventDefault(); if (askQuestion.trim()) void onAsk(askQuestion.trim()); }}><input className="input input-bordered" value={askQuestion} onChange={(event) => setAskQuestion(event.target.value)} placeholder="e.g. Which farms should I visit first?" aria-label="Ask Ecovuna a question" /><button className="btn btn-primary" type="submit" disabled={running || !ward || !askQuestion.trim()}>{running ? "Checking…" : "Ask Ecovuna"}</button></form><div className="prompt-row"><button className="btn btn-ghost btn-sm" onClick={() => void onAsk("Which farms need attention today?")} disabled={running}>Priority farms</button><button className="btn btn-ghost btn-sm" onClick={() => void onAsk("Which wards show flood or waterlogging risk?")} disabled={running}>Flood risk</button><button className="btn btn-ghost btn-sm" onClick={() => void onAsk("What should I tell farmers about a dry spell?")} disabled={running}>Dry spell advice</button></div></section><section className="today-card"><span className="kicker">FIELD BRIEFING</span><h3>Good morning, Godfrey</h3><p className="today-priority"><CircleAlert size={17} /> {priorityText}</p><div className="today-meta"><span><strong>{counts?.households ?? "—"}</strong> households</span><span><strong>{counts?.plots ?? "—"}</strong> plots mapped</span></div><button className="btn btn-outline btn-sm" onClick={onOpenWorkspace}>Open review queue</button></section></div><div className="channel-strip panel-white"><div><span className="kicker">MEET PEOPLE WHERE THEY ARE</span><h3>One approved message, every channel</h3><p>Prepare advice for mobile web, SMS, USSD, WhatsApp, or voice after you review it.</p></div><div className="channel-badges"><span className="badge badge-outline">Mobile web</span><span className="badge badge-outline">SMS</span><span className="badge badge-outline">USSD</span><span className="badge badge-outline">Voice next</span></div></div><div className="agent-command"><div><span className="kicker">CONTROLLED ANALYSIS</span><h2>Choose a ward for deeper review</h2><p>The agent fetches telemetry, checks agronomic guidance, and pauses before any outbound action.</p></div><div className="command-controls"><label>Ward<select value={ward} onChange={(event) => setWard(event.target.value)}>{dashboard?.wards.map((item) => <option key={item.ward}>{item.ward}</option>)}</select></label><label>Scenario<select value={scenario} onChange={(event) => setScenario(event.target.value)}><option>sudden dry spell</option><option>flowering maize dry spell</option><option>flash flood waterlogging</option></select></label><button className="command-run" onClick={() => void onStart()} disabled={running || !ward}>{running ? "Running…" : "Start analysis →"}</button></div></div><div className="live-heading"><h2>Registry at a glance</h2><span>Read from local Ecovuna API</span></div><div className="live-metrics"><LiveMetric label="Registered households" value={counts?.households} /><LiveMetric label="Mapped farm plots" value={counts?.plots} /><LiveMetric label="Staged advisories" value={counts?.advisories} /><LiveMetric label="Awaiting your decision" value={counts?.pending_advisories} alert /></div><div className="live-heading"><h2>Ward telemetry</h2><span>Latest cached readings by administrative ward</span></div><div className="ward-table panel-white"><div className="table-head"><span>WARD</span><span>HOUSEHOLDS</span><span>PLOTS</span><span>SOIL MOISTURE</span><span>LAST READING</span></div>{dashboard?.wards.map((item) => <div className="table-row" key={item.ward}><strong>{item.ward}</strong><span>{item.households}</span><span>{item.plots}</span><span className={item.soil_moisture_pct !== null && item.soil_moisture_pct < 20 ? "danger-text" : ""}>{item.soil_moisture_pct === null ? "—" : `${item.soil_moisture_pct}%`}</span><span>{item.last_telemetry_at ? new Date(item.last_telemetry_at).toLocaleString() : "No reading"}</span></div>)}</div><TelemetryPanel ward={ward} readings={telemetry} /><div className="live-heading"><h2>Advisory queue</h2><button className="text-action" onClick={onOpenWorkspace}>Open agent workspace →</button></div><div className="advisory-list panel-white">{advisories.length === 0 ? <p className="empty-copy">No staged advisories. Start an agent analysis above.</p> : advisories.slice(0, 5).map((item) => <AdvisoryRow key={item.advisory_id} advisory={item} onClick={onOpenWorkspace} />)}</div></div>;
}

function TelemetryPanel({ ward, readings }: { ward: string; readings: TelemetryReading[] }) {
  const reading = readings[0];
  const vegetation = reading?.raw_payload_json.vegetation_indices;
  return <section className="telemetry-panel panel-white"><div className="telemetry-heading"><div><span className="kicker">KIJANISPACE READINGS</span><h2>{ward || "Selected ward"}</h2><p>Latest normalized land and agro-climate observation for the selected ward.</p></div>{reading && <span className={`freshness-badge ${reading.freshness}`}><i /> {reading.freshness === "live" ? "LIVE FROM KIJANISPACE" : "CACHED READING"}</span>}</div>{!reading ? <p className="empty-copy">No telemetry reading is available for this ward.</p> : <><div className="reading-grid"><Reading label="Soil moisture" value={`${reading.soil_moisture_pct}%`} /><Reading label="Soil temperature" value={`${reading.soil_temp_c}°C`} /><Reading label="Forecast precipitation" value={`${reading.precipitation_7d_mm} mm`} /><Reading label="Rainfall anomaly" value={`${reading.rainfall_anomaly_mm} mm`} /><Reading label="NDVI" value={vegetation?.NDVI?.toString() ?? "—"} /><Reading label="Vegetation health" value={vegetation?.vegetation_health_index !== undefined ? `${vegetation.vegetation_health_index}%` : "—"} /></div><div className="reading-meta"><span>Sensor {reading.sensor_id}</span><span>Observed {new Date(reading.timestamp).toLocaleString()}</span>{reading.raw_payload_json.landuse && <span>{reading.raw_payload_json.landuse}</span>}{reading.raw_payload_json.forecast_model_run && <span>Model run {reading.raw_payload_json.forecast_model_run}</span>}</div></>}</section>;
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
      <LiveMetric label="Verified partners" value={summary?.verified_partners} />
      <LiveMetric label="Inputs in stock" value={summary?.in_stock_inputs} />
      <LiveMetric label="Recommended matches" value={summary?.recommended_assignments} alert />
      <LiveMetric label="Confirmed assignments" value={summary?.confirmed_assignments} />
    </div>
    <section className="panel-white operations-panel">
      <div className="operations-toolbar"><div><span className="kicker">EXPLAINABLE MATCHING</span><h2>Farm-to-provider recommendations</h2><p>Recommendations use ward proximity, crop, soil moisture, agroclimatic zone, stock, and partner service radius.</p></div><label>Input category<select value={category} onChange={(event) => filterRecommendations(event.target.value)}><option value="">All inputs</option><option value="SEED">Seed</option><option value="FERTILISER">Fertiliser</option><option value="SOIL_AMENDMENT">Soil amendment</option><option value="CROP_PROTECTION">Crop protection</option></select></label></div>
      {message && <div className="operation-message">{message}</div>}
      <div className="recommendation-list">{items.length === 0 ? <p className="empty-copy">No verified provider match was found for this filter.</p> : items.map((item) => <article className="recommendation-card" key={`${item.plot_id}-${item.input.input_id}`}><div className="recommendation-main"><div><span className="recommendation-id">{item.plot_id} · {item.ward}</span><h3>{item.input.name}</h3><p>{item.crop_type} · {item.soil_profile} · {item.agroclimatic_zone}</p></div><strong className="match-score">{item.score}/12 match</strong></div><div className="recommendation-provider"><span><Database size={14} /> {item.partner.name}</span><span>{item.partner.partner_type}</span><span>KES {item.input.price_kes.toLocaleString()} / {item.input.unit}</span><button className="approve-action" onClick={() => confirm(item)} disabled={busyPlot === item.plot_id}>{busyPlot === item.plot_id ? "Saving…" : "Confirm assignment"}</button></div><div className="reason-list">{item.reasons.map((reason) => <span key={reason}><Check size={11} />{reason}</span>)}</div></article>)}</div>
    </section>
  </div>;
}

function Workspace({ run, advisories, onStart, onDecision, running }: { run: Run | null; advisories: Advisory[]; onStart: () => void; onDecision: (approved: boolean) => void; running: boolean }) {
  if (!run) return <div className="empty-workspace panel-white"><span className="empty-agent-icon"><Sparkles size={24} /></span><h2>No active agent run</h2><p>Start an analysis to see the agent's plan, tool calls, evidence, and human approval gate.</p><button className="run-button" onClick={onStart} disabled={running}><Play size={14} />{running ? "Running…" : "Run agent analysis"}</button>{advisories.length > 0 && <p className="existing-note">{advisories.length} advisory record(s) already exist in the API. Open Situation overview to review the queue.</p>}</div>;
  const pending = run.status === "PAUSED_AT_WAO_GATE";
  return <div className="workspace-view"><div className="run-context"><div><span className="kicker">ACTIVE RUN · {run.run_id}</span><h2>{run.ward} investigation</h2><p>Completed in {Math.round(run.cost_telemetry.duration_ms)} ms · {run.telemetry.readings.length} telemetry reading(s)</p></div><span className={`run-status ${pending ? "paused" : "complete"}`}>{pending ? "Paused at approval gate" : run.status.replaceAll("_", " ")}</span></div><section className="agent-contract panel-white"><div><span className="kicker">AGENT OPERATING CONTRACT</span><h3>{run.agent_foundation?.project ?? "Ecovuna Agentic Extension Foundation"}</h3><p>This run is grounded in registered tools and cannot send an outbound action without your decision.</p></div><div className="contract-badges"><span className="badge badge-success badge-outline">Evidence linked</span><span className="badge badge-info badge-outline">Tool calls visible</span><span className="badge badge-warning badge-outline">Human control required</span></div></section><div className="agent-flow"><FlowStep number="1" label="Plan & fetch" done /><FlowStep number="2" label="Check evidence" done /><FlowStep number="3" label="Prepare action" done /><FlowStep number="4" label="Your decision" active={pending} /></div><section className="agent-plan panel-white"><div className="plan-icon"><Sparkles size={18} /></div><div><span className="kicker">AGENT PLAN</span><h3>Investigate {run.ward}, validate the signal, then prepare a reversible advisory</h3><p>The agent used {run.execution_trace.length} tool steps. Review each step below before deciding whether the recommendation is safe to send.</p></div></section><div className="trace-stack">{run.execution_trace.map((trace, index) => <TraceCard key={`${trace.tool}-${index}`} trace={trace} index={index} />)}</div><ApprovalCard run={run} pending={pending} onDecision={onDecision} /></div>;
}

function ApprovalCard({ run, pending, onDecision }: { run: Run; pending: boolean; onDecision: (approved: boolean) => void }) { const advisory = run.advisory; return <section className="approval-card"><div className="approval-header"><div><span className="kicker"><LockKeyhole size={12} /> HUMAN-IN-THE-LOOP GATE</span><h2>{pending ? "Review before dispatch" : "Decision recorded"}</h2><p>{pending ? "The agent has staged this advisory but cannot dispatch until you approve or flag it." : `This advisory is ${run.status.replaceAll("_", " ").toLowerCase()}.`}</p></div><span className="gate-lock"><Clock3 size={13} /> {pending ? "PAUSED" : "CLOSED"}</span></div><div className="approval-body"><div className="advisory-evidence"><h3>Recommended action</h3><p>Target <strong>{advisory.target_growth_stage.replaceAll("_", " ")}</strong> plots in <strong>{advisory.ward}</strong>. Package <strong>{advisory.evoucher_package_code}</strong> at KES {advisory.per_farmer_kes.toLocaleString()} per affected plot.</p><div className="source-chips">{advisory.citations.sensor_ids?.map((sensor) => <span key={sensor}><Activity size={11} /> Sensor: {sensor}</span>)}{advisory.citations.kalro_rule_id && <span><FileSearch size={11} /> Rule: {advisory.citations.kalro_rule_id}</span>}{advisory.citations.weather_bulletin_id && <span><Database size={11} /> Bulletin: {advisory.citations.weather_bulletin_id}</span>}</div><div className="message-preview"><span className="kicker">DRAFT ENGLISH MESSAGE</span><p>{advisory.draft_sms_english}</p><small>USSD {advisory.ussd_menu_payload} · {advisory.affected_household_count} affected household(s)</small></div></div><div className="decision-form"><label>Officer of record<input value="Godfrey Ogembo — WAO-KE-043" readOnly /></label><label>Review note<textarea defaultValue="Reviewed against the agent evidence." readOnly={!pending} /></label>{pending ? <><button className="approve-action" onClick={() => onDecision(true)}><Check size={14} /> Approve and resume dispatch</button><button className="reject-action" onClick={() => onDecision(false)}><Flag size={14} /> Flag for field visit</button></> : <div className="recorded-action"><ShieldCheck size={14} /> Recorded in audit trail</div>}</div></div></section>; }

function TraceCard({ trace, index }: { trace: Trace; index: number }) { const outputKeys = Object.keys(trace.output); return <details className="trace-card" open><summary><span className="trace-check"><Check size={12} /></span><span><strong>{index + 1}. {trace.node.replaceAll("_", " ")}</strong><small><Terminal size={11} /> {trace.server} · {trace.tool}</small></span><time>{trace.latency_ms} ms</time></summary><div className="trace-evidence"><div><span>Agent step</span><strong>{trace.tool.replaceAll("_", " ")}</strong></div><div><span>Evidence returned</span><strong>{outputKeys.length} fields</strong></div><div><span>Operator action</span><strong>Inspect or continue</strong></div></div><pre>{JSON.stringify(trace.output, null, 2)}</pre></details>; }
function FlowStep({ number, label, done, active }: { number: string; label: string; done?: boolean; active?: boolean }) { return <div className={`flow-step ${done ? "done" : ""} ${active ? "active" : ""}`}><b>{done ? <Check size={12} /> : number}</b><span>{label}</span></div>; }
function LiveMetric({ label, value, alert }: { label: string; value?: number; alert?: boolean }) { return <div className={`live-metric ${alert && value ? "alert" : ""}`}><span>{label}</span><strong>{value ?? "—"}</strong></div>; }
function AdvisoryRow({ advisory, onClick }: { advisory: Advisory; onClick: () => void }) { return <button className="advisory-row" onClick={onClick}><span className={`queue-dot ${advisory.status === "PENDING_WAO_APPROVAL" ? "pending" : "done"}`} /><span><strong>{advisory.ward} · {advisory.anomaly_type.replaceAll("_", " ")}</strong><small>{advisory.affected_household_count} households · {advisory.status.replaceAll("_", " ")}</small></span><b>→</b></button>; }
function AuditTable({ entries }: { entries: Audit[] }) { return <div className="audit-view panel-white">{entries.length === 0 ? <p className="empty-copy">No audit events have been recorded yet.</p> : entries.map((entry) => <details className="audit-row" key={entry.id}><summary><time>{new Date(entry.timestamp).toLocaleString()}</time><strong>{entry.tool_name}</strong><span>{entry.action}</span><small>{entry.run_id}</small></summary><pre>INPUT {entry.input_json}{"\n"}OUTPUT {entry.output_json}</pre></details>)}</div>; }
