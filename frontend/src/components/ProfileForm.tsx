import { useState } from "react";
import type { Category, Profile } from "../types";

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

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const errs = validateProfile(p);
    setErrors(errs);
    setTouched(true);
    if (Object.keys(errs).length === 0) {
      let url = p.website_url.trim();
      if (!/^https?:\/\//i.test(url)) url = "https://" + url;
      onSubmit({ ...p, org_name: p.org_name.trim(), website_url: url });
    }
  };

  const update = (patch: Partial<Profile>) => {
    const next = { ...p, ...patch };
    setP(next);
    if (touched) setErrors(validateProfile(next));
  };

  return (
    <section className="narrow">
      <p className="eyebrow">Step 1 of 4</p>
      <h1>Tell us about your organization</h1>
      <p className="lede">
        We use your public website to tailor the recommendations to your programs and community.
        Please don't enter personal information about staff or participants.
      </p>

      <form className="card form" onSubmit={submit} noValidate>
        <label className={`field ${errors.org_name ? "invalid" : ""}`}>
          <span>Organization name</span>
          <input value={p.org_name} onChange={(e) => update({ org_name: e.target.value })}
            placeholder="e.g. Southside Youth Peace Collective" aria-invalid={!!errors.org_name} />
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
