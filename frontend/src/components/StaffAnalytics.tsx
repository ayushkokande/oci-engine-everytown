import { useEffect, useState } from "react";
import { api } from "../api";
import type { Analytics } from "../types";
import { STAGES } from "../types";

export function StaffAnalytics() {
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [category, setCategory] = useState("");
  const [data, setData] = useState<Analytics | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setError(null);
    api.analytics({ from, to, category })
      .then(setData)
      .catch(() => setError("Couldn't load analytics."));
  }, [from, to, category]);

  const maxShare = Math.max(1, ...(data?.most_common_gaps.map((g) => g.share_pct) ?? [1]));

  return (
    <section className="staff">
      <div className="results-hero">
        <div>
          <p className="eyebrow">CSF staff</p>
          <h1>Network capacity overview</h1>
          <p className="muted">
            Aggregate figures across completed assessments. No individual organization is named or compared.
          </p>
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
      {data && (
        <>
          <div className="stat-row">
            <div className="stat"><span className="stat-num">{data.total_submissions}</span><span>assessments</span></div>
            <div className="stat"><span className="stat-num">{data.by_category.grantee}</span><span>grantees</span></div>
            <div className="stat"><span className="stat-num">{data.by_category.non_grantee}</span><span>non-grantees</span></div>
          </div>

          {data.total_submissions === 0 ? (
            <p className="muted">No assessments match these filters.</p>
          ) : (
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
                      <div className="stage-dist" title="Stage distribution">
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
                        <span className="chip">{g.domain_name}</span>
                        <span className="muted small">{g.occurrences} of {data.total_submissions} ({g.share_pct}%)</span>
                      </div>
                      <p>{g.text}</p>
                      <div className="bar-track thin"><div className="bar-fill" style={{ width: `${(g.share_pct / maxShare) * 100}%` }} /></div>
                    </li>
                  ))}
                </ol>
              </div>
            </div>
          )}
        </>
      )}
    </section>
  );
}
