# Vision Document: Everytown OCI Platform

_AWS Breaking Barriers hackathon MVP, derived from the OCI scoping session_

## Executive Summary

The Organizational Capacity Index (OCI) platform helps a community violence intervention (CVI) nonprofit assess how well it is run and receive personalized, actionable recommendations to get stronger. The existing prototype is deterministic Python code with a minimal UI: it presents a questionnaire, scores the answers across capacity dimensions, and outputs the scores. The hackathon goal is to add an LLM orchestration layer on Amazon Bedrock that takes an organization's answers, draws on a curated library of CVI resources, and generates customized recommendations the organization can act on within weeks or months. The expected outcome is a working end-to-end demo where a CVI organization completes a scoped assessment and downloads a personalized recommendations report.

## Business Context

### Problem Statement

Most CVI organizations are small, community-rooted nonprofits that deliver strong frontline work while running on limited operational capacity. They need practical guidance on the back-office systems that let them sustain and grow. Everytown's Community Safety Fund built a manual OCI to meet this need and it worked, but producing individualized assessments and recommendations by hand took two staff members significant time per organization, so it cannot scale to the 140+ organization network. The current prototype scores the answers but has no AI reasoning or personalization layer, so it does not yet produce the tailored recommendations that made the manual pilot valuable.

### Business Drivers

- A proven manual pilot (45 organizations) that is too resource-intensive to scale.
- A two-person team supporting a growing network of 140+ grantee and alumni organizations.
- The need for recommendations that are both customized to an organization's answers and actionable in the near term.

### Target Users and Stakeholders

| User | Primary Need |
| --- | --- |
| CVI organization leaders | Enter the questionnaire and get back actionable, personalized recommendations to make the organization stronger over the next weeks and months |
| CSF program staff | Deliver tailored capacity support at scale without manual report writing |
| Everytown Labs | A forkable prototype and infrastructure-as-code that can be iterated toward production, not rebuilt |

### Business Constraints

- Deterministic code computes the scores. The LLM generates the recommendation narrative, it does not compute scores.
- The build runs entirely in sandbox hackathon environments and never touches Everytown's AWS account.
- No real organization data without PII removed first; synthetic or scrubbed responses only.
- AWS only, Python only, Claude only on Bedrock.

### Success Metrics

| Metric | Current | Target |
| --- | --- | --- |
| Personalized recommendations from answers | None (scores only) | LLM-generated, actionable recommendations |
| Organizations able to use it | 45 (manual pilot) | 3-4 CVI orgs find the recommendations helpful |
| End-to-end run | No AI layer | Assessment to downloadable PDF report |

## MVP Scope

### MVP Objective

Add an LLM orchestration layer to the existing deterministic prototype so a CVI organization completes a scoped assessment and receives personalized, actionable recommendations as a downloadable report.

### Domains in Scope

Two domains are confirmed for now, with the selection to be updated as the team finalizes it. The OCI covers eight domains in total; a well-executed subset is replicable to the rest after the hackathon.

- Strategic planning
- Fundraising

(Additional domains, such as human resources, may be added. To be confirmed with the Everytown team.)

### Features In Scope

| Feature | Description | Priority |
| --- | --- | --- |
| Scoped questionnaire | Questions for the confirmed domains | Must Have |
| Deterministic scoring | Existing Python engine computes the scores | Must Have |
| LLM orchestration pipeline | Hardcoded steps: web search on the org URL, scoring, recommendation generation from the CVI resource library | Must Have |
| Personalized recommendations | Actionable, near-term recommendations tailored to the answers | Must Have |
| PDF report | Downloadable report of the recommendations; plain text rendered to PDF | Must Have |
| Mocked login | Dummy credentials; no real auth | Must Have |
| Processing indicators | Visible steps showing the tool reading answers, consulting resources, researching the org | Should Have |

### Features Out of Scope

- Real authentication and identity management (Cognito)
- Staff review queue
- Peer benchmarking dashboard, charts, or maps
- Relational database, load balancer, WAF, KMS, Secrets Manager
- All eight domains (scoped to the confirmed subset)

### Stretch Goals

- Hosted, clickable front end (UI on Fargate with CloudFront)
- RAG using a Bedrock knowledge base backed by S3, if the resource library is too large for prompt-based context injection
- Tone and vocabulary shaped by Everytown's communications guide and public web pages

### MVP User Journey

1. Log in with dummy credentials.
2. Enter the organization name and website URL in a short form.
3. Answer the questionnaire for the in-scope domains.
4. Submit and watch the processing indicators as the tool reads the answers, consults the CVI resources, and researches the organization via its website.
5. Download a PDF with the personalized recommendations.

## Risks and Dependencies

### Prerequisites from Everytown

- Final list of confirmed domains (strategic planning and fundraising so far).
- Questionnaire questions for the selected domains.
- Scoring logic, as existing Python code or a written spec.
- Two or three synthetic or scrubbed org responses with expected scores and recommendations, to serve as the benchmark answer key.
- CVI resource library (PDFs and web pages) for the LLM context, targeted for end of week.
- A CVI domain expert available onsite to answer subject-matter questions.

### Key Risks

| Risk | Mitigation |
| --- | --- |
| Scoring logic or question bank not shared in time | Confirmed as a this-week deliverable from Sri; follow a written spec if code is not ready |
| Recommendations not grounded in the org's answers | Deterministic scores drive the recommendations; the LLM narrates and enhances, it does not score |
| Resource library too large for the context window | Prompt-based context injection is the baseline; RAG with S3 is the stretch path if volume requires it |
| Scope too large for 2-3 days | Hold to the confirmed domains, mock auth, PDF output, and keep excluded services out |

### Open Questions

- Final domain selection beyond strategic planning and fundraising.
- Total volume of the CVI resource library, which decides prompt injection versus RAG.
- Which CVI domain expert attends onsite in NYC.
