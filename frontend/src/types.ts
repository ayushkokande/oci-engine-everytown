export type AppStep = "login" | "profile" | "questionnaire" | "processing" | "results" | "staff";
export type ProcessingStep = "reading" | "consulting" | "researching" | "done";
export type Role = "org" | "staff";
export type Answer = "yes" | "no";
export type Band = "High" | "Medium" | "Low";
export type Category = "grantee" | "non_grantee";

export interface Question {
  id: string;
  text: string;
  stage: number;
  options: Answer[];
}

export type ChatRole = "user" | "assistant";

export interface ChatMessage {
  role: ChatRole;
  content: string;
}

export type QuestionChats = Record<string, ChatMessage[]>;

export interface QuestionChatResponse {
  question_id: string;
  reply: string;
}

export interface Domain {
  id: string;
  name: string;
  questions: Question[];
}

export interface QuestionsPayload {
  in_scope_domains: string[];
  domains: Domain[];
}

export interface Profile {
  org_name: string;
  website_url: string;
  category: Category;
}

export interface DomainScore {
  domain_id: string;
  domain_name: string;
  score_pct: number;
  estimated_stage: string;
  gap_count: number;
  total_questions: number;
}

export interface OverallStats {
  total_questions: number;
  total_gaps: number;
  high_priority: number;
  medium_priority: number;
  low_priority: number;
}

export interface Gap {
  question_id: string;
  domain_id: string;
  domain_name: string;
  stage_name: string;
  text: string;
  next_steps: string[];
  priority_score: number;
  priority: Band;
}

export interface Recommendation extends Gap {
  narrative: string | null;
  resource_ids: string[];
}

export interface ActionPhase {
  timeframe: string;
  actions: { text: string; question_ids: string[] }[];
}

export interface StageCell {
  stage: number;
  name: string;
  total: number;
  in_place: number;
  gap_ids: string[];
}

/** Computed by the API from the engine's gaps; identical on results, PDF and staff views. */
export interface StageProfile {
  domain_id: string;
  domain_name: string;
  estimated_stage: string;
  stage_number: number;
  score_pct: number;
  stages: StageCell[];
  next_stage: string | null;
  blocking_gap_ids: string[];
  in_place_beyond_stage: number;
  summary: string;
}

export interface NetworkStageCell {
  stage: number;
  name: string;
  avg_in_place_pct: number;
}

export interface ContextEntry {
  text: string;
  timestamp: string;
}

export type RevisionStatus = "none" | "pending" | "ok" | "error";

export interface SubmissionResult {
  submission_id: string;
  timestamp: string;
  profile: Profile;
  in_scope_domains: string[];
  scores: { overall_stats: OverallStats; domains: DomainScore[] };
  gaps: Gap[];
  research_summary: string | null;
  overview: string | null;
  action_plan: ActionPhase[];
  recommendations: Recommendation[];
  orchestration_status: "ok" | "error" | "seed" | "pending";
  orchestration_error: string | null;
  persisted?: boolean;
  stage_profile: StageProfile[];
  stage_rule: string;
  domain_analysis?: Record<string, string>;
  org_context?: ContextEntry[];
  revision_status?: RevisionStatus;
  revision_error?: string | null;
  revision_count?: number;
}

export interface AssessmentChatResponse {
  submission_id: string;
  reply: string;
}

export type InsightKind = "stage" | "relative" | "common_gap" | "distinctive_gap" | "context";

export interface Insight {
  kind: InsightKind;
  domain_id: string | null;
  title: string;
  detail: string;
  question_ids: string[];
}

export interface StaffAssessmentRow {
  submission_id: string;
  timestamp: string;
  org_name: string;
  category: Category;
  synthetic: boolean;
  orchestration_status: SubmissionResult["orchestration_status"];
  overall_stats: OverallStats;
  domains: Pick<DomainScore, "domain_id" | "domain_name" | "score_pct" | "estimated_stage">[];
  context_count: number;
  revision_count: number;
}

export interface StaffAssessmentDetail extends SubmissionResult {
  insights: Insight[];
  network: {
    assessments: number;
    avg_capacity_pct: Record<string, number>;
    stage_counts: Record<string, Record<string, number>>;
    stage_profile: Record<string, NetworkStageCell[]>;
    gap_share_pct: Record<string, number>;
  };
}

export interface IncompleteError {
  error: "incomplete_submission";
  missing_count: number;
  missing_ids: string[];
}

export interface ResourceInfo {
  id: string;
  title: string;
  domains: string[];
  source: string;
}

export interface ApiConfig {
  in_scope_domains: string[];
  llm_mode: string;
  model_id: string | null;
  store: string;
  region: string;
  resource_count: number;
}

export interface Analytics {
  filters: { from: string | null; to: string | null; category: string | null };
  total_submissions: number;
  by_category: { grantee: number; non_grantee: number };
  domain_averages: {
    domain_id: string;
    domain_name: string;
    avg_capacity_pct: number;
    avg_stage: string;
    mean_stage_number: number;
    stage_distribution: Record<string, number>;
    stage_profile: NetworkStageCell[];
    submissions: number;
  }[];
  stage_rule: string;
  most_common_gaps: {
    question_id: string;
    domain_id: string;
    domain_name: string;
    text: string;
    occurrences: number;
    share_pct: number;
  }[];
}

export const STAGES = ["Seeding", "Emerging", "Developing", "Strengthening", "Transformational"];
