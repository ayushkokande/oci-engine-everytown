# Technical Document: Everytown OCI Platform

_AWS Breaking Barriers hackathon MVP, derived from the OCI scoping session_

## Technical Summary

The MVP adds an LLM orchestration layer to an existing deterministic Python prototype. The current prototype has a Render back end, a minimal UI, a questionnaire, and a deterministic scoring algorithm with no AI component. The hackathon work keeps the scoring in code and adds a hardcoded, multi-step pipeline on Amazon Bedrock (Claude) that generates personalized recommendations. The build runs in sandbox hackathon environments and is handed off as a forkable GitHub repository with CloudFormation templates so Everytown Labs can iterate toward production rather than rebuild.

## Technology Stack

What runs on which AWS service and what runs locally for the hackathon build.

| Component | Where it runs | Notes |
| --- | --- | --- |
| Python application (questionnaire, orchestration, PDF) | Local / sandbox | Runs locally for the demo; Fargate + CloudFront is a stretch goal for a hosted URL |
| Deterministic scoring engine | Local (in the Python app) | Existing code; computes scores, no model involved |
| LLM research + recommendation steps | Amazon Bedrock (Claude) | Two model calls: research the org from its URL, then generate recommendations |
| CVI resource library | In-prompt (baseline) / S3 + Bedrock KB (stretch) | Prompt-based context injection first; RAG with S3 only if the library is too large |
| Responses and scores store | Local data store | Lightweight local store in place of a cloud database |
| PDF report | Local (in the Python app) | Plain text rendered to a downloadable PDF |
| Hosting | Local for the demo | Fargate + CloudFront is a stretch goal, not required |

## Programming Languages

| Language | Status | Notes |
| --- | --- | --- |
| Python | Required | Required throughout, consistent with the existing codebase and team preference |
| JavaScript / TypeScript | Permitted | For the questionnaire and results UI if needed |
| Any non-AWS cloud | Prohibited | AWS only is a hard constraint |

## Frameworks and Libraries

| Library | Status | Notes |
| --- | --- | --- |
| AWS SDK for Python (boto3) | Required | Access to Bedrock and S3 |
| Existing deterministic scoring code | Required | Reuse as-is; the LLM never computes scores |
| A lightweight Python web framework | Preferred | Serve the form, questionnaire, and PDF download |
| A PDF generation library | Preferred | Render the recommendations as a downloadable PDF |
| Any library that lets the model compute scores | Prohibited | Scores must stay deterministic and reproducible |

## Cloud Environment

- Provider: AWS only (hard constraint).
- Account: sandbox hackathon workshop environment. The build never touches Everytown's AWS account.
- Model host: Amazon Bedrock, Claude only.
- Data store: a lightweight local store for responses and scores is acceptable in place of a cloud database.

## Preferred Technologies and Patterns

### Architecture Patterns

| Pattern | Guidance |
| --- | --- |
| Deterministic scoring before the model | Code computes the scores; the LLM only generates the recommendation narrative |
| Hardcoded pipeline over agentic | Predictable, sequential steps rather than autonomous agent behavior |
| Sandbox-only build | All work in the hackathon account; nothing touches Everytown's environment |
| Infrastructure as code | CloudFormation templates in a forkable GitHub repo for local iteration and sandbox deploy |


### Security and Data Handling

- No real organization or participant data in the hackathon account; synthetic or scrubbed responses only, with PII removed before sharing.
- Keep the model out of the scoring path so a model issue cannot change a result.
- Open-source the result per the Breaking Barriers requirement; keep the repo free of anything Everytown-confidential.
