import type {
  Analytics, Answer, ApiConfig, ChatMessage, IncompleteError, Profile, QuestionChatResponse,
  QuestionsPayload, ResourceInfo, SubmissionResult,
} from "./types";

// Relative on purpose: works at the site root and behind path-prefix proxies
// such as code-server's /proxy/8000/ in the hackathon workshop IDE.
const BASE = "api";

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
  async questionChat(questionId: string, messages: ChatMessage[]): Promise<QuestionChatResponse> {
    let res: Response;
    try {
      res = await fetch(`${BASE}/questions/${encodeURIComponent(questionId)}/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ messages }),
      });
    } catch {
      throw new ApiError(0, "Couldn't reach the explanation service. Check that the API is running, then try again.");
    }
    const body: unknown = await res.json().catch(() => null);
    if (!res.ok) {
      throw new ApiError(res.status, `The explanation service could not respond (HTTP ${res.status}). Please try again.`, body);
    }
    if (!body || typeof body !== "object" || typeof (body as QuestionChatResponse).reply !== "string") {
      throw new ApiError(502, "The explanation service returned an invalid response. Please try again.", body);
    }
    return body as QuestionChatResponse;
  },
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
    let res: Response;
    try {
      res = await fetch(BASE + "/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile, answers }),
      });
    } catch {
      // No HTTP response at all: the API process is stopped, restarting, or unreachable.
      throw new ApiError(0, "Couldn't reach the assessment server. Check that it's running " +
        "(make demo or make dev-api), then try again. Your answers are saved.");
    }
    const body = await res.json().catch(() => null);
    if (res.status === 422 && body && (body as IncompleteError).error === "incomplete_submission") {
      const b = body as IncompleteError;
      throw new ApiError(422, `${b.missing_count} statement(s) still need an answer.`, b);
    }
    if (!res.ok) {
      const detail = body && typeof (body as { detail?: unknown }).detail === "string"
        ? `: ${(body as { detail: string }).detail}` : "";
      throw new ApiError(res.status, `The server couldn't process this submission (HTTP ${res.status}${detail}). ` +
        "Your answers are saved; try again, and check the server terminal if it keeps happening.", body);
    }
    return body as SubmissionResult;
  },
};
