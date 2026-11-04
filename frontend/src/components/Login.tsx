import { useState } from "react";
import { checkCredentials, DEMO_CREDENTIALS } from "../config";
import type { Role } from "../types";

export function Login({ onLogin }: { onLogin: (role: Role) => void }) {
  const [role, setRole] = useState<Role>("org");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    if (checkCredentials(role, user, password)) {
      setError(null);
      onLogin(role);
    } else {
      setError("Those credentials don't match. Check the demo credentials below and try again.");
    }
  };

  const creds = DEMO_CREDENTIALS[role];

  return (
    <section className="login-wrap">
      <div className="login-intro">
        <p className="eyebrow">Self-assessment</p>
        <h1>See where your organization is strong, and where to build next.</h1>
        <p className="lede">
          Answer a short set of yes/no statements about planning, fundraising, financial management
          and learning. You'll get your capacity scores and a personalized, prioritized set of
          recommendations you can start on in the coming weeks, plus a PDF to share with your team.
        </p>
        <ul className="intro-points">
          <li><strong>About 15 minutes.</strong> 72 statements across 4 areas.</li>
          <li><strong>Not a grade.</strong> It's a snapshot to help you plan.</li>
          <li><strong>Your answers drive the scores.</strong> AI writes the guidance, never the numbers.</li>
        </ul>
      </div>

      <form className="card login-card" onSubmit={submit} noValidate>
        <div className="tabs" role="tablist" aria-label="Sign in as">
          {(["org", "staff"] as Role[]).map((r) => (
            <button key={r} type="button" role="tab" aria-selected={role === r}
              className={`tab ${role === r ? "active" : ""}`}
              onClick={() => { setRole(r); setError(null); }}>
              {r === "org" ? "Organization" : "CSF staff"}
            </button>
          ))}
        </div>

        <label className="field">
          <span>Username</span>
          <input value={user} onChange={(e) => setUser(e.target.value)} autoComplete="off" name="username" />
        </label>
        <label className="field">
          <span>Password</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)}
            autoComplete="off" name="password" />
        </label>

        {error && <div className="alert error" role="alert">{error}</div>}

        <button className="btn primary block" type="submit">
          {role === "org" ? "Start assessment" : "Open staff analytics"}
        </button>

        <div className="demo-creds">
          <span>Demo credentials</span>
          <code>{creds.user}</code> / <code>{creds.password}</code>
          <button type="button" className="linklike" onClick={() => { setUser(creds.user); setPassword(creds.password); }}>
            Fill in
          </button>
        </div>
      </form>
    </section>
  );
}
