import { useEffect, useMemo, useState } from "react";
import { api, ApiError } from "../api";
import { sessionStore, storage } from "../config";
import type { Answer, Band, ChatMessage, Recommendation, ResourceInfo, SubmissionResult } from "../types";
import { AssessmentChat } from "./AssessmentChat";
import { StageCells } from "./StageProfileView";

const BANDS: Band[] = ["High", "Medium", "Low"];
const BAND_LABEL: Record<Band, string> = { High: "Start here", Medium: "Next", Low: "Later" };
const POLL_MS = 3000;
const MAX_WAIT_MS = 6 * 60 * 1000;
const MAX_CONTEXT_CHARS = 3000;

const SUGGESTIONS = [
  "We're a very small team. How should we pace these recommendations?",
  "We already do some of this informally. Does the feedback account for that?",
  "Why is our first recommendation the place to start?",
];

const label = (a: Answer | null | undefined) => (a === "yes" ? "Yes" : a === "no" ? "No" : "not answered");

/**
 * Lets the organization correct its own answer to one statement. The engine re-scores a
 * corrected copy as a new submission; the AI never changes answers.
 */
function ChangeAnswer({ r, answer, onConfirm }: {
  r: Recommendation;
  answer: Answer | null | undefined;
  onConfirm: (to: Answer) => void;
}) {
  const [open, setOpen] = useState(false);
  if (answer !== "yes" && answer !== "no") return null;
  const to: Answer = answer === "yes" ? "no" : "yes";
  if (!open) {
    return (
      <button type="button" className="linklike change-answer-link" onClick={() => setOpen(true)}>
        Change my answer
      </button>
    );
  }
  return (
    <div className="change-answer" role="group" aria-label={`Change your answer to ${r.question_id}`}>
      <p>
        You answered <strong>{label(answer)}</strong> to: “{r.text}” Change it to <strong>{label(to)}</strong>?
      </p>
      <p className="muted small">
        This re-scores a corrected copy of your assessment with the OCI engine. Your other answers stay the
        same, the original assessment is kept, and any context you added carries over.
      </p>
      <div className="change-answer-actions">
        <button type="button" className="btn primary small" onClick={() => onConfirm(to)}>
          Change to {label(to)} and re-score
        </button>
        <button type="button" className="linklike" onClick={() => setOpen(false)}>Cancel</button>
      </div>
    </div>
  );
}

async function waitForRevision(id: string): Promise<SubmissionResult> {
  const deadline = Date.now() + MAX_WAIT_MS;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
    try {
      const latest = await api.submission(id);
      if (latest.revision_status !== "pending") return latest;
    } catch {
      /* transient network or proxy error: keep waiting */
    }
  }
  throw new ApiError(504, "The update is taking longer than expected. Refresh in a few minutes to see it.");
}

function RecBody({ r, resById }: { r: Recommendation; resById: Record<string, ResourceInfo> }) {
  return (
    <>
      {r.narrative && <p className="rec-narrative">{r.narrative}</p>}
      <details className="rec-steps" open={!r.narrative}>
        <summary>Next steps</summary>
        <ul>{r.next_steps.map((s, i) => <li key={i}>{s}</li>)}</ul>
      </details>
      {r.resource_ids.length > 0 && (
        <div className="rec-res">
          {r.resource_ids.map((id) => (
            <span key={id} className="res-tag" title={resById[id]?.source}>{resById[id]?.title ?? id}</span>
          ))}
        </div>
      )}
    </>
  );
}

export function Results({ result, onResultChange, onStartOver, onChangeAnswer }: {
  result: SubmissionResult;
  onResultChange: (r: SubmissionResult) => void;
  onStartOver: () => void;
  onChangeAnswer?: (questionId: string, to: Answer) => void;
}) {
  const id = result.submission_id;
  const chatKey = `oci.feedbackChat.${id}`;
  const [resources, setResources] = useState<ResourceInfo[]>([]);
  const [planned, setPlanned] = useState<Record<string, boolean>>(() => storage.get(`oci.planned.${id}`, {}));
  const [chat, setChat] = useState<ChatMessage[]>(() => sessionStore.get(chatKey, []));
  const [applied, setApplied] = useState<number>(() => sessionStore.get(`${chatKey}.applied`, 0));
  const [updating, setUpdating] = useState(false);
  const [updateError, setUpdateError] = useState<string | null>(null);
  const [justUpdated, setJustUpdated] = useState(false);
  const [openAll, setOpenAll] = useState(false);

  useEffect(() => { api.resources().then(setResources).catch(() => setResources([])); }, []);
  useEffect(() => storage.set(`oci.planned.${id}`, planned), [planned, id]);
  useEffect(() => sessionStore.set(chatKey, chat), [chat, chatKey]);
  useEffect(() => sessionStore.set(`${chatKey}.applied`, applied), [applied, chatKey]);

  const degraded = result.orchestration_status === "error";
  // When narration failed, show the engine's own gaps and next steps.
  const recs: Recommendation[] = useMemo(() => {
    if (result.recommendations.length) return result.recommendations;
    const order = { High: 0, Medium: 1, Low: 2 } as const;
    return [...result.gaps]
      .sort((a, b) => order[a.priority] - order[b.priority] || b.priority_score - a.priority_score)
      .map((g) => ({ ...g, narrative: null, resource_ids: [] }));
  }, [result]);

  const resById = Object.fromEntries(resources.map((r) => [r.id, r]));
  const stats = result.scores.overall_stats;
  const date = new Date(result.timestamp).toLocaleDateString(undefined, { year: "numeric", month: "long", day: "numeric" });
  const startHere = recs.filter((r) => r.priority === "High").slice(0, 3);
  const thisMonth = result.action_plan[0];
  const contexts = result.org_context ?? [];
  const newContext = chat.slice(applied).filter((m) => m.role === "user").map((m) => m.content);
  const plannedCount = Object.values(planned).filter(Boolean).length;
  const canRetry = result.revision_status === "error" && contexts.length > 0;

  const jumpTo = (qid: string) => {
    setOpenAll(true);
    window.setTimeout(() => {
      const el = document.getElementById(`rec-${qid}`) as HTMLDetailsElement | null;
      if (el) { el.open = true; el.scrollIntoView({ behavior: "smooth", block: "center" }); }
    }, 60);
  };

  const updateFeedback = async (context: string) => {
    setUpdating(true);
    setUpdateError(null);
    setJustUpdated(false);
    try {
      const { status, body } = await api.revise(id, context.slice(0, MAX_CONTEXT_CHARS));
      setApplied(chat.length);  // this context is saved on the server now, even if the update fails
      const latest = status === 202 || body.revision_status === "pending" ? await waitForRevision(id) : body;
      onResultChange(latest);
      if (latest.revision_status === "error") {
        setUpdateError("Your context is saved, but the feedback couldn't be regenerated this time. Try again in a moment.");
      } else {
        setJustUpdated(true);
      }
    } catch (e: unknown) {
      setUpdateError(e instanceof ApiError ? e.message : "The feedback couldn't be updated. Please try again.");
    } finally {
      setUpdating(false);
    }
  };

  const answerOf = Object.fromEntries(result.gaps.map((g) => [g.question_id, g.answer]));
  const changeAnswer = (r: Recommendation) => (onChangeAnswer && !result.superseded_by
    ? <ChangeAnswer r={r} answer={answerOf[r.question_id]} onConfirm={(to) => onChangeAnswer(r.question_id, to)} />
    : null);

  const plannedToggle = (r: Recommendation) => (
    <label className="plan-toggle">
      <input type="checkbox" checked={!!planned[r.question_id]}
        onChange={(e) => setPlanned((p) => ({ ...p, [r.question_id]: e.target.checked }))} />
      Planned
    </label>
  );

  return (
    <section className="results">
      <div className="results-hero">
        <div>
          <p className="eyebrow">Step 4 of 4 · {date}</p>
          <h1>{result.profile.org_name}</h1>
          {result.profile.sample_id && (
            <p className="sample-note">Sample {result.profile.sample_id} from the OCI package · synthetic organization and answers</p>
          )}
          <p className="muted">
            {stats.total_questions} statements answered · {stats.total_gaps} practices to build on ·{" "}
            {stats.high_priority} to start with
          </p>
        </div>
        <div className="hero-actions">
          <a className="btn primary" href={api.reportUrl(id, true)} target="_blank" rel="noreferrer">
            View detailed PDF report
          </a>
          <a className="btn ghost" href={api.reportUrl(id)} download>Download</a>
          <button className="btn ghost" onClick={onStartOver}>New assessment</button>
        </div>
      </div>

      {(result.answer_changes?.length ?? 0) > 0 && (
        <div className="alert ok" role="status">
          <strong>Re-scored with your corrected answer{result.answer_changes!.length > 1 ? "s" : ""}.</strong>{" "}
          {result.answer_changes!.map((c) => `${c.question_id} “${c.text}” ${label(c.from)} → ${label(c.to)}`).join("; ")}.
          {" "}Scores, stages and priorities were recalculated by the OCI engine; your original assessment is kept.
        </div>
      )}
      {result.superseded_by && (
        <div className="alert warn" role="status">
          You corrected an answer in this assessment, so a newer, re-scored version exists. This one is kept
          for reference and no longer counts in network figures.
        </div>
      )}
      {degraded && (
        <div className="alert warn" role="status">
          <strong>Personalized narrative couldn't be generated this time.</strong> Your scores and priorities
          are complete and accurate; the recommendations use the questionnaire's standard next steps.
        </div>
      )}
      {justUpdated && (
        <div className="alert ok" role="status">
          Your feedback was updated with the context you added. Scores and priorities are unchanged.
        </div>
      )}

      {result.overview && (
        <p className="overview">
          {(result.revision_count ?? 0) > 0 && <span className="chip updated-chip">Updated with your context</span>}
          {result.overview}
        </p>
      )}

      <div className="results-grid">
        <div className="results-main">
          <h2 className="section-title">Where to start</h2>
          <div className="recs">
            {startHere.map((r) => (
              <article key={r.question_id} className={`card rec ${planned[r.question_id] ? "planned" : ""}`}>
                <header className="rec-head">
                  <span className="band-pill band-High">Start here</span>
                  <span className="muted small">{r.domain_name} · {r.question_id}</span>
                  {plannedToggle(r)}
                </header>
                <h3 className="rec-statement">{r.text}</h3>
                <RecBody r={r} resById={resById} />
                {changeAnswer(r)}
              </article>
            ))}
            {startHere.length === 0 && <p className="muted">No capacity gaps were found in this assessment.</p>}
          </div>

          {thisMonth && thisMonth.actions.length > 0 && (
            <div className="card this-month">
              <h2 className="section-title">{thisMonth.timeframe}</h2>
              <ul>
                {thisMonth.actions.map((a, i) => (
                  <li key={i}>{a.text}{" "}
                    {a.question_ids.map((q) => <button key={q} className="qref" onClick={() => jumpTo(q)}>{q}</button>)}
                  </li>
                ))}
              </ul>
              <p className="muted small">The full 30-day to 6-month plan is in your detailed report.</p>
            </div>
          )}
          {result.research_summary && (
            <div className="card research">
              <h2 className="section-title">
                {result.research_source === "sample_profile" ? "Organization profile" : "What we read on your website"}
              </h2>
              <p>{result.research_summary}</p>
              <p className="muted small">
                {result.research_source === "sample_profile"
                  ? "From the sample report in the OCI package; used in place of website research."
                  : `Summarized by AI from ${result.profile.website_url}. Tell us if anything is off.`}
              </p>
            </div>
          )}

          <h2 className="section-title">Your areas</h2>
          <div className="card areas">
            <p className="muted small">{result.stage_rule}</p>
            {result.stage_profile.map((p) => (
              <div key={p.domain_id} className="area-row">
                <div className="area-head">
                  <strong>{p.domain_name}</strong>
                  <span className="stage-chip">{p.estimated_stage}</span>
                  <span className="area-pct">{Math.round(p.score_pct)}% in place</span>
                </div>
                <StageCells profile={p} onGapClick={jumpTo} />
              </div>
            ))}
          </div>
        </div>

        <aside className="results-side">
          <div className="card pdf-callout">
            <h2 className="section-title">Your detailed report</h2>
            <p className="small">
              Area-by-area analysis, what holds each area at its stage, the full action plan, and every
              recommendation with next steps and resources.
            </p>
            <a className="btn primary block" href={api.reportUrl(id, true)} target="_blank" rel="noreferrer">
              View PDF report
            </a>
          </div>

          <AssessmentChat
            id="refine"
            title="Refine this feedback"
            intro={<>Tell us what the assessment couldn't know: your team size, what you already do informally,
              deadlines or constraints. Then update your feedback. Your answers and scores stay as submitted; to correct an answer, use “Change my answer” on that recommendation.</>}
            placeholder="For example: We have three staff and our board meets quarterly."
            suggestions={SUGGESTIONS}
            assistantName="Feedback guide"
            messages={chat}
            onMessagesChange={(m) => { setChat(m); if (m.length < applied) setApplied(0); }}
            send={(m) => api.feedbackChat(id, m)}
            notice="Don't include names of individuals or client details. Narrative is AI-generated."
            actions={
              <>
                <button type="button" className="btn primary block"
                  disabled={updating || newContext.length === 0 || result.orchestration_status === "pending"}
                  onClick={() => void updateFeedback(newContext.join("\n"))}>
                  {updating ? "Updating your feedback..." : "Update my feedback"}
                </button>
                {newContext.length === 0 && !updating && (
                  <span className="muted small">Add context in the chat, then update.</span>
                )}
                {canRetry && !updating && (
                  <button type="button" className="linklike small" onClick={() => void updateFeedback("")}>
                    Try the last update again
                  </button>
                )}
                {updateError && <span className="chat-error" role="alert">{updateError}</span>}
                {updating && <span className="muted small">This can take up to two minutes.</span>}
              </>
            }
          />

          {contexts.length > 0 && (
            <div className="card">
              <h2 className="section-title">Context you've added</h2>
              <ul className="context-list">
                {contexts.map((c, i) => <li key={i}>{c.text}</li>)}
              </ul>
            </div>
          )}
        </aside>
      </div>

      <details className="all-recs" open={openAll} onToggle={(e) => setOpenAll((e.target as HTMLDetailsElement).open)}>
        <summary>
          <span className="section-title">All recommendations ({recs.length})</span>
          <span className="muted small">
            Priority shows where to start within your own assessment, not how serious a gap is.
            {plannedCount > 0 && <strong> {plannedCount} marked as planned.</strong>}
          </span>
        </summary>
        {BANDS.map((b) => {
          const inBand = recs.filter((r) => r.priority === b);
          if (!inBand.length) return null;
          return (
            <div key={b} className="band-group">
              <h3><span className={`band-pill band-${b}`}>{BAND_LABEL[b]}</span> {inBand.length} {b} priority</h3>
              {inBand.map((r) => (
                <details key={r.question_id} id={`rec-${r.question_id}`} className={`rec-row ${planned[r.question_id] ? "planned" : ""}`}>
                  <summary>
                    <span className="rec-row-text">{r.text}</span>
                    <span className="muted small">{r.domain_name} · {r.question_id}</span>
                  </summary>
                  <div className="rec-row-body">
                    <RecBody r={r} resById={resById} />
                    {plannedToggle(r)}
                    {changeAnswer(r)}
                  </div>
                </details>
              ))}
            </div>
          );
        })}
      </details>
    </section>
  );
}
