import type { Metadata } from "next";
import { Activity, Database, Radar, ShieldCheck, Sparkles } from "lucide-react";

export const metadata: Metadata = {
  title: "Ecovuna Desk — Grounded field intelligence for smallholder farms",
  description: "Agentic agricultural triage: ward sensor checks, KALRO citations, and officer approval before SMS or USSD dispatch.",
};

export default function LandingPage() {
  return <main style={{ minHeight: "100vh", background: "var(--bg)", color: "var(--ink)" }}>
    <section style={{ background: "var(--green-light)", borderBottom: "1px solid var(--line)" }}>
      <div style={{ maxWidth: 1080, margin: "0 auto", padding: "84px 20px 72px" }}>
        <span className="kicker">FIELD INTELLIGENCE · HOMA BAY COUNTY</span>
        <h1 style={{ margin: "12px 0 16px", color: "var(--navy)", fontSize: "clamp(32px, 5vw, 50px)", lineHeight: 1.12, maxWidth: 780 }}>Grounded agent triage for smallholder farms.</h1>
        <p style={{ margin: "0 0 30px", color: "var(--muted)", fontSize: 16, lineHeight: 1.65, maxWidth: 640 }}>Ecovuna Desk runs ward sensor checks, cites KALRO agronomy protocols, and stages farmer-ready advisories — pausing at the officer approval gate before any SMS or USSD dispatch.</p>
        <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
          <a className="btn btn-primary" href="/">Open the Agent Console</a>
          <a className="btn btn-outline" href="#how">How the agent works</a>
        </div>
      </div>
    </section>
    <section style={{ maxWidth: 1080, margin: "0 auto", padding: "54px 20px 30px" }}>
      <div className="live-metrics">
        <div className="live-metric"><span>Triage time</span><strong>24s<small>vs 4 days</small></strong></div>
        <div className="live-metric"><span>Cost per alert</span><strong>$11.40</strong></div>
        <div className="live-metric"><span>Farmers reached</span><strong>1,850</strong></div>
        <div className="live-metric"><span>Data layer</span><strong>AWS</strong></div>
      </div>
    </section>
    <section id="how" style={{ maxWidth: 1080, margin: "0 auto", padding: "26px 20px 70px" }}>
      <div className="live-heading"><div><span className="kicker">HOW IT WORKS</span><h2>From sensor alert to approved field action</h2></div></div>
      <div className="recommendation-list">
        {[
          { icon: <Radar size={18} />, title: "Agent checks ward evidence", text: "Soil moisture, pest thresholds, weather context, and KALRO protocol citations are fetched and cross-checked in seconds." },
          { icon: <Activity size={18} />, title: "Advisory is staged", text: "A grounded, localized SMS/USSD/voucher draft is prepared for the affected plots and farmers." },
          { icon: <ShieldCheck size={18} />, title: "Officer approves", text: "The WAO reviews evidence and sign-off before any external dispatch leaves the gate." },
          { icon: <Database size={18} />, title: "SMS & USSD dispatched", text: "Approved campaigns reach farmers over Africa's Talking SMS and USSD channels with citations attached." },
        ].map((step, index) => (
          <article className="recommendation-card" key={step.title}>
            <div className="recommendation-main">
              <div>
                <span className="recommendation-id">STEP {index + 1}</span>
                <h3 style={{ fontSize: "15px", marginTop: 4 }}>{step.title}</h3>
                <p style={{ marginTop: 4, color: "#1f3040" }}>{step.text}</p>
              </div>
              <span className="recommendation-id" style={{ alignSelf: "flex-start" }}>{step.icon}</span>
            </div>
          </article>
        ))}
      </div>
    </section>
    <section style={{ padding: "0 20px 90px" }}>
      <div className="panel-white" style={{ padding: 34, textAlign: "center", background: "var(--green-light)", borderColor: "var(--line)" }}>
        <span className="kicker">NEXT ALERT</span>
        <h2 style={{ margin: "8px 0 10px", color: "var(--navy)", fontSize: 24 }}>Ready when the next ward alert hits.</h2>
        <p style={{ margin: "0 0 22px", color: "var(--muted)", fontSize: 13 }}>Grounded triage, officer approval, and farmer dispatch — in one console.</p>
        <a className="run-button" href="/"><Sparkles size={14} /> Open the Agent Console</a>
      </div>
    </section>
  </main>;
}
