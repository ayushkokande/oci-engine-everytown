import { useEffect, useState } from "react";
import { api } from "./api";
import { storage } from "./config";
import type { Answer, ApiConfig, AppStep, Profile, Role, SubmissionResult } from "./types";
import { Login } from "./components/Login";
import { ProfileForm } from "./components/ProfileForm";
import { Questionnaire } from "./components/Questionnaire";
import { Processing } from "./components/Processing";
import { Results } from "./components/Results";
import { StaffAnalytics } from "./components/StaffAnalytics";

const EMPTY_PROFILE: Profile = { org_name: "", website_url: "", category: "grantee" };

export default function App() {
  const [step, setStep] = useState<AppStep>("login");
  const [role, setRole] = useState<Role | null>(null);
  const [profile, setProfile] = useState<Profile>(() => storage.get("oci.profile", EMPTY_PROFILE));
  const [pending, setPending] = useState<Record<string, Answer> | null>(null);
  const [result, setResult] = useState<SubmissionResult | null>(null);
  const [config, setConfig] = useState<ApiConfig | null>(null);

  useEffect(() => {
    api.config().then(setConfig).catch(() => setConfig(null));
  }, []);

  const signOut = () => {
    setRole(null);
    setResult(null);
    setStep("login");
  };

  const startOver = () => {
    storage.remove("oci.answers");
    setResult(null);
    setStep("profile");
  };

  return (
    <div className="shell">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            <svg viewBox="0 0 32 32" width="28" height="28">
              <rect width="32" height="32" rx="8" fill="var(--ink)" />
              <path d="M8 22 L14 14 L18 18 L24 9" stroke="var(--paper)" strokeWidth="3" fill="none"
                strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <div>
            <div className="brand-title">Organizational Capacity Index</div>
            <div className="brand-sub">Community Safety Fund · assessment MVP</div>
          </div>
        </div>
        <div className="topbar-right">
          {config && (
            <span className={`mode-pill ${config.llm_mode === "mock" ? "mock" : ""}`}
              title={config.model_id ?? "Offline mock - no model is called"}>
              {config.llm_mode === "mock" ? "Offline mock narrative" : "Claude on Amazon Bedrock"}
            </span>
          )}
          {role && (
            <button className="btn ghost small" onClick={signOut}>
              Sign out
            </button>
          )}
        </div>
      </header>

      {step !== "login" && step !== "staff" && (
        <nav className="progress-steps" aria-label="Assessment progress">
          {(["profile", "questionnaire", "processing", "results"] as AppStep[]).map((s, i) => {
            const order = ["profile", "questionnaire", "processing", "results"];
            const state = order.indexOf(step) > i ? "done" : order.indexOf(step) === i ? "current" : "todo";
            const label = { profile: "Organization", questionnaire: "Questionnaire", processing: "Analysis", results: "Results" }[s as string];
            return (
              <div key={s} className={`pstep ${state}`}>
                <span className="pstep-dot">{state === "done" ? "✓" : i + 1}</span>
                <span>{label}</span>
              </div>
            );
          })}
        </nav>
      )}

      <main className="main">
        {step === "login" && (
          <Login
            onLogin={(r) => {
              setRole(r);
              setStep(r === "staff" ? "staff" : "profile");
            }}
          />
        )}
        {step === "profile" && (
          <ProfileForm
            initial={profile}
            onSubmit={(p) => {
              setProfile(p);
              storage.set("oci.profile", p);
              setStep("questionnaire");
            }}
          />
        )}
        {step === "questionnaire" && (
          <Questionnaire
            profile={profile}
            onBack={() => setStep("profile")}
            onSubmit={(answers) => {
              setPending(answers);
              setStep("processing");
            }}
          />
        )}
        {step === "processing" && pending && (
          <Processing
            profile={profile}
            answers={pending}
            onDone={(r) => {
              setResult(r);
              storage.set("oci.lastResult", r.submission_id);
              setStep("results");
            }}
            onError={() => setStep("questionnaire")}
          />
        )}
        {step === "results" && result && <Results result={result} onStartOver={startOver} />}
        {step === "staff" && <StaffAnalytics />}
      </main>

      <footer className="footer">
        Synthetic data only · Scores are computed by the deterministic OCI engine; narrative text is
        AI-generated and should be reviewed with CSF program staff.
      </footer>
    </div>
  );
}
