import type {
  Analytics, Answer, ApiConfig, IncompleteError, Profile, QuestionsPayload, ResourceInfo, SubmissionResult,
} from "./types";

const BASE = "/api";

export class ApiError extends Error {
  constructor(public status: number, message: string, public body?: unknown) {
    super(message);
  }
}

async function getJson<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path);
  if (!res.ok) throw new ApiError(res.status, `GET ${path} failed (${res.status})`);
  return res.json() as Promise<T>;
}

export const api = {
  config: () => getJson<ApiConfig>("/config"),
  questions: () => getJson<QuestionsPayload>("/questions"),
  resources: () => getJson<{ resources: ResourceInfo[] }>("/resources").then((r) => r.resources),
  sample: (id: string) =>
    getJson<{ sample: string; org_name: string; category: string; answers: Record<string, Answer> }>(`/samples/${id}`),
  submission: (id: string) => getJson<SubmissionResult>(`/submissions/${encodeURIComponent(id)}`),
  analytics: (params: { from?: string; to?: string; category?: string }) => {
    const q = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => v && q.set(k, v));
    return getJson<Analytics>(`/analytics${q.toString() ? "?" + q : ""}`);
  },
  reportUrl: (id: string) => `${BASE}/report/${encodeURIComponent(id)}`,

  async submit(profile: Profile, answers: Record<string, Answer>): Promise<SubmissionResult> {
    const res = await fetch(BASE + "/submit", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ profile, answers }),
    });
    const body = await res.json().catch(() => null);
    if (res.status === 422 && body && (body as IncompleteError).error === "incomplete_submission") {
      const b = body as IncompleteError;
      throw new ApiError(422, `${b.missing_count} statement(s) still need an answer.`, b);
    }
    if (!res.ok) throw new ApiError(res.status, `Submission failed (${res.status})`, body);
    return body as SubmissionResult;
  },
};
