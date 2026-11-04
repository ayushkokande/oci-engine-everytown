import type {
  Analytics, Answer, ApiConfig, AssessmentChatResponse, ChatMessage, IncompleteError, Profile,
  QuestionChatResponse, QuestionsPayload, ResourceInfo, StaffAssessmentDetail, StaffAssessmentRow,
  SubmissionResult,
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

function detailOf(body: unknown): string {
  return body && typeof (body as { detail?: unknown }).detail === "string" ? (body as { detail: string }).detail : "";
}

async function postJson<T>(path: string, payload: unknown, unreachable: string): Promise<{ status: number; body: T }> {
  let res: Response;
  try {
    res = await fetch(BASE + path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
  } catch {
    throw new ApiError(0, unreachable);
  }
  const body: unknown = await res.json().catch(() => null);
  if (!res.ok) {
    throw new ApiError(res.status, detailOf(body) || `The request failed (HTTP ${res.status}). Please try again.`, body);
  }
  return { status: res.status, body: body as T };
}

function query(params: Record<string, string | undefined>): string {
  const q = new URLSearchParams();
  Object.entries(params).forEach(([k, v]) => v && q.set(k, v));
  return q.toString() ? "?" + q : "";
}

const CHAT_UNREACHABLE = "Couldn't reach the assistant. Check that the API is running, then try again.";

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
  analytics: (params: { from?: string; to?: string; category?: string }) =>
    getJson<Analytics>(`/analytics${query(params)}`),
  /** inline=true opens the PDF in the browser; otherwise it downloads. */
  reportUrl: (id: string, inline = false) => `${BASE}/report/${encodeURIComponent(id)}${inline ? "?inline=true" : ""}`,

  feedbackChat: (id: string, messages: ChatMessage[]) =>
    postJson<AssessmentChatResponse>(`/submissions/${encodeURIComponent(id)}/feedback-chat`, { messages },
      CHAT_UNREACHABLE).then((r) => r.body.reply),
  /** Regenerate the narrative with added context. Status 202 means it is running in the background. */
  revise: (id: string, context: string) =>
    postJson<SubmissionResult>(`/submissions/${encodeURIComponent(id)}/revise`, { context },
      "Couldn't reach the assessment server. Your context is still in the chat; try again."),

  staffAssessments: (params: { from?: string; to?: string; category?: string }) =>
    getJson<{ assessments: StaffAssessmentRow[] }>(`/staff/assessments${query(params)}`).then((r) => r.assessments),
  staffAssessment: (id: string) => getJson<StaffAssessmentDetail>(`/staff/assessments/${encodeURIComponent(id)}`),
  staffChat: (id: string, messages: ChatMessage[]) =>
    postJson<AssessmentChatResponse>(`/staff/assessments/${encodeURIComponent(id)}/chat`, { messages },
      CHAT_UNREACHABLE).then((r) => r.body.reply),

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
