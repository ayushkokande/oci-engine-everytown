---
inclusion: always
---

# Tech — stack, commands, constraints

## Stack
- **Python_API**: Python 3.10+, FastAPI, boto3 (Bedrock Converse + S3), fpdf2 for the PDF.
- **Frontend_App**: React 18 + TypeScript + Vite 5, plain CSS (`frontend/src/styles.css`), no UI library.
- **Infra**: CloudFormation (`infra/oci-stack.yaml`), region **us-west-2**.
- **Tests**: pytest + hypothesis (property tests ≥100 examples), pypdf, cfn-lint. Bedrock and S3 are
  **always mocked** in tests — never call a live model from tests.

## Commands (repo root)
```
make install      # pip install -r requirements-dev.txt && npm install (frontend)
make demo         # build SPA, serve everything on :8000 with OFFLINE MOCK narrative
make dev-api      # API on :8000 (OCI_LLM_MODE=bedrock by default) — run from python_api/
make dev-web      # Vite on :5173, proxies /api to :8000
make test         # verify_benchmark.py (A/B/C must PASS) + pytest
make lint         # cfn-lint infra/*.yaml
```
Demo logins: `demo` / `demo123` (organization), `staff` / `staff123` (CSF staff).

## Configuration (env vars)
| Var | Default | Notes |
|---|---|---|
| `OCI_IN_SCOPE_DOMAINS` | `PL,FR,FM,ML` | Any of PL FR GV HR FM ML CE TI; validated at startup |
| `OCI_LLM_MODE` | `bedrock` | `mock` = offline placeholder text, no model called |
| `OCI_BEDROCK_MODEL_ID` | `us.anthropic.claude-sonnet-4-5-20250929-v1:0` | Placeholder; use a Claude profile enabled in the sandbox |
| `OCI_AWS_REGION` | `us-west-2` | |
| `OCI_STORE` | `local` | `local` (JSON files) or `s3` |
| `OCI_S3_BUCKET` | – | From the stack output when `OCI_STORE=s3` |
| `OCI_SEED_ON_STARTUP` | `true` | Seeds 9 synthetic submissions if the store is empty |
| `VITE_ORG_USER` etc. | demo creds | Mocked login, front end only |

## Hard constraints
- AWS only; Claude on Bedrock is the only model host. No other model or cloud service.
- S3 is the only persistent store. Excluded: Cognito, RDS, load balancers, WAF, KMS, Secrets Manager,
  Marketplace. (Fargate + CloudFront and Bedrock KB RAG are stretch goals in separate templates.)
- Every AWS resource lives in CloudFormation under `infra/` (see `infrastructure-as-code.md`).
- **Never modify the vendored engine**: `python_api/engine/`, `python_api/utils/`,
  `python_api/data/questions.json`, `python_api/verify_benchmark.py`. Checksums are in
  `python_api/ENGINE_CHECKSUMS.sha256` and a test fails on any drift.
- `verify_benchmark.py` must report PASS for samples A, B and C on every change.

## Request flow (`POST /api/submit`)
1. Completeness check → HTTP 422 `incomplete_submission` with `missing_count`/`missing_ids`; engine not called.
2. Score with the unchanged engine, scoped by passing only in-scope domains.
3. Research call: fetch the org's public homepage (http/https, public IPs only, 6 s timeout); Claude
   summarises it ("say 'not stated', don't invent"). Skipped if no URL or unreadable.
   Research is homepage-style and AWS-only by decision: read only the org's own site, never a
   web search API or third-party source.
4. Recommendation call: scores + every gap with next steps + research (or "no research available")
   + full Resource_Library in-prompt → JSON {overview, action_plan, recommendations[]}. Unknown
   question/resource ids are dropped.
5. Persist `submissions/<YYYY>/<MM>/<submission_id>.json`. On model failure → `orchestration_status:
   "error"`, scores still returned; UI/PDF fall back to the questionnaire's next steps.
Bedrock calls: < 1 req/s throttle, exponential backoff + jitter on throttling/transient errors.

## API
`GET /api/questions`, `POST /api/submit`, `GET /api/submissions/{id}`, `GET /api/report/{id}` (PDF),
`GET /api/analytics?from&to&category`, `GET /api/samples/{A|B|C}` (demo answers), `GET /api/config`,
`POST /api/submissions/{id}/feedback-chat`, `POST /api/submissions/{id}/revise` (narrative only),
`GET /api/staff/assessments`, `GET /api/staff/assessments/{id}`, `POST /api/staff/assessments/{id}/chat`,
`GET /api/resources`. (Design doc paths have no `/api` prefix; the prefix lets one process also serve the SPA.)
