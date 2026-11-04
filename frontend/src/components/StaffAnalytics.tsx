import { useEffect, useState } from "react";
import { api } from "../api";
import type { Analytics, StaffAssessmentRow } from "../types";
import { STAGES } from "../types";
import { StaffAssessment } from "./StaffAssessment";
import { NetworkStageCells } from "./StageProfileView";

type Tab = "overview" | "assessments";

export function StaffAnalytics() {
  const [tab, setTab] = useState<Tab>("overview");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [category, setCategory] = useState("");
  const [data, setData] = useState<Analytics | null>(null);
  const [rows, setRows] = useState<StaffAssessmentRow[] | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api.analytics({ from, to, category }).then(setData).catch(() => setError("Couldn't load analytics."));
    api.staffAssessments({ from, to, category }).then(setRows).catch(() => setError("Couldn't load assessments."));
  }, [from, to, category]);

  if (selected) {
    return <StaffAssessment submissionId={selected} onBack={() => setSelected(null)} />;
  }

  const maxShare = Math.max(1, ...(data?.most_common_gaps.map((g) => g.share_pct) ?? [1]));
  const domainNames = data?.domain_averages.map((d) => ({ id: d.domain_id, name: d.domain_name })) ?? [];

  return (
    <section className="staff">
      <div className="results-hero">
        <div>
          <p className="eyebrow">CSF staff</p>
          <h1>{tab === "overview" ? "Network capacity overview" : "Individual assessments"}</h1>
          <p className="muted">
            {tab === "overview"
              ? "Aggregate figures across completed assessments."
              : "Staff only. Open an assessment to see the feedback the organization received, linked insights, and to ask questions about it."}
          </p>
        </div>
        <div className="tabs staff-tabs" role="tablist">
          <button role="tab" aria-selected={tab === "overview"} className={`tab ${tab === "overview" ? "active" : ""}`}
            onClick={() => setTab("overview")}>Network overview</button>
          <button role="tab" aria-selected={tab === "assessments"} className={`tab ${tab === "assessments" ? "active" : ""}`}
            onClick={() => setTab("assessments")}>Assessments{rows ? ` (${rows.length})` : ""}</button>
        </div>
      </div>

      <div className="card filters-bar">
        <label className="field inline"><span>From</span>
          <input type="date" value={from} onChange={(e) => setFrom(e.target.value)} /></label>
        <label className="field inline"><span>To</span>
          <input type="date" value={to} onChange={(e) => setTo(e.target.value)} /></label>
        <label className="field inline"><span>Category</span>
          <select value={category} onChange={(e) => setCategory(e.target.value)}>
            <option value="">All organizations</option>
            <option value="grantee">Grantees</option>
            <option value="non_grantee">Non-grantees</option>
          </select></label>
        {(from || to || category) && (
          <button className="linklike" onClick={() => { setFrom(""); setTo(""); setCategory(""); }}>Clear filters</button>
        )}
      </div>

      {error && <div className="alert error">{error}</div>}

      {tab === "assessments" && rows && (
        rows.length === 0 ? <p className="muted">No assessments match these filters.</p> : (
          <div className="card table-card">
            <table className="assess-table">
              <thead>
                <tr>
                  <th>Organization</th>
                  <th>Date</th>
                  {domainNames.map((d) => <th key={d.id}>{d.name}</th>)}
                  <th>Gaps</th>
                  <th aria-label="Open" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.submission_id} onClick={() => setSelected(r.submission_id)} className="clickable">
                    <td>
                      <strong>{r.org_name}</strong>
                      <div className="muted small">
                        {r.category === "grantee" ? "Grantee" : "Non-grantee"}
                        {r.synthetic && " · synthetic"}
                        {r.context_count > 0 && <span className="chip updated-chip">added context</span>}
                      </div>
                    </td>
                    <td className="nowrap">{r.timestamp.slice(0, 10)}</td>
                    {domainNames.map((d) => {
                      const s = r.domains.find((x) => x.domain_id === d.id);
                      return (
                        <td key={d.id}>
                          {s ? <><span className="stage-chip">{s.estimated_stage}</span>
                            <div className="muted small">{Math.round(s.score_pct)}%</div></> : "–"}
                        </td>
                      );
                    })}
                    <td className="nowrap">{r.overall_stats.total_gaps} <span className="muted small">({r.overall_stats.high_priority} High)</span></td>
                    <td><button className="btn ghost small" onClick={(e) => { e.stopPropagation(); setSelected(r.submission_id); }}>Open</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      )}

      {tab === "overview" && data && (
        <>
          <div className="stat-row">
            <div className="stat"><span className="stat-num">{data.total_submissions}</span><span>assessments</span></div>
            <div className="stat"><span className="stat-num">{data.by_category.grantee}</span><span>grantees</span></div>
            <div className="stat"><span className="stat-num">{data.by_category.non_grantee}</span><span>non-grantees</span></div>
          </div>

          {data.total_submissions === 0 ? (
            <p className="muted">No assessments match these filters.</p>
          ) : (
            <>
              <div className="two-col">
                <div className="card">
                  <h2 className="section-title">Average capacity by area</h2>
                  <div className="bars">
                    {data.domain_averages.map((d) => (
                      <div key={d.domain_id} className="bar-row">
                        <div className="bar-label">
                          <strong>{d.domain_name}</strong>
                          <span className="muted small">most common stage: {d.avg_stage}</span>
                        </div>
                        <div className="bar-track"><div className="bar-fill" style={{ width: `${d.avg_capacity_pct}%` }} /></div>
                        <span className="bar-val">{d.avg_capacity_pct}%</span>
                        <div className="stage-dist" title="How many assessments reached each stage">
                          {STAGES.map((s, i) => {
                            const n = d.stage_distribution[s] ?? 0;
                            return n ? (
                              <span key={s} className={`sd sd-${i}`} style={{ flex: n }} title={`${s}: ${n}`}>{n}</span>
                            ) : null;
                          })}
                        </div>
                      </div>
                    ))}
                  </div>
                  <div className="stage-legend">
                    {STAGES.map((s, i) => <span key={s}><i className={`sd-${i}`} />{s}</span>)}
                  </div>
                </div>

                <div className="card">
                  <h2 className="section-title">Most common capacity gaps</h2>
                  <ol className="gap-list">
                    {data.most_common_gaps.map((g) => (
                      <li key={g.question_id}>
                        <div className="gap-top">
                          <span className="chip">{g.domain_name} · {g.question_id}</span>
                          <span className="muted small">{g.occurrences} of {data.total_submissions} ({g.share_pct}%)</span>
                        </div>
                        <p>{g.text}</p>
                        <div className="bar-track thin"><div className="bar-fill" style={{ width: `${(g.share_pct / maxShare) * 100}%` }} /></div>
                      </li>
                    ))}
                  </ol>
                </div>
              </div>

              <div className="card">
                <h2 className="section-title">Why stages and percentages can differ</h2>
                <p className="muted small">
                  {data.stage_rule} Below: on average, how much of each stage is in place across the network. Organizations
                  see the same stage-by-stage view for their own assessment, so a conversation about "your stage" and
                  "the network" uses one definition.
                </p>
                <div className="network-stages">
                  {data.domain_averages.map((d) => (
                    <div key={d.domain_id} className="area-row">
                      <div className="area-head"><strong>{d.domain_name}</strong>
                        <span className="muted small">most common stage: {d.avg_stage}</span></div>
                      <NetworkStageCells cells={d.stage_profile} label={`${d.domain_name}: average practices in place by stage`} />
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}
        </>
      )}
    </section>
  );
}
