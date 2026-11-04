import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Answer, ProcessingStep, Profile, SubmissionResult } from "../types";

const STEPS: { id: Exclude<ProcessingStep, "done">; label: string; detail: string }[] = [
  { id: "reading", label: "Reading your answers", detail: "Scoring each area with the OCI engine" },
  { id: "consulting", label: "Consulting CVI resources", detail: "Matching your gaps to the resource library" },
  { id: "researching", label: "Researching your organization", detail: "Reading your website and drafting recommendations" },
];
const MIN_STEP_MS = 1400;
const POLL_MS = 3000;
const MAX_WAIT_MS = 6 * 60 * 1000;

/**
 * With OCI_ASYNC_ORCHESTRATION the API saves the scores and answers "pending" at once,
 * then adds Claude's narrative in the background. Poll until it is ready; if it never
 * arrives, show the (complete) scores with the questionnaire's own next steps.
 */
async function waitForNarrative(first: SubmissionResult): Promise<SubmissionResult> {
  const deadline = Date.now() + MAX_WAIT_MS;
  let latest = first;
  while (Date.now() < deadline) {
    await new Promise((resolve) => window.setTimeout(resolve, POLL_MS));
    try {
      latest = await api.submission(first.submission_id);
    } catch {
      continue; // transient network or proxy error: keep waiting
    }
    if (latest.orchestration_status !== "pending") return latest;
  }
  return { ...latest, orchestration_status: "error", orchestration_error: "narrative_timeout" };
}

/**
 * The indicators are time-sequenced here; the move to results is gated on the
 * real (final) response.
 */
export function Processing({ profile, answers, run, onDone, onError, errorLabel }: {
  profile: Profile;
  answers: Record<string, Answer>;
  /** Overrides the default submit, e.g. to re-score corrected answers. */
  run?: () => Promise<SubmissionResult>;
  onDone: (r: SubmissionResult) => void;
  onError: () => void;
  errorLabel?: string;
}) {
  const [active, setActive] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<SubmissionResult | null>(null);
  const [attempt, setAttempt] = useState(0);
  const started = useRef(-1);

  useEffect(() => {
    if (started.current === attempt) return;  // StrictMode runs effects twice in dev
    started.current = attempt;
    (run ? run() : api.submit(profile, answers))
      .then((r) => (r.orchestration_status === "pending" ? waitForNarrative(r) : r))
      .then(setResponse)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message
        : `Unexpected error: ${e instanceof Error ? e.message : String(e)}. Your answers are saved.`));
  }, [profile, answers, attempt]);

  const retry = () => {
    setError(null);
    setResponse(null);
    setActive(0);
    setAttempt((a) => a + 1);
  };

  // Advance one indicator per MIN_STEP_MS; the last one waits for the real response.
  useEffect(() => {
    if (error || active >= STEPS.length) return;
    if (active === STEPS.length - 1 && !response) return;
    const t = window.setTimeout(() => setActive((a) => a + 1), MIN_STEP_MS);
    return () => window.clearTimeout(t);
  }, [active, response, error]);

  useEffect(() => {
    if (active < STEPS.length || !response) return;
    const t = window.setTimeout(() => onDone(response), 450);
    return () => window.clearTimeout(t);
  }, [active, response, onDone]);

  return (
    <section className="narrow processing">
      <p className="eyebrow">Step 3 of 4</p>
      <h1>Preparing recommendations for {profile.org_name}</h1>
      <p className="lede">This can take up to two minutes.</p>
      <ol className="proc-list card" aria-live="polite">
        {STEPS.map((s, i) => {
          const state = i < active ? "done" : i === active && !error ? "active" : "todo";
          return (
            <li key={s.id} className={`proc ${state}`}>
              <span className="proc-icon" aria-hidden>
                {state === "done" ? "✓" : state === "active" ? <span className="spinner" /> : ""}
              </span>
              <span>
                <strong>{s.label}</strong>
                <small>{s.detail}</small>
              </span>
            </li>
          );
        })}
      </ol>
      {error && (
        <div className="alert error proc-error" role="alert">
          <span>{error}</span>
          <span className="proc-error-actions">
            <button className="btn primary small" onClick={retry}>Try again</button>
            <button className="linklike" onClick={onError}>{errorLabel ?? "Back to the questionnaire"}</button>
          </span>
        </div>
      )}
    </section>
  );
}
