# Design Document

## Overview

The Everytown OCI platform is delivered as two deployable pieces plus a thin set of AWS resources:

1. **Frontend_App** — a JavaScript/TypeScript single-page application. It owns the mocked login (organization and staff), the organization profile form, the quiz-style questionnaire driven by `questions.json`, the processing indicators, the results page, the PDF download trigger, and the staff aggregate analytics view.
2. **Python_API** — a Python service using boto3. It serves questions, validates completeness, invokes the **unchanged** Scoring_Engine, runs the Bedrock_Orchestrator (two sequential Claude calls), renders the PDF, persists submissions to S3, and computes aggregate analytics.
3. **AWS/Infra** — region `us-west-2`, Amazon Bedrock (Claude) for the model calls, Amazon S3 as the **only** persistent storage (block public access enabled), provisioned via CloudFormation. No Cognito, RDS, load balancer, WAF, KMS, Secrets Manager, or Marketplace offerings.

The central design principle is a hard separation between **deterministic scoring** and **generative narration**. The Scoring_Engine (`engine/scoring.py`) is reused byte-for-byte and is the single source of truth for every capacity score and Priority_Band. The Bedrock_Orchestrator reads those scores and produces prose recommendations; it never computes, alters, or overrides a score. A model failure degrades gracefully to "scores without narration" rather than corrupting results.

This design targets the MVP (local or sandbox hackathon account). Hosted deployment (Fargate + CloudFront) and Knowledge-Base RAG are called out separately in the Stretch Goals section and are not part of the baseline.

Code examples use **Python** for the API and **TypeScript/React** for the front end, matching the languages detected in the workspace (vendored Python reference implementation; a JS/TS front end to be built).

## Architecture

### Component Diagram

```
                           Browser (Org_User / Staff_User)
                                      |
                 +--------------------+--------------------+
                 |             Frontend_App (TS/React)      |
                 |  Login  Profile  Questionnaire  Results  |
                 |  Processing indicators  PDF trigger      |
                 |  Staff aggregate analytics view          |
                 +--------------------+--------------------+
                                      | HTTPS (JSON)
                                      v
      +---------------------------------------------------------------+
      |                        Python_API (boto3)                      |
      |                                                               |
      |  /questions   -> QuestionService (reads questions.json)        |
      |  /submit      -> CompletenessValidator                         |
      |                   -> Scoring_Engine (engine/scoring.py, UNCHANGED)|
      |                   -> Bedrock_Orchestrator                      |
      |                        research call -> recommendation call    |
      |                   -> SubmissionStore (write)                   |
      |  /report/{id} -> PdfRenderer (plain text -> PDF)               |
      |  /analytics   -> AnalyticsService (aggregate over store)       |
      +------------------+----------------------+---------------------+
                         |                      |
                         | boto3 bedrock-runtime| boto3 s3
                         v                      v
             +----------------------+   +--------------------------+
             | Amazon Bedrock Claude |   | Amazon S3 (block public) |
             |  (us-west-2)          |   |  submissions/*.json      |
             +----------------------+   +--------------------------+

   Provisioned by CloudFormation: S3 bucket + IAM role (bedrock:InvokeModel, s3:*Object).
```

### End-to-End Request Flow (Org_User)

```
login -> profile -> questionnaire -> submit -> validate -> score -> research -> recommend -> results -> PDF
```

1. **login** — Org_User submits dummy credentials; Frontend_App checks them against a configured pair and grants access to the profile form. (No Cognito.)
2. **profile** — Org_User enters organization name, website URL, and selects a category (grantee / non-grantee). Front-end validation blocks empty name or empty URL.
3. **questionnaire** — Frontend_App fetches `GET /questions` (scoped to the configured In_Scope_Domains, default PL/FR/FM/ML = 72 statements) and renders a quiz-style Yes/No form.
4. **submit** — Frontend_App POSTs the profile + answers to `POST /submit`.
5. **validate** — CompletenessValidator confirms every in-scope statement has a `yes`/`no` answer. If not, the API returns a completeness error with the missing count and the Scoring_Engine is never called.
6. **score** — The Python_API calls `calculate_recommendations(...)` from the unchanged engine. Scores and Priority_Bands are now fixed.
7. **research** — Bedrock_Orchestrator makes the first Claude call: research the organization from its website URL, producing a short research summary. If the URL is missing/unreachable, it falls back to a neutral "no research available" summary and continues.
8. **recommend** — Bedrock_Orchestrator makes the second Claude call: generate recommendations grounded in the deterministic scores, the research summary, and the in-prompt Resource_Library.
9. **results** — The Python_API persists the full submission record to S3 and returns scores + recommendations; Frontend_App renders the results page.
10. **PDF** — Org_User triggers `GET /report/{id}`; PdfRenderer builds plain text ordered by Priority_Band and renders it to a PDF.

If either Bedrock call fails irrecoverably, the API returns an orchestration error **with the deterministic scores retained**, and the results page shows scores with a notice that narration could not be generated.

### Staff Analytics Path

```
staff login -> analytics view -> GET /analytics?from&to&category -> AnalyticsService reads all submissions from S3 -> aggregate metrics
```

The Staff_User authenticates through the mocked staff path and sees aggregate-only figures (no named-organization comparison). Seeded submissions for the package's sample organizations (A–C) ensure the view is populated on first run.

## Reuse of the Scoring_Engine (unchanged)

`engine/scoring.py`, `engine/recommendations.py`, `utils/data_loader.py`, and `data/questions.json` are **vendored into the Python_API verbatim** from `02_Scoring_Specification/reference_implementation/`. The API imports `calculate_recommendations` and the display formatter rather than reimplementing them. `verify_benchmark.py` is carried along unchanged and wired into CI so that samples A, B, and C must report `PASS` (exit 0) on every build.

```python
# python_api/scoring_adapter.py — thin wrapper, no logic changes
from engine.scoring import calculate_recommendations
from engine.recommendations import format_for_display
from utils.data_loader import get_domains, get_stage_weights, get_stage_names

def score_submission(answers: dict, in_scope_domain_ids: list[str]):
    all_domains = get_domains()
    scoped = [d for d in all_domains if d["id"] in in_scope_domain_ids]
    all_recs, summaries = calculate_recommendations(
        answers, scoped, get_stage_weights(), get_stage_names())
    return all_recs, summaries, format_for_display(all_recs, summaries)
```

Scoping is applied by passing only the in-scope domains into the engine — the engine itself is untouched. `verify_benchmark.py` keeps passing because it imports the same engine and calls it with all 8 domains and the shipped answer/expected pairs; the adapter adds nothing on that path.

### Scoring Gotchas the Design Must Respect

1. **Relative percentile Priority_Bands (thirds).** Bands are assigned by `pct = index / total_gaps` across all gaps in *this* submission (`< 0.33` High, `< 0.66` Medium, else Low). They are **not** absolute. Because the MVP scores only 4 domains instead of 8, the same gap can land in a different band than it would under the full benchmark — this is expected and correct. Only the per-domain `capacity_pct` and `estimated_stage` are stable across scope changes; the UI and PDF therefore present bands as "relative to your submission," never as an absolute severity.
2. **Completeness validation before scoring.** The engine does `answers.get(id, "")`; an unanswered statement matches neither `"yes"` nor `"no"`, so it silently counts as favourable and inflates the score. The CompletenessValidator runs **before** the engine is ever called and rejects any submission missing an in-scope answer.
3. **PL1 is reverse-coded.** `PL1` has `trigger_on: "yes"` — answering Yes is the gap. Every other statement is `trigger_on: "no"`. The design never assumes polarity; the engine reads `trigger_on` per statement, and the front end treats PL1 as an ordinary Yes/No question (polarity lives entirely in scoring).

## Components and Interfaces

### Python_API surface

All request/response bodies are JSON.

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/questions` | Return the in-scope questionnaire (domains, statements, Yes/No options). |
| `POST` | `/submit` | Validate completeness, score, run orchestration, persist, return results. |
| `GET` | `/report/{submission_id}` | Return the Recommendations_Report as a PDF (`application/pdf`). |
| `GET` | `/analytics` | Return aggregate analytics; supports `from`, `to`, `category` filters. |

**`GET /questions` response**

```json
{
  "in_scope_domains": ["PL", "FR", "FM", "ML"],
  "domains": [
    {
      "id": "PL",
      "name": "Planning",
      "questions": [
        { "id": "PL1", "text": "We primarily focus on short-term planning...", "options": ["yes", "no"] }
      ]
    }
  ]
}
```

**`POST /submit` request**

```json
{
  "profile": {
    "org_name": "Southside Youth Peace Collective",
    "website_url": "https://example.org",
    "category": "grantee"
  },
  "answers": { "PL1": "no", "PL2": "no", "FR1": "yes", "...": "..." }
}
```

**`POST /submit` success response**

```json
{
  "submission_id": "2025-05-14T18-30-00Z_southside-youth-peace-collective_ab12cd",
  "scores": {
    "overall_stats": { "total_questions": 72, "total_gaps": 41, "high_priority": 14, "medium_priority": 13, "low_priority": 14 },
    "domains": [
      { "domain_id": "PL", "domain_name": "Planning", "score_pct": 13.3, "estimated_stage": "Seeding", "gap_count": 13, "total_questions": 15, "recommendations": [] }
    ]
  },
  "research_summary": "Short Claude-generated summary of the organization...",
  "recommendations": [
    { "question_id": "PL2", "priority": "High", "domain_id": "PL", "text": "...", "narrative": "Grounded recommendation prose..." }
  ],
  "orchestration_status": "ok"
}
```

**`POST /submit` completeness error (HTTP 422)**

```json
{ "error": "incomplete_submission", "missing_count": 3, "missing_ids": ["FM11", "ML9", "PL14"] }
```

**`POST /submit` orchestration error (HTTP 200 with degraded flag — scores retained)**

```json
{
  "submission_id": "...",
  "scores": { "...": "deterministic scores still present" },
  "research_summary": null,
  "recommendations": [],
  "orchestration_status": "error",
  "orchestration_error": "bedrock_unavailable"
}
```

**`GET /analytics` response**

```json
{
  "filters": { "from": "2025-01-01", "to": "2025-06-01", "category": null },
  "total_submissions": 12,
  "by_category": { "grantee": 7, "non_grantee": 5 },
  "domain_averages": [
    { "domain_id": "PL", "avg_capacity_pct": 24.1, "avg_stage": "Seeding" }
  ],
  "most_common_gaps": [
    { "question_id": "FM4", "domain_id": "FM", "occurrences": 10 }
  ]
}
```

### Bedrock_Orchestrator

A hardcoded, sequential two-call pipeline using the boto3 `bedrock-runtime` client in `us-west-2`. The orchestrator never touches scores.

```python
# python_api/orchestrator.py
import time, random
import boto3
from botocore.exceptions import ClientError

_bedrock = boto3.client("bedrock-runtime", region_name="us-west-2")
MODEL_ID = "anthropic.claude-3-5-sonnet-20240620-v1:0"  # Claude on Bedrock
_MIN_INTERVAL = 1.05  # keep calls under 1 request/second
_last_call = 0.0

def _throttle():
    global _last_call
    wait = _MIN_INTERVAL - (time.monotonic() - _last_call)
    if wait > 0:
        time.sleep(wait)
    _last_call = time.monotonic()

def _invoke(prompt: str, max_retries: int = 5) -> str:
    for attempt in range(max_retries):
        _throttle()
        try:
            resp = _bedrock.converse(
                modelId=MODEL_ID,
                messages=[{"role": "user", "content": [{"text": prompt}]}],
                inferenceConfig={"maxTokens": 2000, "temperature": 0.2},
            )
            return resp["output"]["message"]["content"][0]["text"]
        except ClientError as e:
            code = e.response["Error"]["Code"]
            if code in ("ThrottlingException", "ServiceUnavailableException") and attempt < max_retries - 1:
                backoff = (2 ** attempt) + random.uniform(0, 0.5)  # exponential backoff + jitter
                time.sleep(backoff)
                continue
            raise

def orchestrate(profile, scores):
    # Call 1: research the org from its website URL (graceful fallback).
    try:
        if profile.get("website_url"):
            research = _invoke(_research_prompt(profile))
        else:
            research = None  # no URL -> skip research
    except ClientError:
        research = None  # unreachable / failing research -> continue without it

    # Call 2: resource-grounded recommendations.
    recommendations = _invoke(_recommendation_prompt(profile, scores, research, RESOURCE_LIBRARY))
    return research, recommendations
```

**Throttling and retry.** A process-level minimum interval keeps Bedrock calls under 1 request/second. On `ThrottlingException` / transient errors the orchestrator retries with exponential backoff plus jitter (`2**attempt + random`), up to a bounded number of attempts.

**Two prompts.**

- *Research prompt (call 1):* given the organization name and website URL, produce a concise factual summary of the organization's mission, programs, and context. Explicitly instructed: "If you are uncertain or lack information, say so; do not invent facts."
- *Recommendation prompt (call 2):* given (a) the deterministic domain scores and prioritized gaps, (b) the research summary (or an explicit "no research available" note), and (c) the full **Resource_Library** injected in-prompt, produce actionable recommendations for each gap, ordered by Priority_Band. Grounding/anti-hallucination instructions require every recommendation to be supported by the provided scores or the Resource_Library and to avoid inventing programs, grants, or statistics. The prompt states plainly that the model **must not change, recompute, or contradict** the provided scores.

**In-prompt Resource_Library injection.** The Resource_Library is a curated set of non-confidential CVI reference texts loaded from the repo and concatenated into the recommendation prompt as labeled context blocks. (If the library outgrows the context window, the KB-RAG stretch goal replaces this; the baseline is in-prompt.)

**Graceful fallback & error handling.**
- Missing website URL → research call skipped, `research_summary = null`, recommendations still generated from scores + library.
- Unreachable URL / research call failure → caught, treated as "no research," pipeline continues.
- Recommendation call failure after retries → `orchestration_status = "error"`, `recommendations = []`, **deterministic scores retained and returned**. Scores are computed and captured before any Bedrock call, so no model outcome can lose them.

### Frontend_App structure

React + TypeScript SPA. State is a simple step machine driving routing and the processing indicators.

```
App
├── AuthGate            // mocked org/staff login; holds { role, authed }
├── ProfileForm         // org_name, website_url, category; client-side validation
├── Questionnaire       // fetches /questions, renders Yes/No per statement
│   └── QuestionCard[]  // one Yes/No control per statement
├── ProcessingView      // shows step indicators during /submit
├── ResultsView         // scores + recommendations, PDF download button
└── StaffAnalytics      // aggregate charts/tables; date + category filters
```

**Quiz state flow.**

```
type AppStep =
  | "login" | "profile" | "questionnaire"
  | "processing" | "results" | "staff";

type ProcessingStep = "reading" | "consulting" | "researching" | "done";
```

`Questionnaire` holds `answers: Record<string, "yes" | "no">` and a "submit" that is enabled only when the local count of answered in-scope statements equals the total (a client-side mirror of the server's authoritative completeness check). On submit, the app transitions to `processing` and advances `ProcessingStep` through `reading → consulting → researching` while awaiting the `/submit` response, then transitions to `results` on success (Req 7.2). Because the back end runs the steps as one request, the indicators are time-sequenced on the client to reflect the three phases; the final transition is gated on the real response.

### PDF Report structure

Plain text rendered to PDF (e.g., a minimal text-to-PDF writer; no heavy templating). The report contains, in order:

1. **Header** — organization name, report date, and the list of **domains assessed** (the In_Scope_Domains).
2. **Non-evaluative disclaimer** — a short statement that this is a self-assessment snapshot, that Priority_Bands are relative to this submission, and that the report is informational, not an evaluation or ranking of the organization.
3. **Capacity summary** — per-domain `capacity_pct` and `estimated_stage`.
4. **Recommendations ordered by Priority_Band** — all High first, then Medium, then Low; each entry shows the statement, its domain/stage, and the next steps / generated narrative.

## Data Models

### Submission record (stored in S3)

```python
@dataclass
class SubmissionRecord:
    submission_id: str            # "<ISO8601>_<org-slug>_<rand6>"
    timestamp: str                # ISO 8601 UTC
    profile: dict                 # { org_name, website_url, category }
    category: str                 # "grantee" | "non_grantee"
    in_scope_domains: list[str]   # e.g. ["PL","FR","FM","ML"]
    answers: dict                 # question_id -> "yes" | "no"
    scores: dict                  # format_for_display output (overall_stats + domains)
    gaps: list[dict]              # per gap: question_id, domain_id, stage, priority_score, priority band
    research_summary: str | None
    recommendations: list[dict]   # generated narrative per gap
    orchestration_status: str     # "ok" | "error"
```

`scores`/`gaps` mirror the engine's `format_for_display` and `ScoredRecommendation` shapes so the record is a faithful snapshot of deterministic output. `priority` (band) and `priority_score` come straight from the engine.

### S3 storage and key scheme

Amazon S3 is the only persistent store. One JSON object per submission:

```
s3://<bucket>/submissions/<YYYY>/<MM>/<submission_id>.json
```

- Date-partitioned prefixes make date-range analytics a prefix-scoped `list_objects_v2` rather than a full scan.
- The bucket has **Block Public Access** fully enabled; access is only through the API's IAM role.
- No RDS / database — aggregation reads objects on demand.

### Aggregation for analytics

`AnalyticsService` lists submission objects (optionally narrowed by date prefix), loads each JSON, applies the `category` filter, and computes:

- **Counts:** total submissions; grantee vs non-grantee split.
- **Per-domain averages:** mean `capacity_pct` and the modal/mean `estimated_stage` per domain.
- **Most common gaps:** frequency of each `question_id` appearing as a gap across the filtered set.

Output is **aggregate only** — no named-organization figures and no peer benchmarking between organizations.

### Seeded synthetic data

On deploy/first run, the store is seeded with the three sample organizations from the OCI package (A Southside Youth Peace Collective, B Riverbend Violence Interruption Network, C Metro Community Safety Alliance) so the staff analytics view is populated immediately. (Earlier synthetic variants were removed so the demo uses only the package's sample data.) All seed data is synthetic, contains no PII, and reuses the public benchmark answer sets.

## Security and Data Handling

- **Synthetic data only.** The platform processes only synthetic or scrubbed response data and excludes PII. Seed data is derived from the public benchmark samples.
- **No PII.** Profiles use organization name + public website URL + category; no personal identifiers are collected or stored.
- **S3 Block Public Access.** The submissions bucket blocks all public access; the API reaches it only via its scoped IAM role (least-privilege: `s3:GetObject`/`PutObject`/`ListBucket` on the bucket, `bedrock:InvokeModel` for the model).
- **Sandbox only.** Runs exclusively in the sandbox hackathon AWS account; no access to Everytown's account and no cross-account references in templates.
- **Excluded services.** No Cognito, RDS, load balancer, WAF, KMS, Secrets Manager, or Marketplace. AWS is the only cloud provider; Bedrock Claude is the only model host (no non-AWS model service).
- **Open-source delivery.** Shipped as a forkable repository with CloudFormation templates and free of Everytown-confidential content; only non-confidential reference materials go in the Resource_Library until confirmed.

## Error Handling

| Failure | Handling |
|---|---|
| Incomplete answers | HTTP 422 `incomplete_submission` with `missing_count`/`missing_ids`; engine not invoked. |
| Missing website URL | Research call skipped; `research_summary = null`; recommendations still generated. |
| Research call fails/unreachable | Caught; pipeline continues without research. |
| Recommendation call fails after retries | `orchestration_status = "error"`; recommendations empty; **deterministic scores retained**. |
| Bedrock throttling | Retry with exponential backoff + jitter; calls held under 1 req/sec. |
| S3 write failure | Surfaced as a server error; scores already returned to client are unaffected (write is after scoring). |
| Invalid domain config | Startup validation that every configured in-scope domain id exists in `questions.json`. |

## Testing Strategy

**Dual approach:** example/unit/integration tests for specific behaviors and infrastructure; property-based tests (≥100 iterations each) for universal behaviors. Bedrock is always mocked in automated tests — no live model calls.

- **Benchmark (must stay green):** `verify_benchmark.py` runs in CI against the vendored engine and must report PASS for samples A, B, C (exit 0). The engine is vendored unmodified; a checksum/benchmark guard flags any drift.
- **Completeness validation tests:** property and example tests that incomplete submissions are rejected with the correct missing count and that the engine is never invoked for them.
- **Scoring behavior tests:** property tests for relative percentile bands and PL1 reverse-coding, checked against an independent recomputation of the documented rules.
- **Orchestration tests (mocked Bedrock):** call order (research → recommendation), prompt content (scores + research + Resource_Library present), graceful fallback on missing/failing URL, and score retention on model failure.
- **PDF tests:** generated PDF is valid, contains every recommendation's text, and orders entries by Priority_Band.
- **Analytics tests:** aggregation matches an independent recomputation; date-range and category filters select exactly the matching records; output contains no named-organization comparison.
- **Front-end tests:** login (valid/invalid), profile validation (empty name/URL), questionnaire rendering from `/questions`, processing-indicator sequencing, and results rendering.
- **Infra checks:** CloudFormation validates (cfn-lint); a static scan asserts the templates contain S3 with Block Public Access and none of the excluded resource types (RDS/LB/WAF/KMS/Secrets Manager/Marketplace/Cognito).

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

### Property 1: Invalid credentials are always rejected

*For any* credential pair that is not equal to the configured dummy credentials, the Frontend_App SHALL deny access and display a login failure message.

**Validates: Requirements 1.2**

### Property 2: Profile validation rejects empty required fields

*For any* profile input in which the organization name is empty or whitespace, or the website URL is empty, the Frontend_App SHALL block submission and name the missing field.

**Validates: Requirements 2.2**

### Property 3: Questionnaire matches the configured domains

*For any* configured set of In_Scope_Domains, the statements presented in the questionnaire SHALL equal exactly the union of the statements of those domains in `questions.json`.

**Validates: Requirements 3.1, 3.2**

### Property 4: Completeness is exact

*For any* answer map, the completeness check SHALL pass if and only if every in-scope statement has an answer of "yes" or "no"; and when it fails, the reported missing count SHALL equal the true number of in-scope statements lacking a valid answer.

**Validates: Requirements 4.1, 4.2**

### Property 5: Scoring is withheld until complete

*For any* submission missing at least one in-scope answer, the Scoring_Engine SHALL NOT be invoked.

**Validates: Requirements 4.3**

### Property 6: Scores are a deterministic function of answers, independent of the model

*For any* submission and *for any* Bedrock output (including malformed output or failure), the capacity scores and Priority_Bands returned to the client SHALL equal the Scoring_Engine's output for those answers and SHALL NOT be altered by the Bedrock_Orchestrator.

**Validates: Requirements 5.1, 5.2, 6.5**

### Property 7: Priority_Bands are relative percentile thirds

*For any* submission, each Capacity_Gap's Priority_Band SHALL equal the band obtained by sorting all gaps by score descending and assigning High/Medium/Low at the index/total thresholds (< 0.33, < 0.66, otherwise).

**Validates: Requirements 5.3**

### Property 8: PL1 reverse-coding

*For any* submission, statement PL1 SHALL be counted as a Capacity_Gap if and only if its answer is "yes", opposite to the polarity of a `trigger_on: "no"` statement.

**Validates: Requirements 5.4**

### Property 9: Benchmark fidelity

*For any* of the benchmark answer sets A, B, and C, the Scoring_Engine SHALL produce results matching the corresponding expected results (all three report PASS).

**Validates: Requirements 5.5**

### Property 10: Orchestration call order

*For any* valid submission that reaches orchestration with a usable website URL, the Bedrock_Orchestrator SHALL make exactly the research call followed by the recommendation call, with the research output available to the recommendation call.

**Validates: Requirements 6.2**

### Property 11: Recommendation prompt is grounded

*For any* valid submission, the recommendation call's prompt SHALL contain the deterministic scores, the research summary (or an explicit "no research available" note), and every entry of the Resource_Library.

**Validates: Requirements 6.3, 6.4**

### Property 12: PDF contains all recommendations

*For any* results payload, the generated Recommendations_Report SHALL be a valid PDF whose extracted text contains every recommendation in the payload.

**Validates: Requirements 8.1, 8.3**

### Property 13: Report is ordered by Priority_Band

*For any* results payload, the recommendations in the Recommendations_Report SHALL appear in non-increasing Priority_Band order (all High before any Medium, all Medium before any Low).

**Validates: Requirements 8.4**

### Property 14: Analytics are correct and aggregate-only

*For any* set of stored submissions and any date-range/category filter, the staff analytics output SHALL equal an independent recomputation of the counts, grantee/non-grantee split, per-domain average capacity and stage, and most-common gaps over exactly the records matching the filter, and SHALL contain no named-organization comparison.

**Validates: Requirements 9.1, 9.2**

## Stretch Goals (Optional — Not Part of the Baseline)

These are explicitly out of the MVP scope and should not block or complicate the baseline design.

- **Hosted front end on Fargate + CloudFront.** Package the Python_API as a container behind Amazon ECS Fargate and serve the Frontend_App via Amazon CloudFront for a public, clickable URL. Adds CloudFormation for the cluster, task definition, and distribution — introduced only after the local/sandbox MVP is complete.
- **RAG via Amazon Bedrock Knowledge Base on S3.** If the Resource_Library grows too large for in-prompt injection, replace the in-prompt block with an Amazon Bedrock Knowledge Base backed by the S3 bucket and retrieve the top-k relevant passages for the recommendation call. The orchestrator's two-call shape stays the same; only the library-injection mechanism changes.
- **Tone and vocabulary shaping.** Shape recommendation tone with Everytown's communications guide and public web pages, injected as additional style context in the recommendation prompt.
