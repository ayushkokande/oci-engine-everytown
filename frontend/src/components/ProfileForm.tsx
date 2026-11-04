import { useEffect, useState } from "react";
import { api } from "../api";
import { storage } from "../config";
import type { Category, Profile, SampleOrg } from "../types";

export function validateProfile(p: Profile): Partial<Record<"org_name" | "website_url", string>> {
  const errors: Partial<Record<"org_name" | "website_url", string>> = {};
  if (!p.org_name.trim()) errors.org_name = "Organization name is required.";
  if (!p.website_url.trim()) errors.website_url = "Website URL is required.";
  else if (!/^(https?:\/\/)?[^\s/$.?#].[^\s]*\.[^\s]{2,}/i.test(p.website_url.trim()))
    errors.website_url = "Enter a web address like https://example.org.";
  return errors;
}

export function ProfileForm({ initial, onSubmit }: { initial: Profile; onSubmit: (p: Profile) => void }) {
  const [p, setP] = useState<Profile>(initial);
  const [errors, setErrors] = useState<ReturnType<typeof validateProfile>>({});
  const [touched, setTouched] = useState(false);
  const [samples, setSamples] = useState<SampleOrg[]>([]);
  const [loadingSample, setLoadingSample] = useState<string | null>(null);

  useEffect(() => { api.samples().then(setSamples).catch(() => setSamples([])); }, []);

  const finish = (profile: Profile) => {
    let url = profile.website_url.trim();
    if (!/^https?:\/\//i.test(url)) url = "https://" + url;
    onSubmit({ ...profile, org_name: profile.org_name.trim(), website_url: url });
  };

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validateProfile(p);
    setErrors(errs);
    setTouched(true);
    if (Object.keys(errs).length === 0) {
      // Switching from a sample to your own organization: don't carry the sample's answers over.
      if (initial.sample_id && !p.sample_id) storage.remove("oci.answers");
      finish(p);
    }
  };

  const update = (patch: Partial<Profile>) => {
    const next = { ...p, ...patch };
    // Editing the name or website means it's no longer the package sample.
    if ((patch.org_name !== undefined || patch.website_url !== undefined) && next.sample_id) delete next.sample_id;
    setP(next);
    if (touched) setErrors(validateProfile(next));
  };

  const useSample = async (s: SampleOrg) => {
    setLoadingSample(s.id);
    try {
      const full = await api.sample(s.id);
      storage.set("oci.answers", full.answers);  // the questionnaire opens fully answered
      const profile: Profile = { org_name: s.org_name, website_url: s.website_url, category: s.category, sample_id: s.id };
      setP(profile);
      setErrors({});
      finish(profile);
    } finally {
      setLoadingSample(null);
    }
  };

  return (
    <section className="narrow">
      <p className="eyebrow">Step 1 of 4</p>
      <h1>Tell us about your organization</h1>
      <p className="lede">
        We use your public website to tailor the recommendations to your programs and community.
        Please don't enter personal information about staff or participants.
      </p>

      {samples.length > 0 && (
        <div className="card samples">
          <h2 className="section-title">Choose your organization</h2>
          <div className="sample-grid">
            {samples.map((s) => (
              <button key={s.id} type="button" className={`sample-card ${p.sample_id === s.id ? "selected" : ""}`}
                onClick={() => useSample(s)} disabled={loadingSample !== null}>
                <strong>{s.org_name}</strong>
                <span className="sample-go">{loadingSample === s.id ? "Loading…" : "Select →"}</span>
              </button>
            ))}
          </div>
        </div>
      )}

      <form className="card form" onSubmit={submit} noValidate>
        <h2 className="section-title">Or add a different organization</h2>
        <label className={`field ${errors.org_name ? "invalid" : ""}`}>
          <span>Organization name</span>
          <input value={p.org_name} onChange={(e) => update({ org_name: e.target.value })}
            placeholder="Your organization's name" aria-invalid={!!errors.org_name} />
          {errors.org_name && <small className="field-error" role="alert">{errors.org_name}</small>}
        </label>

        <label className={`field ${errors.website_url ? "invalid" : ""}`}>
          <span>Organization website</span>
          <input value={p.website_url} onChange={(e) => update({ website_url: e.target.value })}
            placeholder="https://example.org" inputMode="url" aria-invalid={!!errors.website_url} />
          {errors.website_url && <small className="field-error" role="alert">{errors.website_url}</small>}
        </label>

        <fieldset className="field">
          <span>Relationship with the Community Safety Fund</span>
          <div className="segmented">
            {([["grantee", "Current or past grantee"], ["non_grantee", "Not a grantee"]] as [Category, string][]).map(
              ([value, label]) => (
                <label key={value} className={`seg ${p.category === value ? "active" : ""}`}>
                  <input type="radio" name="category" value={value} checked={p.category === value}
                    onChange={() => update({ category: value })} />
                  {label}
                </label>
              ))}
          </div>
        </fieldset>

        <div className="form-actions">
          <button className="btn primary" type="submit">Continue to questionnaire →</button>
        </div>
      </form>
    </section>
  );
}
