---
inclusion: always
---

# Structure — where things live and status

```
.kiro/specs/everytown-oci-assessment/   requirements.md, design.md, tasks.md (source of truth)
.kiro/steering/                         product.md, tech.md, structure.md, infrastructure-as-code.md
python_api/
  app/main.py            FastAPI app factory + routes (create_app(settings, store, llm))
  app/config.py          env-driven Settings
  app/questions.py       QuestionService + CompletenessValidator + domain config validation
  app/scoring_adapter.py thin wrapper over the engine (scoping only)
  app/orchestrator.py    two-call Bedrock pipeline, prompts, website fetch, output cleaning, merge
  app/llm.py             BedrockClaude (Converse, throttle, retry) and MockClaude (offline)
  app/pdf_report.py      plain text -> PDF, ordered High -> Medium -> Low
  app/store.py           SubmissionRecord, Local/S3 stores, key scheme
  app/analytics.py       network aggregates for staff analytics
  app/stage_profile.py   shared stage profile (results, PDF, staff) explaining the engine's stage
  app/insights.py        code-computed per-assessment insights for staff, linked by question id
  app/assistant_chat.py  feedback-refinement chat (org) and per-assessment chat (staff)
  app/seed.py            package sample orgs A/B/C: seeding + profiles (sample_data/organizations.json)
  app/resources.py       Resource_Library loader
  resource_library/      R1–R6 placeholder resources (*.md with front matter)
  engine/ utils/ data/ verify_benchmark.py benchmark/   VENDORED — do not edit
frontend/src/
  App.tsx                step machine: login | profile | questionnaire | processing | results | staff
  components/Login.tsx ProfileForm.tsx Questionnaire.tsx Processing.tsx Results.tsx StaffAnalytics.tsx
  components/StaffAssessment.tsx AssessmentChat.tsx StageProfileView.tsx QuestionChatDialog.tsx
  api.ts types.ts config.ts (mocked creds + safe localStorage) styles.css
infra/oci-stack.yaml     S3 bucket (Block Public Access) + least-privilege IAM role; infra/README.md
tests/                   test_scoring_path.py, test_orchestration.py, test_report_store_analytics.py
.github/workflows/ci.yml benchmark + pytest + cfn-lint + frontend build
```

## Status (as of Nov 4, 2026)
- MVP merged to `main` (PR #1). All core tasks in `tasks.md` are done; 29 tests pass; benchmark green.
- Verified end to end in a headless browser with the **offline mock** narrative only.
  **Not yet run against live Bedrock** — first real run should check narrative quality, latency and
  token use (one narrative per gap, up to 72 per submission; `OCI_BEDROCK_MAX_TOKENS` default 8000).
- Not done: optional front-end tests (tasks 7.2, 7.4, 7.6, 7.9); stretch goals (task 13).

## Suggested next work
1. Questionnaire fatigue: stage-grouped "tick what's true" lists + "None of these yet" fast path for
   stage 4–5 statements (see product.md). Must keep every statement explicitly answered; add a test
   proving scores are identical to the one-at-a-time flow.
2. First live Bedrock run in the sandbox; tune prompt/token budget if needed.
3. Replace placeholder resources with cleared CVI materials.
4. Front-end tests; then stretch goals (Fargate + CloudFront, Bedrock KB RAG, tone shaping).

## Working conventions
- Keep scoring and narration separate; anything touching scores needs a property test.
- Python: type hints, small modules, no new heavy dependencies without reason.
- Frontend: plain CSS tokens in `styles.css`; wrap localStorage access in try/catch (see `config.ts`).
- Run `make test` and `make lint` before committing; keep CI green.
