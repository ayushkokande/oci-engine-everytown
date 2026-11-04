# Everytown OCI Assessment — MVP

A CVI organization logs in, describes itself, answers a quiz-style questionnaire (Planning,
Fundraising, Financial Management, and Monitoring, Learning & Evaluation — 72 statements),
and gets its capacity scores plus personalized, prioritized recommendations and a detailed PDF report.
It can then chat about its feedback and add context (team size, what it already does) to regenerate
the recommendations; scores never change. CSF staff get network aggregates plus a staff-only view of
each assessment with code-computed insights linked to the organization's feedback, and a chat about it.

Built from the Kiro spec in [`.kiro/specs/everytown-oci-assessment/`](.kiro/specs/everytown-oci-assessment/).

```
frontend/      React + TypeScript SPA (login, profile, questionnaire, processing, results, staff analytics)
python_api/    FastAPI + boto3: questions, completeness check, scoring, Bedrock pipeline, PDF, analytics
  engine/ utils/ data/ verify_benchmark.py   <- vendored byte-for-byte from the reference implementation
  resource_library/                          <- non-confidential resources injected into the prompt
infra/         CloudFormation: private S3 bucket + least-privilege IAM role (us-west-2)
tests/         pytest + hypothesis (Bedrock and S3 always mocked)
```

## The one rule

**Code computes every score; the model only writes narrative.** The scoring engine is vendored
unchanged (checksums in `python_api/ENGINE_CHECKSUMS.sha256`, checked by a test) and runs before any
model call. If Bedrock fails or returns junk, the API still returns the exact engine scores with
`orchestration_status: "error"`, and the UI and PDF fall back to the questionnaire's own next steps.

## Quick start

Requires Python 3.10+ and Node 20+.

```bash
make install          # pip install -r requirements-dev.txt && npm install
make demo             # builds the SPA, serves everything on http://localhost:8000 with OFFLINE MOCK narrative
```

Log in with **demo / demo123** (organization) or **staff / staff123** (staff). On the organization step,
pick one of the package's sample organizations to load its profile and all 72 answers in one click:

| Sample | Organization | Profile |
|---|---|---|
| A | Southside Youth Peace Collective | Grassroots, founded 2023 · 4 staff · ~$310K |
| B | Riverbend Violence Interruption Network | Mid-size, founded 2016 · 19 staff · ~$2.1M |
| C | Metro Community Safety Alliance | Mature, founded 2009 · 48 staff · ~$7.4M |

These are the synthetic samples from `Everytown/Everytown_OCI_Package/03_Sample_Responses/` (profiles in
`python_api/sample_data/organizations.json`, answers in `python_api/benchmark/`). They have no websites, so
their written profile from the sample report stands in for the website research step. The staff view is
seeded with the same three organizations; `make reset-data` clears local test submissions.

### In the hackathon workshop IDE (code-server)

The app uses relative URLs, so it works behind the IDE's port proxy. From `/workshop`:

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r python_api/requirements.txt
make build      # skip if frontend/dist is already there; needs Node 20+
make serve      # 0.0.0.0:8000, offline mock narrative
```

Open it from the **Ports** tab (port 8000), or at `https://<workshop-host>/proxy/8000/`.

### With Claude on Amazon Bedrock

```bash
export AWS_PROFILE=<your sandbox profile>     # credentials for the hackathon sandbox account only
export OCI_LLM_MODE=bedrock                    # the default
export OCI_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6   # any enabled Claude profile in us-west-2
export OCI_ASYNC_ORCHESTRATION=true            # needed behind a 30 s proxy (IDE port preview, CloudFront)
make dev-api                                   # :8000
make dev-web                                   # :5173 (hot reload, proxies /api)
```

Model access must be enabled once for the account in the Bedrock console (us-west-2). The default
model id is a placeholder; use whichever Claude inference profile your sandbox has enabled. Sonnet 4.6
has been tested end to end. The Sonnet 4.5 default is now a legacy model, and Sonnet 5.5 and Haiku 5.5
reject the `temperature` setting the app sends.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `OCI_IN_SCOPE_DOMAINS` | `PL,FR,FM,ML` | Domains assessed. Any of PL FR GV HR FM ML CE TI. Validated at startup. |
| `OCI_LLM_MODE` | `bedrock` | `bedrock` = Claude on Bedrock; `mock` = offline placeholder text, no model called |
| `OCI_BEDROCK_MODEL_ID` | Sonnet 4.5 US profile | Model / inference profile id |
| `OCI_AWS_REGION` | `us-west-2` | Region for Bedrock and S3 |
| `OCI_STORE` | `local` | `local` (JSON files, same key scheme) or `s3` |
| `OCI_S3_BUCKET` | – | Bucket from the stack output, when `OCI_STORE=s3` |
| `OCI_LOCAL_STORE_DIR` | `python_api/.data` | Local store root |
| `OCI_SEED_ON_STARTUP` | `true` | Seed the 3 package sample organizations if the store is empty |
| `OCI_BEDROCK_MAX_TOKENS` | `16000` | Output budget for the recommendation call. On Sonnet 4.6, 60 gaps needed ~9,200 tokens and 71 gaps ~10,000; 8,000 cut the JSON off. |
| `OCI_BEDROCK_CHAT_MAX_TOKENS` | `500` | Output budget for each question-explanation chat response. |
| `OCI_BEDROCK_ASSESSMENT_CHAT_MAX_TOKENS` | `900` | Output budget for each reply in the feedback-refinement and staff assessment chats. |
| `OCI_ASYNC_ORCHESTRATION` | `false` | `true` = `POST /api/submit` saves the scores and returns 202 at once; the UI polls until Claude's narrative is saved. Use it behind proxies with a 30 s timeout. |
| `VITE_ORG_USER` / `VITE_ORG_PASSWORD` / `VITE_STAFF_*` | demo creds | Mocked login (front end) |

## How a submission flows

`POST /api/submit` →
1. **Completeness check.** Every in-scope statement needs `yes`/`no`, or HTTP 422 with `missing_count`/`missing_ids`. The engine is never called for an incomplete submission (it would silently count blanks as favourable).
2. **Scoring.** The unchanged engine, scoped by passing only the in-scope domains. Priority bands are percentile thirds *of this submission*, so the UI and PDF label them as relative.
3. **Research call.** The API fetches the org's public homepage (http/https, public IPs only, 6 s timeout), and Claude summarises it with "say 'not stated', don't invent" instructions. If there's no URL or it can't be read, this step is skipped.
4. **Recommendation call.** Claude gets the scores, every gap with its next steps, the research summary (or an explicit "no research available" note), and the whole Resource_Library, and returns JSON: overview, 30/60–90/3–6-month action plan, and one narrative per gap. Unknown question ids and resource ids are dropped; scores and bands are never taken from the model.
5. **Persist** to `submissions/<YYYY>/<MM>/<submission_id>.json` (S3 or local). If the write fails, the response still carries the scores and `persisted: false`.

With `OCI_ASYNC_ORCHESTRATION=true`, steps 1–2 run in the request and the record is saved with
`orchestration_status: "pending"` (HTTP 202). Steps 3–5 run in the background, and the UI polls
`GET /api/submissions/{id}` until the status changes. A live run takes 25–120 s, longer than the
30 s request timeout of CloudFront and the IDE port preview.

Bedrock calls go through the Converse API, are held under 1 request/second, and retry
throttling/transient errors with exponential backoff plus jitter.

| Endpoint | |
|---|---|
| `GET /api/questions` | In-scope questionnaire |
| `POST /api/questions/{id}/chat` | Clarify one canonical statement using a bounded, question-scoped chat |
| `POST /api/submit` | Validate → score → research → recommend → persist |
| `GET /api/submissions/{id}` | Stored result (no answers) |
| `POST /api/submissions/{id}/feedback-chat` | Organization asks about its feedback and adds context (grounded in its own assessment) |
| `POST /api/submissions/{id}/revise` | `{context}`: regenerate the narrative with the organization's added context. Scores, stages, gaps and bands are never touched; earlier narrative versions are kept. 202 + polling when `OCI_ASYNC_ORCHESTRATION=true` |
| `POST /api/submissions/{id}/change-answers` | The organization corrects its own answers; the engine re-scores them as a new, linked submission (original kept and marked superseded) |
| `GET /api/report/{id}[?inline=true]` | Detailed PDF: at a glance, where to start, action plan, area-by-area analysis, added context, every recommendation High → Medium → Low, resources |
| `GET /api/analytics?from=&to=&category=` | Network aggregates, including the average stage profile per area |
| `GET /api/staff/assessments?from=&to=&category=` | Staff only: named list of individual assessments |
| `GET /api/staff/assessments/{id}` | Staff only: one assessment with its feedback, stage profile, network comparison and code-computed insights |
| `POST /api/staff/assessments/{id}/chat` | Staff only: chat about one assessment, grounded in it and network aggregates |
| `GET /api/samples/{A,B,C}` | Demo helper: synthetic benchmark answers |

The design doc specifies these paths without the `/api` prefix; the prefix lets one process serve
both the API and the built SPA.

## Stages: one definition everywhere

An area's stage (from the unchanged engine) is the highest stage at which every practice, at that
stage and all below it, is in place. One early gap can hold an area at Seeding even at 80% capacity,
which looked contradictory next to staff analytics. `app/stage_profile.py` explains the stage instead
of changing it: practices in place at each of the five stages, which gaps hold the area at its stage,
and how much is already in place above it. The same profile and sentence appear on the results page,
in the PDF, in each staff assessment view, and (averaged) in network analytics. A property test checks
that the profile always implies exactly the engine's stage.

## Access note

Staff views name individual organizations (staff only; organizations never see each other). Login is
still mocked in the front end, so the `/api/staff/*` routes have no server-side access control yet.
Add real auth before any deployment with real organizations.

## Resource library

`python_api/resource_library/*.md` are injected in full into the recommendation prompt. The six `R*`
entries shipped here are **starter entries written for the MVP** (general nonprofit practice, not
Everytown guidance). Replace them with cleared CVI materials; confidential references stay in the
git-ignored `04_Reference_Materials/` or `private/` folders.

## Tests

```bash
make test       # verify_benchmark.py (A/B/C PASS) + pytest
make lint       # cfn-lint infra/*.yaml
```

The tests cover design Properties 3–14: questionnaire scope, exact completeness, scoring withheld
until complete, scores independent of any model output or failure, relative bands, PL1 reverse-coding,
benchmark fidelity, call order, prompt grounding, PDF contents and band order, analytics correctness
and aggregate-only output. They also cover Bedrock retry/throttle, S3 key scheme, write-failure
handling, research URL safety, and a static infra scan. CI runs all of it plus the front-end build.

## Deploying the AWS resources

See [`infra/README.md`](infra/README.md).

## Not done yet

- Front-end unit tests (spec tasks 7.2, 7.4, 7.6, 7.9 are optional and not written).
- Stretch goals: Fargate + CloudFront hosting, Bedrock Knowledge Base RAG, tone shaping.
- First live Bedrock run done with Sonnet 4.6 in the sandbox: 7, 32, 60 and 71 gaps took about 25, 65,
  112 and 118 s, and every gap got a narrative once the output budget was raised to 16,000 tokens.
  Narrative quality still needs review with CSF staff.
