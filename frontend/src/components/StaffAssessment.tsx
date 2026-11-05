import { useEffect, useMemo, useState } from "react";
import { api } from "../api";
import { sessionStore } from "../config";
import type { Band, ChatMessage, Insight, Recommendation, StaffAssessmentDetail } from "../types";
import { AssessmentChat } from "./AssessmentChat";
import { StageCells } from "./StageProfileView";

const BANDS: Band[] = ["High", "Medium", "Low"];
const KIND_LABEL: Record<Insight["kind"], string> = {
  stage: "Stage",
  relative: "Against the network",
  common_gap: "Shared gaps",
  distinctive_gap: "Distinctive gaps",
  context: "Organization's context",
};
const SUGGESTIONS = [
  "What should I raise first in a coaching call with them?",
  "Which of their gaps could they work on with peers in a cohort?",
  "Which area's stage is lower than its percentage suggests, and why?",
  "Summarize this assessment in three sentences for my notes.",
];

/** Staff-only view of one named assessment: the feedback the organization received, linked insights and a chat. */
export function StaffAssessment({ submissionId, onBack }: { submissionId: string; onBack: () => void }) {
  const chatKey = `oci.staffChat.${submissionId}`;
  const [data, setData] = useState<StaffAssessmentDetail | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [focus, setFocus] = useState<string | null>(null);
  const [band, setBand] = useState<Band | "All">("High");
  const [chat, setChat] = useState<ChatMessage[]>(() => sessionStore.get(chatKey, []));

  useEffect(() => {
    setData(null);
    setError(null);
    api.staffAssessment(submissionId).then(setData).catch(() => setError("Couldn't load this assessment."));
  }, [submissionId]);
  useEffect(() => sessionStore.set(chatKey, chat), [chat, chatKey]);

  const recs: Recommendation[] = useMemo(() => {
    if (!data) return [];
    if (data.recommendations.length) return data.recommendations;
    const order = { High: 0, Medium: 1, Low: 2 } as const;
    return [...data.gaps]
      .sort((a, b) => order[a.priority] - order[b.priority] || b.priority_score - a.priority_score)
      .map((g) => ({ ...g, narrative: null, resource_ids: [] }));
  }, [data]);
  const recById = Object.fromEntries(recs.map((r) => [r.question_id, r]));

  if (error) return <div className="alert error">{error} <button className="linklike" onClick={onBack}>Back</button></div>;
  if (!data) return <p className="loading">Loading assessment...</p>;

  const focused = focus ? recById[focus] : null;
  const date = new Date(data.timestamp).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  const shown = recs.filter((r) => band === "All" || r.priority === band);
  const share = data.network.gap_share_pct;

  return (
    <section className="staff-detail">
      <button className="linklike small" onClick={onBack}>← All assessments</button>
      <div className="results-hero">
        <div>
          <p className="eyebrow">CSF staff · individual assessment</p>
          <h1>{data.profile.org_name}</h1>
          <p className="muted">
            {data.profile.category === "grantee" ? "Grantee" : "Non-grantee"} · {date} ·{" "}
            {data.scores.overall_stats.total_gaps} gaps ({data.scores.overall_stats.high_priority} High)
            {(data.revision_count ?? 0) > 0 && <> · feedback refined {data.revision_count}×</>}
          </p>
        </div>
        <div className="hero-actions">
          <a className="btn ghost" href={api.reportUrl(submissionId, true)} target="_blank" rel="noreferrer">
            View the organization's PDF
          </a>
        </div>
      </div>

      {data.orchestration_status === "seed" && (
        <div className="alert warn">Pre-loaded assessment: it has scores but no AI narrative.</div>
      )}

      <div className="results-grid">
        <div className="results-main">
          <h2 className="section-title">Insights</h2>
          <div className="insights">
            {data.insights.map((ins, i) => (
              <article key={i} className={`card insight kind-${ins.kind}`}>
                <span className="insight-kind">{KIND_LABEL[ins.kind]}</span>
                <h3>{ins.title}</h3>
                <p className="small">{ins.detail}</p>
                {ins.question_ids.length > 0 && (
                  <div className="insight-refs">
                    {ins.question_ids.map((q) => (
                      <button key={q} type="button" className={`qref ${focus === q ? "active" : ""}`}
                        onClick={() => setFocus(focus === q ? null : q)} title={recById[q]?.text}>
                        {q}
                      </button>
                    ))}
                  </div>
                )}
              </article>
            ))}
            {data.insights.length === 0 && <p className="muted">No notable insights for this assessment.</p>}
          </div>

          {focused && (
            <article className="card rec focus-rec" aria-live="polite">
              <header className="rec-head">
                <span className={`band-pill band-${focused.priority}`}>{focused.priority}</span>
                <span className="muted small">
                  {focused.domain_name} · {focused.stage_name} stage · {focused.question_id}
                  {share[focused.question_id] !== undefined && <> · a gap for {share[focused.question_id]}% of the network</>}
                </span>
                <button className="linklike small plan-toggle" onClick={() => setFocus(null)}>Close</button>
              </header>
              <h3 className="rec-statement">{focused.text}</h3>
              <p className="muted small">Feedback the organization received:</p>
              {focused.narrative ? <p className="rec-narrative">{focused.narrative}</p>
                : <p className="muted small">No narrative (standard next steps only).</p>}
              <ul className="muted">{focused.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ul>
            </article>
          )}

          <h2 className="section-title">Areas and stages</h2>
          <div className="card areas">
            <p className="muted small">{data.stage_rule} The same view appears on the organization's results page and PDF.</p>
            {data.stage_profile.map((p) => {
              const net = data.network.avg_capacity_pct[p.domain_id];
              return (
                <div key={p.domain_id} className="area-row">
                  <div className="area-head">
                    <strong>{p.domain_name}</strong>
                    <span className="stage-chip">{p.estimated_stage}</span>
                    <span className="area-pct">
                      {Math.round(p.score_pct)}% in place{net !== undefined && <span className="muted"> · network {Math.round(net)}%</span>}
                    </span>
                  </div>
                  <StageCells profile={p} network={data.network.stage_profile[p.domain_id]} onGapClick={setFocus} />
                </div>
              );
            })}
          </div>

          {data.overview && (
            <>
              <h2 className="section-title">Overview the organization received</h2>
              <p className="overview">{data.overview}</p>
            </>
          )}

          <div className="recs-head">
            <h2 className="section-title">Their recommendations</h2>
            <div className="chips" role="group" aria-label="Filter by priority">
              {(["All", ...BANDS] as const).map((b) => (
                <button key={b} className={`chip-btn ${band === b ? "active" : ""}`} onClick={() => setBand(b)}>
                  {b} <span className="count">{b === "All" ? recs.length : recs.filter((r) => r.priority === b).length}</span>
                </button>
              ))}
            </div>
          </div>
          <div className="band-group">
            {shown.map((r) => (
              <details key={r.question_id} className="rec-row">
                <summary>
                  <span className="rec-row-text">{r.text}</span>
                  <span className="muted small">
                    {r.priority} · {r.domain_name} · {r.question_id}
                    {share[r.question_id] !== undefined && <> · {share[r.question_id]}% of network</>}
                  </span>
                </summary>
                <div className="rec-row-body">
                  {r.narrative && <p className="rec-narrative">{r.narrative}</p>}
                  <ul className="muted">{r.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ul>
                </div>
              </details>
            ))}
          </div>
        </div>

        <aside className="results-side">
          <AssessmentChat
            id="staff-chat"
            title={`Ask about ${data.profile.org_name}`}
            intro={<>Ask specific questions about this assessment. Answers are grounded in its scores, feedback and
              network aggregates, and cite question ids.</>}
            placeholder="For example: What would a realistic 90-day focus look like for them?"
            suggestions={SUGGESTIONS}
            assistantName="Assessment assistant"
            messages={chat}
            onMessagesChange={setChat}
            send={(m) => api.staffChat(submissionId, m)}
          />
          {(data.org_context?.length ?? 0) > 0 && (
            <div className="card">
              <h2 className="section-title">Context the organization added</h2>
              <ul className="context-list">
                {data.org_context!.map((c, i) => (
                  <li key={i}>{c.text} <span className="muted small">({c.timestamp.slice(0, 10)})</span></li>
                ))}
              </ul>
            </div>
          )}
        </aside>
      </div>
    </section>
  );
}
