# Requirements Document

## Introduction

The Everytown Organizational Capacity Index (OCI) platform helps a Community Violence Intervention (CVI) nonprofit assess how well it is run and receive personalized, actionable recommendations to strengthen its operational capacity. An existing deterministic Python prototype presents a questionnaire and computes capacity scores across domains. This feature adds an LLM orchestration layer on Amazon Bedrock (Claude) that takes an organization's answers, draws on a curated library of CVI resources, and generates customized recommendations an organization can act on within weeks or months.

The system comprises a JavaScript/TypeScript front-end application (mocked login, organization profile form, quiz-style questionnaire, processing indicators, results page, and PDF download trigger) and a Python API (deterministic scoring plus Amazon Bedrock orchestration). Scoring remains deterministic and reproducible in the existing engine; the LLM narrates and enhances recommendations but never computes scores. The target outcome is a working end-to-end demo where a CVI organization completes a scoped assessment and downloads a personalized recommendations report.

The MVP runs locally or in a sandbox hackathon environment first. Hosted deployment on Fargate with CloudFront is a stretch goal. CloudFormation templates ship for AWS resources so Everytown Labs can iterate toward production rather than rebuild.

## Glossary

- **OCI_Platform**: The complete system comprising the front-end application and the Python API that delivers organizational capacity assessment and personalized recommendations.
- **Frontend_App**: The JavaScript/TypeScript front-end application responsible for mocked login, the organization profile form, the quiz-style questionnaire, processing indicators, the results page, and the PDF download trigger.
- **Python_API**: The Python service, using boto3, that owns deterministic scoring and Amazon Bedrock orchestration.
- **Scoring_Engine**: The existing deterministic Python code in `engine/scoring.py` that computes capacity scores and priority bands. Reused unchanged.
- **Bedrock_Orchestrator**: The component of the Python API that performs the hardcoded, sequential pipeline of Amazon Bedrock (Claude) model calls.
- **Resource_Library**: The curated collection of CVI reference materials (PDFs and web pages) used to ground recommendation generation.
- **In_Scope_Domains**: The configurable set of OCI capacity domains assessed in this MVP, defaulting to Planning (PL), Fundraising (FR), Financial Management (FM), and Monitoring, Learning and Evaluation (ML) — 72 statements.
- **Priority_Band**: A relative percentile classification (High, Medium, Low) assigned to each capacity gap, computed as percentile thirds of all gaps in the current submission.
- **Capacity_Gap**: A questionnaire statement whose answer equals its `trigger_on` value, indicating an area for improvement.
- **Staff_User**: A CSF program staff member who accesses the aggregate analytics view behind a mocked staff login.
- **Org_User**: A CVI organization leader who completes the assessment and receives recommendations.
- **Recommendations_Report**: The downloadable PDF, rendered from plain text, containing personalized recommendations, plus the equivalent on-screen results.

## Requirements

### Requirement 1: Mocked Authentication

**User Story:** As an Org_User, I want to log in with dummy credentials, so that I can access the assessment without a real identity system being built for the hackathon.

_Source: Vision (Mocked login, Must Have); Technical (no Cognito)._

#### Acceptance Criteria

1. WHEN an Org_User submits valid dummy credentials, THE Frontend_App SHALL grant access to the organization profile form.
2. IF an Org_User submits credentials that do not match the configured dummy credentials, THEN THE Frontend_App SHALL deny access and display a login failure message.
3. THE Frontend_App SHALL provide a mocked staff login path that grants a Staff_User access to the aggregate analytics view.
4. THE OCI_Platform SHALL implement authentication without Amazon Cognito.

### Requirement 2: Organization Profile Capture

**User Story:** As an Org_User, I want to enter my organization name and website URL, so that the system can research my organization and tailor recommendations.

_Source: Vision (user journey step 2)._

#### Acceptance Criteria

1. WHEN an authenticated Org_User opens the profile form, THE Frontend_App SHALL present fields for organization name and organization website URL.
2. IF an Org_User submits the profile form with an empty organization name or an empty website URL, THEN THE Frontend_App SHALL block submission and display a validation message identifying the missing field.
3. WHEN an Org_User submits a valid profile form, THE Frontend_App SHALL advance the Org_User to the questionnaire.

### Requirement 3: Scoped Questionnaire

**User Story:** As an Org_User, I want to answer a quiz-style questionnaire for the in-scope domains, so that my organization's capacity can be assessed.

_Source: Vision (Scoped questionnaire, Must Have); clarify answer 1 (PL, FR, FM, ML configurable); clarify answer 2 (quiz-style form)._

#### Acceptance Criteria

1. THE Frontend_App SHALL present questionnaire statements for the In_Scope_Domains, defaulting to Planning, Fundraising, Financial Management, and Monitoring, Learning and Evaluation.
2. THE OCI_Platform SHALL read the set of In_Scope_Domains from configuration so that the assessed domains can be changed without code changes.
3. THE Frontend_App SHALL present the questionnaire as a quiz-style form that collects a Yes or No answer for each statement.
4. WHEN an Org_User submits the questionnaire, THE Frontend_App SHALL transmit the collected answers to the Python_API.

### Requirement 4: Completeness Validation Before Scoring

**User Story:** As a CSF program staff member, I want the system to require a complete set of answers before scoring, so that unanswered statements do not silently inflate capacity scores.

_Source: Scoring README gotcha 2 (unanswered counts as favourable); Vision (accurate scoring)._

#### Acceptance Criteria

1. WHEN answers are received for scoring, THE Python_API SHALL verify that every statement in the In_Scope_Domains has a recorded answer of "yes" or "no".
2. IF one or more statements in the In_Scope_Domains lack a recorded answer, THEN THE Python_API SHALL reject the submission for scoring and return a completeness error identifying the count of missing answers.
3. WHILE any statement in the In_Scope_Domains lacks a recorded answer, THE Python_API SHALL withhold invocation of the Scoring_Engine.

### Requirement 5: Deterministic Scoring

**User Story:** As Everytown Labs, I want scores computed deterministically in the existing engine, so that results are reproducible and a model issue cannot change a result.

_Source: Technical (deterministic scoring before the model; LLM never computes scores); Scoring README (relative priority bands, PL1 reverse-coded); benchmark samples A, B, C._

#### Acceptance Criteria

1. THE OCI_Platform SHALL compute all capacity scores and Priority_Bands using the existing Scoring_Engine in `engine/scoring.py` without modification to that engine.
2. THE Bedrock_Orchestrator SHALL NOT compute, alter, or override any capacity score or Priority_Band.
3. WHEN classifying each Capacity_Gap, THE Scoring_Engine SHALL assign the Priority_Band as a relative percentile third across all gaps in the current submission.
4. WHEN evaluating statement PL1, THE Scoring_Engine SHALL treat an answer of "yes" as the Capacity_Gap condition, consistent with its reverse-coded `trigger_on` value.
5. WHEN scoring the benchmark answer sets for samples A, B, and C, THE Scoring_Engine SHALL produce results that match the corresponding expected results so that `verify_benchmark.py` reports PASS for all three samples.

### Requirement 6: Bedrock Orchestration Pipeline

**User Story:** As an Org_User, I want the system to research my organization and generate recommendations grounded in CVI resources, so that the guidance is personalized and actionable.

_Source: Vision (LLM orchestration pipeline, personalized recommendations, Must Have); Technical (two Bedrock Claude calls; hardcoded pipeline; in-prompt resource library baseline)._

#### Acceptance Criteria

1. THE Bedrock_Orchestrator SHALL invoke Claude on Amazon Bedrock in the us-west-2 region using boto3.
2. WHEN an assessment is submitted and passes completeness validation, THE Bedrock_Orchestrator SHALL execute a hardcoded sequential pipeline consisting of one Amazon Bedrock Claude call to research the organization from its website URL and one Amazon Bedrock Claude call to generate recommendations.
3. WHEN generating recommendations, THE Bedrock_Orchestrator SHALL ground the recommendations in the deterministic scores, the organization research output, and the Resource_Library.
4. THE Bedrock_Orchestrator SHALL supply the Resource_Library to the recommendation call as in-prompt context.
5. IF an Amazon Bedrock model call fails, THEN THE Python_API SHALL return an orchestration error to the Frontend_App and SHALL retain the deterministic scores already computed.
6. THE OCI_Platform SHALL use Amazon Bedrock Claude as the only model host and SHALL NOT invoke any non-AWS model service.

### Requirement 7: Processing Indicators

**User Story:** As an Org_User, I want to see visible processing steps after I submit, so that I understand the tool is reading my answers, consulting resources, and researching my organization.

_Source: Vision (Processing indicators, Should Have)._

#### Acceptance Criteria

1. WHILE the Python_API is processing a submitted assessment, THE Frontend_App SHALL display processing indicators for reading the answers, consulting the CVI resources, and researching the organization.
2. WHEN all processing steps complete, THE Frontend_App SHALL advance the Org_User to the results page.

### Requirement 8: Results and PDF Report

**User Story:** As an Org_User, I want to view my results on screen and download a PDF report, so that I can act on the personalized recommendations.

_Source: Vision (PDF report, Must Have; user journey step 5); Technical (plain text rendered to PDF)._

#### Acceptance Criteria

1. WHEN recommendation generation completes, THE Frontend_App SHALL display the capacity scores and personalized recommendations on the results page.
2. THE Frontend_App SHALL provide a control that triggers download of the Recommendations_Report as a PDF.
3. WHEN the Org_User triggers the download, THE Python_API SHALL produce the Recommendations_Report as plain text rendered to a PDF.
4. THE Recommendations_Report SHALL present recommendations ordered by Priority_Band.

### Requirement 9: Staff Aggregate Analytics

**User Story:** As a Staff_User, I want an aggregate analytics view behind a mocked staff login, so that I can understand capacity trends across organizations without exposing individual comparisons.

_Source: Clarify summary (staff analytics view, aggregate only, no peer benchmarking); Vision (peer benchmarking out of scope)._

#### Acceptance Criteria

1. WHILE a Staff_User is authenticated through the mocked staff login, THE Frontend_App SHALL display aggregate analytics across completed assessments.
2. THE OCI_Platform SHALL present staff analytics as aggregate figures only and SHALL NOT present peer benchmarking between named organizations.

### Requirement 10: Data Handling, Infrastructure, and Open-Source Delivery

**User Story:** As Everytown Labs, I want a sandbox-only, synthetic-data build delivered as a forkable repository with CloudFormation, so that we can iterate toward production safely and without confidential data.

_Source: Vision and Technical (sandbox-only; synthetic/scrubbed data, no PII; excluded services; AWS only; CloudFormation; open-source)._

#### Acceptance Criteria

1. THE OCI_Platform SHALL operate exclusively within the sandbox hackathon AWS account and SHALL NOT access Everytown's AWS account.
2. THE OCI_Platform SHALL process only synthetic or scrubbed response data and SHALL exclude personally identifiable information.
3. THE OCI_Platform SHALL provision its AWS resources through CloudFormation templates.
4. THE OCI_Platform SHALL use Amazon S3 as the only persistent AWS storage service required for the baseline and SHALL exclude Amazon RDS, load balancers, AWS WAF, AWS KMS, AWS Secrets Manager, and AWS Marketplace offerings.
5. THE OCI_Platform SHALL be delivered as an open-source, forkable repository free of Everytown-confidential content.
6. THE OCI_Platform SHALL use AWS as the only cloud provider.

## Out of Scope

- Real authentication and identity management (Amazon Cognito).
- Staff review queue.
- Peer benchmarking dashboard, charts, or maps.
- Relational database, load balancer, WAF, KMS, Secrets Manager, and Marketplace offerings.
- All eight OCI domains; this MVP is scoped to the configurable In_Scope_Domains (default PL, FR, FM, ML).

## Stretch Goals

- Hosted, clickable front end on Fargate with CloudFront for a public URL.
- RAG using an Amazon Bedrock knowledge base backed by Amazon S3, used if the Resource_Library is too large for in-prompt context injection.
- Tone and vocabulary shaped by Everytown's communications guide and public web pages.

## Open Assumptions (to confirm with Everytown)

These items are flagged for later confirmation and are not treated as blockers for the MVP build.

1. **Access and identity verification**: How Org_Users are provisioned and verified beyond mocked credentials is unconfirmed. Assumption: mocked credentials suffice for the demo.
2. **Public reference materials**: Which reference files in the Resource_Library may be distributed in the open-source repository is unconfirmed. Assumption: only non-confidential materials are included until confirmed.
3. **PDF format confirmation**: The exact Recommendations_Report layout and formatting is to be confirmed with Megan. Assumption: plain text rendered to PDF, ordered by Priority_Band, until confirmed.
