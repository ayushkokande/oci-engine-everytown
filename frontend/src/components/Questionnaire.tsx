import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api";
import { storage } from "../config";
import type { Answer, Profile, Question, QuestionsPayload } from "../types";
import { STAGES } from "../types";

type FlatQ = Question & { domainId: string; domainName: string; indexInDomain: number; domainSize: number };

export function Questionnaire({ profile, onSubmit, onBack }: {
  profile: Profile;
  onSubmit: (answers: Record<string, Answer>) => void;
  onBack: () => void;
}) {
  const [data, setData] = useState<QuestionsPayload | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [answers, setAnswers] = useState<Record<string, Answer>>(() => storage.get("oci.answers", {}));
  const [index, setIndex] = useState(0);
  const [view, setView] = useState<"quiz" | "list">("quiz");
  const [showMissing, setShowMissing] = useState(false);
  const advanceTimer = useRef<number | null>(null);

  useEffect(() => {
    api.questions().then(setData).catch(() => setLoadError("Couldn't load the questionnaire. Is the API running?"));
  }, []);

  useEffect(() => storage.set("oci.answers", answers), [answers]);

  const flat: FlatQ[] = useMemo(() => {
    if (!data) return [];
    return data.domains.flatMap((d) =>
      d.questions.map((q, i) => ({ ...q, domainId: d.id, domainName: d.name, indexInDomain: i, domainSize: d.questions.length })));
  }, [data]);

  // Drop stale answers for statements no longer in scope.
  const scopedAnswers = useMemo(() => {
    const ids = new Set(flat.map((q) => q.id));
    return Object.fromEntries(Object.entries(answers).filter(([k]) => ids.has(k))) as Record<string, Answer>;
  }, [answers, flat]);

  const answered = Object.keys(scopedAnswers).length;
  const total = flat.length;
  const complete = total > 0 && answered === total;
  const current = flat[index];
  const missing = flat.filter((q) => !scopedAnswers[q.id]);

  const goto = useCallback((i: number) => setIndex(Math.max(0, Math.min(flat.length - 1, i))), [flat.length]);

  const answer = useCallback((qid: string, value: Answer, autoAdvance = true) => {
    setAnswers((a) => ({ ...a, [qid]: value }));
    if (autoAdvance) {
      if (advanceTimer.current) window.clearTimeout(advanceTimer.current);
      advanceTimer.current = window.setTimeout(() => {
        setIndex((i) => {
          const pos = flat.findIndex((q) => q.id === qid);
          return pos >= 0 && pos < flat.length - 1 ? pos + 1 : i;
        });
      }, 220);
    }
  }, [flat]);

  useEffect(() => {
    if (view !== "quiz") return;
    const onKey = (e: KeyboardEvent) => {
      if (!current || (e.target as HTMLElement)?.tagName === "INPUT" || (e.target as HTMLElement)?.tagName === "SELECT") return;
      const k = e.key.toLowerCase();
      if (k === "y" || k === "1") answer(current.id, "yes");
      else if (k === "n" || k === "2") answer(current.id, "no");
      else if (k === "arrowright") goto(index + 1);
      else if (k === "arrowleft") goto(index - 1);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [view, current, index, answer, goto]);

  const loadSample = async (id: string) => {
    if (!id) return;
    const s = await api.sample(id);
    setAnswers(s.answers);
    setIndex(flat.length - 1);
  };

  if (loadError) return <div className="alert error">{loadError}</div>;
  if (!data || !current) return <div className="loading">Loading questionnaire…</div>;

  const domainStats = data.domains.map((d) => ({
    id: d.id, name: d.name, total: d.questions.length,
    done: d.questions.filter((q) => scopedAnswers[q.id]).length,
    first: flat.findIndex((q) => q.domainId === d.id),
  }));

  return (
    <section className="quiz">
      <aside className="quiz-rail">
        <p className="eyebrow">Step 2 of 4</p>
        <h2 className="rail-org">{profile.org_name}</h2>
        <div className="overall">
          <div className="overall-bar"><div style={{ width: `${(answered / total) * 100}%` }} /></div>
          <span>{answered} of {total} answered</span>
        </div>
        <ul className="rail-domains">
          {domainStats.map((d) => (
            <li key={d.id}>
              <button className={`rail-domain ${current.domainId === d.id ? "active" : ""}`}
                onClick={() => { setView("quiz"); goto(d.first); }}>
                <span className="rd-name">{d.name}</span>
                <span className={`rd-count ${d.done === d.total ? "full" : ""}`}>{d.done}/{d.total}</span>
                <span className="rd-bar"><span style={{ width: `${(d.done / d.total) * 100}%` }} /></span>
              </button>
            </li>
          ))}
        </ul>
        <div className="rail-tools">
          <div className="view-toggle" role="group" aria-label="View">
            <button className={view === "quiz" ? "active" : ""} onClick={() => setView("quiz")}>One at a time</button>
            <button className={view === "list" ? "active" : ""} onClick={() => setView("list")}>All statements</button>
          </div>
          <label className="demo-fill">
            <span>Demo: fill with synthetic answers</span>
            <select defaultValue="" onChange={(e) => { loadSample(e.target.value); e.target.value = ""; }}>
              <option value="" disabled>Choose a sample…</option>
              <option value="A">Sample A · early-stage org</option>
              <option value="B">Sample B · developing org</option>
              <option value="C">Sample C · established org</option>
            </select>
          </label>
          <button className="linklike" onClick={onBack}>← Edit organization details</button>
        </div>
      </aside>

      <div className="quiz-main">
        {view === "quiz" ? (
          <div className="qcard card" key={current.id}>
            <div className="qcard-meta">
              <span className="chip">{current.domainName}</span>
              <span>Statement {current.indexInDomain + 1} of {current.domainSize}</span>
              <span className="muted">· {STAGES[current.stage - 1]} practice</span>
            </div>
            <p className="qcard-prompt">Is this true of your organization today?</p>
            <h2 className="qcard-text">{current.text}</h2>
            <div className="yn">
              {(["yes", "no"] as Answer[]).map((v) => (
                <button key={v} className={`yn-btn ${scopedAnswers[current.id] === v ? "selected" : ""}`}
                  aria-pressed={scopedAnswers[current.id] === v} onClick={() => answer(current.id, v)}>
                  <span className="yn-key">{v === "yes" ? "Y" : "N"}</span>
                  {v === "yes" ? "Yes" : "No"}
                </button>
              ))}
            </div>
            <div className="qcard-nav">
              <button className="btn ghost" onClick={() => goto(index - 1)} disabled={index === 0}>← Previous</button>
              <span className="muted kbd-hint">Keyboard: Y / N to answer, ← → to move</span>
              <button className="btn ghost" onClick={() => goto(index + 1)} disabled={index === flat.length - 1}>Next →</button>
            </div>
          </div>
        ) : (
          <div className="qlist">
            {data.domains.map((d) => (
              <div key={d.id} className="card qlist-domain">
                <h3>{d.name}</h3>
                {d.questions.map((q) => {
                  const isMissing = showMissing && !scopedAnswers[q.id];
                  return (
                    <div key={q.id} className={`qrow ${isMissing ? "missing" : ""}`} id={`q-${q.id}`}>
                      <span className="qrow-text">{q.text}</span>
                      <span className="qrow-yn">
                        {(["yes", "no"] as Answer[]).map((v) => (
                          <button key={v} className={`mini-yn ${scopedAnswers[q.id] === v ? "selected" : ""}`}
                            aria-pressed={scopedAnswers[q.id] === v} onClick={() => answer(q.id, v, false)}>
                            {v === "yes" ? "Yes" : "No"}
                          </button>
                        ))}
                      </span>
                    </div>
                  );
                })}
              </div>
            ))}
          </div>
        )}

        <div className={`submit-bar ${complete ? "ready" : ""}`}>
          {complete ? (
            <span><strong>All {total} statements answered.</strong> You can still change any answer.</span>
          ) : (
            <span>
              <strong>{total - answered}</strong> statement{total - answered === 1 ? "" : "s"} left.{" "}
              <button className="linklike" onClick={() => {
                setShowMissing(true);
                const i = flat.findIndex((q) => !scopedAnswers[q.id]);
                if (view === "quiz") goto(i);
                else document.getElementById(`q-${missing[0]?.id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
              }}>Go to the next unanswered one</button>
            </span>
          )}
          <button className="btn primary" disabled={!complete} onClick={() => onSubmit(scopedAnswers)}>
            Submit for analysis
          </button>
        </div>
      </div>
    </section>
  );
}
