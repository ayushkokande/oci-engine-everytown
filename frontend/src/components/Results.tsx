import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { storage } from "../config";
import type { Band, Recommendation, ResourceInfo, SubmissionResult } from "../types";
import { STAGES } from "../types";

const BANDS: Band[] = ["High", "Medium", "Low"];

function StageLadder({ stage }: { stage: string }) {
  const idx = STAGES.indexOf(stage);
  return (
    <div className="ladder" aria-label={`Estimated stage: ${stage}`}>
      {STAGES.map((s, i) => (
        <span key={s} className={`rung ${i <= idx ? "on" : ""} ${i === idx ? "here" : ""}`} title={s} />
      ))}
    </div>
  );
}

function CapacityRing({ pct }: { pct: number }) {
  const r = 30;
  const c = 2 * Math.PI * r;
  return (
    <svg viewBox="0 0 72 72" className="ring" role="img" aria-label={`${pct}% capacity`}>
      <circle cx="36" cy="36" r={r} className="ring-track" />
      <circle cx="36" cy="36" r={r} className="ring-fill" strokeDasharray={`${(pct / 100) * c} ${c}`}
        transform="rotate(-90 36 36)" />
      <text x="36" y="40" textAnchor="middle" className="ring-label">{Math.round(pct)}%</text>
    </svg>
  );
}

export function Results({ result, onStartOver }: { result: SubmissionResult; onStartOver: () => void }) {
  const [band, setBand] = useState<Band | "All">("All");
  const [domain, setDomain] = useState<string>("All");
  const [resources, setResources] = useState<ResourceInfo[]>([]);
  const [planned, setPlanned] = useState<Record<string, boolean>>(
    () => storage.get(`oci.planned.${result.submission_id}`, {}));

  useEffect(() => { api.resources().then(setResources).catch(() => setResources([])); }, []);
  useEffect(() => storage.set(`oci.planned.${result.submission_id}`, planned), [planned, result.submission_id]);

  const degraded = result.orchestration_status === "error";
  // When narration failed, show the engine's own gaps and next steps.
  const recs: Recommendation[] = useMemo(() => {
    if (result.recommendations.length) return result.recommendations;
    const order = { High: 0, Medium: 1, Low: 2 } as const;
    return [...result.gaps]
      .sort((a, b) => order[a.priority] - order[b.priority] || b.priority_score - a.priority_score)
      .map((g) => ({ ...g, narrative: null, resource_ids: [] }));
  }, [result]);

  const filtered = recs.filter((r) => (band === "All" || r.priority === band) && (domain === "All" || r.domain_id === domain));
  const stats = result.scores.overall_stats;
  const resById = Object.fromEntries(resources.map((r) => [r.id, r]));
  const date = new Date(result.timestamp).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  const plannedCount = Object.values(planned).filter(Boolean).length;

  const jumpTo = (qid: string) => {
    setBand("All");
    setDomain("All");
    window.setTimeout(() => document.getElementById(`rec-${qid}`)?.scrollIntoView({ behavior: "smooth", block: "center" }), 50);
  };

  return (
    <section className="results">
      <div className="results-hero">
        <div>
          <p className="eyebrow">Step 4 of 4 · {date}</p>
          <h1>{result.profile.org_name}</h1>
          <p className="muted">
            Domains assessed: {result.scores.domains.map((d) => d.domain_name).join(", ")}
          </p>
        </div>
        <div className="hero-actions">
          <a className="btn primary" href={api.reportUrl(result.submission_id)} download>
            ↓ Download PDF report
          </a>
          <button className="btn ghost" onClick={onStartOver}>Start a new assessment</button>
        </div>
      </div>

      {degraded && (
        <div className="alert warn" role="status">
          <strong>Personalized narrative couldn't be generated this time.</strong> Your scores and priorities
          below are complete and accurate; the recommendations use the questionnaire's standard next steps.
          {result.orchestration_error && <span className="muted"> ({result.orchestration_error})</span>}
        </div>
      )}

      {result.overview && <p className="overview">{result.overview}</p>}

      <div className="stat-row">
        <div className="stat"><span className="stat-num">{stats.total_questions}</span><span>statements answered</span></div>
        <div className="stat"><span className="stat-num">{stats.total_gaps}</span><span>areas to build</span></div>
        <div className="stat band-High"><span className="stat-num">{stats.high_priority}</span><span>start here</span></div>
        <div className="stat band-Medium"><span className="stat-num">{stats.medium_priority}</span><span>next</span></div>
        <div className="stat band-Low"><span className="stat-num">{stats.low_priority}</span><span>later</span></div>
      </div>

      <h2 className="section-title">Capacity by area</h2>
      <div className="domain-grid">
        {result.scores.domains.map((d) => (
          <button key={d.domain_id} className={`card domain-card ${domain === d.domain_id ? "selected" : ""}`}
            onClick={() => setDomain(domain === d.domain_id ? "All" : d.domain_id)}
            title="Filter recommendations to this area">
            <CapacityRing pct={d.score_pct} />
            <div className="dc-body">
              <h3>{d.domain_name}</h3>
              <div className="dc-stage">
                <span className="muted">Stage</span>
                <strong>{d.estimated_stage}</strong>
              </div>
              <StageLadder stage={d.estimated_stage} />
              <span className="muted small">{d.gap_count} of {d.total_questions} statements to build on</span>
            </div>
          </button>
        ))}
      </div>

      {(result.action_plan.length > 0 || result.research_summary) && (
        <div className="two-col">
          {result.action_plan.length > 0 && (
            <div className="card plan">
              <h2 className="section-title">Suggested action plan</h2>
              <ol className="timeline">
                {result.action_plan.map((p) => (
                  <li key={p.timeframe}>
                    <span className="tl-when">{p.timeframe}</span>
                    <ul>
                      {p.actions.map((a, i) => (
                        <li key={i}>
                          {a.text}{" "}
                          {a.question_ids.map((q) => (
                            <button key={q} className="qref" onClick={() => jumpTo(q)}>{q}</button>
                          ))}
                        </li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ol>
            </div>
          )}
          {result.research_summary && (
            <div className="card research">
              <h2 className="section-title">What we read on your website</h2>
              <p>{result.research_summary}</p>
              <p className="muted small">Summarized by AI from {result.profile.website_url}. Tell us if anything is off.</p>
            </div>
          )}
        </div>
      )}

      <div className="recs-head">
        <h2 className="section-title">Recommendations</h2>
        <span className="muted small">
          Priority is relative to the gaps in this submission: it shows where to start, not how serious
          a gap is. {plannedCount > 0 && <strong>{plannedCount} marked as planned.</strong>}
        </span>
      </div>
      <div className="filters">
        <div className="chips" role="group" aria-label="Filter by priority">
          {(["All", ...BANDS] as const).map((b) => (
            <button key={b} className={`chip-btn ${band === b ? "active" : ""} ${b !== "All" ? "band-" + b : ""}`}
              onClick={() => setBand(b)}>
              {b === "All" ? "All" : `${b}`} <span className="count">
                {b === "All" ? recs.filter((r) => domain === "All" || r.domain_id === domain).length
                  : recs.filter((r) => r.priority === b && (domain === "All" || r.domain_id === domain)).length}
              </span>
            </button>
          ))}
        </div>
        <select value={domain} onChange={(e) => setDomain(e.target.value)} aria-label="Filter by area">
          <option value="All">All areas</option>
          {result.scores.domains.map((d) => <option key={d.domain_id} value={d.domain_id}>{d.domain_name}</option>)}
        </select>
      </div>

      <div className="recs">
        {filtered.map((r) => (
          <article key={r.question_id} id={`rec-${r.question_id}`} className={`card rec ${planned[r.question_id] ? "planned" : ""}`}>
            <header className="rec-head">
              <span className={`band-pill band-${r.priority}`}>{r.priority}</span>
              <span className="muted small">{r.domain_name} · {r.stage_name} stage · {r.question_id}</span>
              <label className="plan-toggle">
                <input type="checkbox" checked={!!planned[r.question_id]}
                  onChange={(e) => setPlanned((p) => ({ ...p, [r.question_id]: e.target.checked }))} />
                Planned
              </label>
            </header>
            <h3 className="rec-statement">{r.text}</h3>
            {r.narrative && <p className="rec-narrative">{r.narrative}</p>}
            <details className="rec-steps" open={!r.narrative}>
              <summary>Next steps</summary>
              <ul>{r.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </details>
            {r.resource_ids.length > 0 && (
              <div className="rec-res">
                {r.resource_ids.map((id) => (
                  <span key={id} className="res-tag" title={resById[id]?.source}>📄 {resById[id]?.title ?? id}</span>
                ))}
              </div>
            )}
          </article>
        ))}
        {filtered.length === 0 && <p className="muted">No recommendations match these filters.</p>}
      </div>
    </section>
  );
}
