# Implementation Plan: Everytown OCI Assessment

## Overview

This plan builds the OCI platform in dependency order so the deterministic scoring path lands first and `verify_benchmark.py` stays green from the start. We scaffold the repo and vendor the existing engine verbatim, then expose the scoring path (questions, completeness, scoped scoring), then add S3 persistence, then layer the Bedrock orchestration (always mocked in tests), then PDF generation, then the React/TypeScript front end, then staff aggregate analytics, then CloudFormation, and finally end-to-end wiring. Bedrock is never called live in automated tests. Each task builds on the prior ones and wires into the running system; there is no orphaned code.

The implementation languages are fixed by the design: **Python** (boto3) for the API and **TypeScript/React** for the front end. The Scoring_Engine is reused byte-for-byte and never modified.

## Tasks

- [ ] 1. Scaffold repository, vendor the engine, and wire the benchmark test command
  - [ ] 1.1 Create repo structure and vendor the Scoring_Engine unchanged
    - Create `python_api/`, `frontend/`, `infra/`, and `tests/` directories at the repo root
    - Copy `engine/scoring.py`, `engine/recommendations.py`, `engine/__init__.py`, `utils/data_loader.py`, `utils/__init__.py`, `data/questions.json`, and `verify_benchmark.py` from `02_Scoring_Specification/reference_implementation/` into `python_api/` **byte-for-byte with no logic changes**
    - Copy the benchmark answer/expected pairs (`sample_A/B/C_answers.json`, `sample_A/B/C_expected.json`) into the repo so the benchmark runs offline
    - Add a checksum/benchmark-guard note so engine drift is detectable
    - _Requirements: 5.1, 5.5, 10.5_
  - [ ] 1.2 Scaffold the Python_API skeleton with config-driven In_Scope_Domains
    - Set up the API package (framework entry point, dependency manifest with boto3, app config)
    - Load `In_Scope_Domains` from configuration defaulting to `["PL","FR","FM","ML"]` (no code change to switch domains)
    - Add startup validation that every configured in-scope domain id exists in `questions.json`
    - _Requirements: 3.2, 10.6_
  - [ ] 1.3 Scaffold the Frontend_App skeleton (React + TypeScript SPA)
    - Set up the TS/React project with the `AppStep` step-machine (`login | profile | questionnaire | processing | results | staff`) and an API client module
    - Add placeholder route components for AuthGate, ProfileForm, Questionnaire, ProcessingView, ResultsView, StaffAnalytics
    - _Requirements: 2.1, 3.1_
  - [ ] 1.4 Wire `verify_benchmark.py` into a test command
    - Add a test/CI command that runs `verify_benchmark.py` against the vendored engine for samples A, B, C and fails the build on any non-PASS (non-zero exit)
    - _Requirements: 5.5_

- [ ] 2. Implement the deterministic scoring path
  - [ ] 2.1 Implement the question-serving endpoint
    - Implement `GET /questions` returning only the In_Scope_Domains with their statements and Yes/No options, shaped per the design
    - _Requirements: 3.1, 3.2_
  - [ ]* 2.2 Write property test for questionnaire scope
    - **Property 3: Questionnaire matches the configured domains**
    - **Validates: Requirements 3.1, 3.2**
  - [ ] 2.3 Implement the CompletenessValidator
    - Validate that every in-scope statement has a `yes`/`no` answer; on failure return HTTP 422 `incomplete_submission` with `missing_count` and `missing_ids`, and never invoke the engine
    - _Requirements: 4.1, 4.2, 4.3_
  - [ ]* 2.4 Write property tests for completeness and score-withholding
    - **Property 4: Completeness is exact** — pass iff all in-scope statements answered; missing count is exact
    - **Property 5: Scoring is withheld until complete** — engine not invoked when any in-scope answer missing
    - **Validates: Requirements 4.1, 4.2, 4.3**
  - [ ] 2.5 Implement the scoring adapter (thin wrapper, no engine logic)
    - Implement `scoring_adapter.score_submission(answers, in_scope_domain_ids)` that scopes to the configured domains by filtering `get_domains()` and calls `calculate_recommendations(...)` plus `format_for_display(...)` from the unchanged engine
    - _Requirements: 5.1, 5.3, 5.4_
  - [ ]* 2.6 Write property tests for scoring behavior
    - **Property 7: Priority_Bands are relative percentile thirds** (sort gaps desc; `<0.33` High, `<0.66` Medium, else Low)
    - **Property 8: PL1 reverse-coding** (gap iff answer is "yes")
    - **Validates: Requirements 5.3, 5.4**
  - [ ]* 2.7 Confirm benchmark fidelity through the adapter path
    - Add a test asserting the adapter path leaves the engine's benchmark output unchanged and A/B/C still PASS
    - **Property 9: Benchmark fidelity**
    - **Validates: Requirements 5.5**
  - [ ] 2.8 Wire `POST /submit` scoring-only flow
    - Wire `/submit` to run CompletenessValidator → scoring adapter and return scores (orchestration/persistence added in later tasks); capture scores before any later side effects
    - _Requirements: 3.4, 4.1, 5.1_

- [ ] 3. Checkpoint - deterministic path green
  - Ensure all tests pass and `verify_benchmark.py` reports PASS for A, B, C; ask the user if questions arise.

- [ ] 4. Implement S3 submission persistence
  - [ ] 4.1 Implement the SubmissionStore and SubmissionRecord
    - Define the `SubmissionRecord` dataclass and write one JSON object per submission to S3 using date-partitioned keys `submissions/<YYYY>/<MM>/<submission_id>.json` via boto3
    - Generate `submission_id` as `<ISO8601>_<org-slug>_<rand6>`; surface S3 write failures as a server error without affecting already-computed scores
    - _Requirements: 10.2, 10.4_
  - [ ]* 4.2 Write unit tests for persistence (S3 mocked)
    - Test key scheme, date partitioning, record shape, and that a write failure does not corrupt returned scores
    - _Requirements: 10.2, 10.4_
  - [ ] 4.3 Wire persistence into `POST /submit`
    - Persist the full submission record after scoring (and after orchestration once added), returning scores regardless of write timing
    - _Requirements: 10.2, 10.4_

- [ ] 5. Implement the Bedrock_Orchestrator (Bedrock mocked in tests)
  - [ ] 5.1 Implement the boto3 Claude client with throttle and retry/backoff
    - Create the `bedrock-runtime` client in `us-west-2`; enforce a process-level minimum interval keeping calls under 1 req/sec; retry transient/throttling errors with exponential backoff + jitter up to a bounded count
    - _Requirements: 6.1_
  - [ ] 5.2 Implement the research call with graceful fallback
    - Build the research prompt from org name + website URL with explicit "do not invent facts" grounding; skip when URL missing (`research_summary = null`); on unreachable/failing call, catch and continue without research
    - _Requirements: 6.2_
  - [ ] 5.3 Implement the resource-grounded recommendation call
    - Load the non-confidential Resource_Library from the repo and inject every entry in-prompt as labeled context; build the recommendation prompt from deterministic scores + research summary (or explicit "no research available") + library; include anti-hallucination grounding and an explicit "must not change/recompute/contradict scores" instruction
    - _Requirements: 6.3, 6.4, 6.6, 10.5_
  - [ ] 5.4 Implement orchestration error handling that preserves scores
    - On recommendation-call failure after retries, set `orchestration_status = "error"`, `recommendations = []`, and return the already-computed deterministic scores (HTTP 200 degraded)
    - _Requirements: 6.5_
  - [ ]* 5.5 Write property/unit tests for orchestration (Bedrock mocked)
    - **Property 6: Scores are a deterministic function of answers, independent of the model** (any/malformed/failed Bedrock output leaves scores unchanged)
    - **Property 10: Orchestration call order** (research then recommendation; research available to recommendation call)
    - **Property 11: Recommendation prompt is grounded** (prompt contains scores, research-or-note, and every Resource_Library entry)
    - Example tests: missing-URL skip, unreachable-URL fallback, throttle-retry path
    - **Validates: Requirements 5.1, 5.2, 6.2, 6.3, 6.4, 6.5**
  - [ ] 5.6 Wire orchestration into `POST /submit`
    - Insert research → recommendation between scoring and persistence; always return deterministic scores; include `orchestration_status`/`orchestration_error` in the response
    - _Requirements: 6.2, 6.5_

- [ ] 6. Implement PDF report generation
  - [ ] 6.1 Implement the PdfRenderer and `GET /report/{submission_id}`
    - Render plain text to a PDF (`application/pdf`) containing: header (org name, report date, domains assessed), non-evaluative/relative-band disclaimer, per-domain capacity_pct + estimated_stage, and recommendations ordered by Priority_Band (all High, then Medium, then Low)
    - Load the submission record from the SubmissionStore by id
    - _Requirements: 8.3, 8.4_
  - [ ]* 6.2 Write property tests for the PDF
    - **Property 12: PDF contains all recommendations** (valid PDF; extracted text contains every recommendation)
    - **Property 13: Report is ordered by Priority_Band** (non-increasing band order)
    - **Validates: Requirements 8.1, 8.3, 8.4**

- [ ] 7. Implement the Frontend_App flows
  - [ ] 7.1 Implement mocked org and staff login (AuthGate)
    - Check credentials against a configured dummy pair; grant org users the profile form and staff users the analytics view; on mismatch deny access and show a login failure message; no Cognito
    - _Requirements: 1.1, 1.2, 1.3, 1.4_
  - [ ]* 7.2 Write property/unit tests for login
    - **Property 1: Invalid credentials are always rejected**
    - Example tests: valid org login, valid staff login routes to analytics
    - **Validates: Requirements 1.1, 1.2, 1.3**
  - [ ] 7.3 Implement the organization profile form with validation
    - Present org name, website URL, and category (grantee / non-grantee); block submission and name the missing field when org name is empty/whitespace or URL is empty; advance to questionnaire on valid input
    - _Requirements: 2.1, 2.2, 2.3_
  - [ ]* 7.4 Write property test for profile validation
    - **Property 2: Profile validation rejects empty required fields**
    - **Validates: Requirements 2.2**
  - [ ] 7.5 Implement the quiz-style questionnaire from `/questions`
    - Fetch `GET /questions` and render one Yes/No control per in-scope statement (PL1 treated as an ordinary Yes/No question); enable submit only when all in-scope statements are answered; POST profile + answers to `POST /submit`
    - _Requirements: 3.1, 3.3, 3.4_
  - [ ]* 7.6 Write unit tests for questionnaire rendering
    - Statements rendered equal the `/questions` payload; submit gated on full completeness
    - _Requirements: 3.1, 3.3_
  - [ ] 7.7 Implement processing indicators and results page
    - During `/submit`, show processing indicators sequencing reading → consulting → researching; advance to results on success; render capacity scores and recommendations, and show a notice when `orchestration_status = "error"`
    - _Requirements: 7.1, 7.2, 8.1_
  - [ ] 7.8 Implement the PDF download trigger
    - Add a control on the results page that triggers `GET /report/{submission_id}` and downloads the PDF
    - _Requirements: 8.2_
  - [ ]* 7.9 Write unit tests for processing/results rendering
    - Processing-indicator sequencing; results render scores + recommendations; degraded-orchestration notice shown
    - _Requirements: 7.1, 7.2, 8.1_

- [ ] 8. Checkpoint - end-user flow working
  - Ensure all tests pass and the org journey (login → profile → questionnaire → processing → results → PDF) works against the API with Bedrock mocked; ask the user if questions arise.

- [ ] 9. Implement staff aggregate analytics
  - [ ] 9.1 Implement the AnalyticsService and `GET /analytics`
    - List submission objects (narrowed by date prefix when possible), load each JSON, apply `from`/`to`/`category` filters, and compute total submissions, grantee vs non-grantee split, per-domain average capacity_pct and average/modal stage, and most-common gaps; output aggregate-only with no named-organization comparison
    - _Requirements: 9.1, 9.2_
  - [ ] 9.2 Implement seeded synthetic submissions
    - On deploy/first run, seed the store with benchmark submissions A, B, C plus a few variants (higher-capacity, mixed-category); all synthetic, no PII
    - _Requirements: 9.1, 10.2_
  - [ ]* 9.3 Write property test for analytics
    - **Property 14: Analytics are correct and aggregate-only** (counts, split, per-domain averages, most-common gaps match independent recomputation over exactly the filtered records; no named-org comparison)
    - **Validates: Requirements 9.1, 9.2**
  - [ ] 9.4 Implement the StaffAnalytics front-end view
    - Render aggregate figures with date-range + category filters behind the mocked staff login; present aggregate-only (no peer benchmarking between named organizations)
    - _Requirements: 9.1, 9.2_

- [ ] 10. Author CloudFormation templates for AWS resources
  - [ ] 10.1 Write the S3 + IAM CloudFormation template
    - Define the submissions S3 bucket with Block Public Access fully enabled and a least-privilege IAM role (`s3:GetObject`/`PutObject`/`ListBucket` on the bucket, `bedrock:InvokeModel`); sandbox-only, no cross-account references; exclude RDS, load balancers, WAF, KMS, Secrets Manager, Marketplace, and Cognito
    - _Requirements: 10.1, 10.3, 10.4, 10.6_
  - [ ]* 10.2 Write infra validation checks
    - cfn-lint validation plus a static scan asserting S3 Block Public Access is present and none of the excluded resource types (RDS/LB/WAF/KMS/Secrets Manager/Marketplace/Cognito) appear
    - _Requirements: 10.3, 10.4_

- [ ] 11. End-to-end wiring and demo-readiness
  - [ ] 11.1 Wire the full org and staff paths end to end
    - Connect front end to all API endpoints (`/questions`, `/submit`, `/report/{id}`, `/analytics`); ensure no orphaned modules and that config-driven domain scope flows through every layer
    - _Requirements: 3.4, 6.2, 8.1, 9.1_
  - [ ]* 11.2 Write integration tests for both paths (Bedrock + S3 mocked)
    - Org path: complete → score → orchestrate → persist → results → PDF, including the degraded (orchestration error) path with scores retained
    - Staff path: seeded data → `/analytics` with filters → aggregate-only output
    - _Requirements: 4.3, 5.1, 6.5, 8.4, 9.2_

- [ ] 12. Final checkpoint - full build green
  - Ensure all tests pass, `verify_benchmark.py` reports PASS for A, B, C, and CloudFormation validates; ask the user if questions arise.

- [ ]* 13. Stretch goals (optional — not part of the baseline)
  - [ ]* 13.1 Host the front end on Fargate + CloudFront
    - Package the Python_API as a container behind ECS Fargate and serve the SPA via CloudFront; add the corresponding CloudFormation
    - _Requirements: Stretch Goals_
  - [ ]* 13.2 Replace in-prompt Resource_Library with Bedrock Knowledge Base RAG on S3
    - Back a Bedrock Knowledge Base with the S3 bucket and retrieve top-k passages for the recommendation call; keep the two-call orchestrator shape unchanged
    - _Requirements: Stretch Goals_
  - [ ]* 13.3 Add tone and vocabulary shaping
    - Inject Everytown's communications guide/public web style context into the recommendation prompt
    - _Requirements: Stretch Goals_
  - [ ]* 13.4 Add save/resume for in-progress questionnaires
    - Persist partial answers so an Org_User can resume an incomplete assessment
    - _Requirements: Stretch Goals_

## Notes

- Tasks marked with `*` are optional (tests and stretch goals) and can be skipped for a faster MVP; core implementation tasks are never optional.
- Each task references the specific requirement sub-clauses it satisfies for traceability.
- Property tests reference the numbered Correctness Properties from the design and should run ≥100 iterations each.
- Bedrock is always mocked in automated tests — no live model calls. S3 is mocked in unit/integration tests.
- Checkpoints ensure incremental validation; `verify_benchmark.py` must stay green (PASS for A, B, C) throughout.
- The Scoring_Engine is vendored unchanged; the adapter adds scoping only by selecting in-scope domains.

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.3"] },
    { "id": 1, "tasks": ["1.2", "1.4", "7.1"] },
    { "id": 2, "tasks": ["2.1", "2.3", "2.5", "7.2", "7.3"] },
    { "id": 3, "tasks": ["2.2", "2.4", "2.6", "2.7", "2.8", "4.1", "7.4", "7.5"] },
    { "id": 4, "tasks": ["4.2", "4.3", "5.1", "7.6", "9.2"] },
    { "id": 5, "tasks": ["5.2", "5.3", "5.4"] },
    { "id": 6, "tasks": ["5.5", "5.6", "6.1"] },
    { "id": 7, "tasks": ["6.2", "7.7", "9.1"] },
    { "id": 8, "tasks": ["7.8", "7.9", "9.3", "9.4", "10.1"] },
    { "id": 9, "tasks": ["10.2", "11.1"] },
    { "id": 10, "tasks": ["11.2"] },
    { "id": 11, "tasks": ["13.1", "13.2", "13.3", "13.4"] }
  ]
}
```
