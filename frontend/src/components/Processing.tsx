import { useEffect, useRef, useState } from "react";
import { api, ApiError } from "../api";
import type { Answer, ProcessingStep, Profile, SubmissionResult } from "../types";

const STEPS: { id: Exclude<ProcessingStep, "done">; label: string; detail: string }[] = [
  { id: "reading", label: "Reading your answers", detail: "Scoring each area with the OCI engine" },
  { id: "consulting", label: "Consulting CVI resources", detail: "Matching your gaps to the resource library" },
  { id: "researching", label: "Researching your organization", detail: "Reading your website and drafting recommendations" },
];
const MIN_STEP_MS = 1400;

/**
 * The API runs every phase in one request, so the indicators are
 * time-sequenced here; the move to results is gated on the real response.
 */
export function Processing({ profile, answers, onDone, onError }: {
  profile: Profile;
  answers: Record<string, Answer>;
  onDone: (r: SubmissionResult) => void;
  onError: () => void;
}) {
  const [active, setActive] = useState(0);
  const [error, setError] = useState<string | null>(null);
  const [response, setResponse] = useState<SubmissionResult | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (started.current) return;
    started.current = true;
    api.submit(profile, answers)
      .then(setResponse)
      .catch((e: unknown) => setError(e instanceof ApiError ? e.message : "Something went wrong. Please try again."));
  }, [profile, answers]);

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
      <p className="lede">This usually takes under a minute.</p>
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
        <div className="alert error" role="alert">
          {error}{" "}
          <button className="linklike" onClick={onError}>Back to the questionnaire</button>
        </div>
      )}
    </section>
  );
}
