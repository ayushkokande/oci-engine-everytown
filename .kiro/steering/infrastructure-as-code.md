---
inclusion: always
---

# Infrastructure as Code — Everytown OCI

How to build the OCI platform in the sandbox account and ship every AWS
resource as CloudFormation, so the whole stack deploys cleanly from the repo
and nothing lives only as a hand-made console resource.

## Guiding principle

Every AWS resource is defined in a CloudFormation template under `infra/`.
If a resource exists in the sandbox but not in a template, it is a bug. The
repo is the source of truth; the sandbox is disposable and must be
reproducible from `infra/` with no manual clicking.

Workflow: author template -> validate (`cfn-lint`) -> deploy to sandbox ->
confirm it works -> commit. Never create a resource in the console first and
backfill the template later.

## Hard constraints (from the spec)

- **AWS only.** No other cloud provider, ever.
- **Region: `us-west-2`.** Every resource and every Bedrock call. Do not
  hardcode the region in app code where a template parameter or environment
  variable belongs.
- **Model host: Amazon Bedrock, Claude only.** No non-AWS model service.
- **Sandbox only.** The stack runs in the hackathon sandbox account and never
  references or reaches into Everytown's AWS account. No cross-account ARNs,
  roles, or bucket policies in any template.
- **Persistent storage: Amazon S3 only.** One bucket for submissions. No
  database.

### Excluded services — do not add these to any template

Cognito, RDS, load balancers (ALB/NLB/ELB), WAF, KMS, Secrets Manager, and
AWS Marketplace offerings. If a template introduces one of these, stop and
rethink — the baseline MVP does not need them. (Fargate + CloudFront are a
stretch goal only, in their own optional template.)

## Repository layout

```
infra/
  oci-stack.yaml        # baseline: S3 bucket + IAM role/policy
  README.md             # deploy/teardown commands, parameters
  (stretch) hosting.yaml  # Fargate + CloudFront — optional, separate stack
```

Keep the baseline stack self-contained. Stretch-goal infrastructure
(Fargate/CloudFront for hosting, Bedrock Knowledge Base for RAG) goes in a
separate optional template so the core stack stays minimal and reviewable.

## S3 bucket requirements

- **Block Public Access fully enabled** on the bucket
  (`BlockPublicAcls`, `IgnorePublicAcls`, `BlockPublicPolicy`,
  `RestrictPublicBuckets` all `true`). This is non-negotiable.
- Submissions are stored as one JSON object per submission under
  date-partitioned keys: `submissions/<YYYY>/<MM>/<submission_id>.json`.
- No public bucket policy, no website hosting, no ACLs granting public read.
- Access is only through the application's IAM role.

## IAM requirements

- Least privilege. The application role gets exactly:
  - `s3:GetObject`, `s3:PutObject`, `s3:ListBucket` scoped to the submissions
    bucket (and its `/*` for object actions).
  - `bedrock:InvokeModel` for the Claude model calls.
- No wildcard `*` on Actions or Resources where a concrete ARN works.
- No inline cross-account trust. Trust policies stay within the sandbox
  account.

## Parameterize, don't hardcode

- Bucket name, model id, and any environment-specific value are
  **template parameters** or stack outputs, not literals buried in app code.
- The app reads resource names/ARNs from environment variables or stack
  outputs at startup, so the same code runs against any deploy of the stack.
- Export the bucket name and role ARN as stack **Outputs** so the app and any
  later stretch stack can consume them.

## Validation before deploy

Run these every time a template changes, and wire the first two into CI:

- `cfn-lint infra/*.yaml` — template must lint clean.
- A static scan asserting:
  - S3 Block Public Access is present and all four flags are `true`.
  - None of the excluded resource types appear
    (`AWS::Cognito::*`, `AWS::RDS::*`, `AWS::ElasticLoadBalancingV2::*`,
    `AWS::WAFv2::*`, `AWS::KMS::*`, `AWS::SecretsManager::*`).
- `verify_benchmark.py` stays green (A/B/C PASS) — unrelated to infra but part
  of every build gate.

## Deploy and teardown

- Deploy with `aws cloudformation deploy` (or `create-stack`/`update-stack`)
  against `us-west-2`. Document the exact command and required parameters in
  `infra/README.md`.
- Sandbox resources are disposable: a full teardown (`delete-stack`) followed
  by a fresh deploy must reproduce a working environment with no manual steps.
- Because the sandbox is temporary, **push to the repo continuously** — a lost
  sandbox should cost nothing but a redeploy.
- Enable Bedrock Claude model access in the sandbox account before first
  deploy (one-time, account-level; note it in `infra/README.md` since it is a
  prerequisite rather than a template resource).

## Data handling in infra

- Synthetic or scrubbed data only. No PII, no real organization or financial
  data in any bucket, parameter, or seeded object.
- Seed data for analytics comes from the package's sample organizations (A/B/C)
  only.

## Open-source hygiene

- The repo is forkable and open-source. Templates must contain nothing
  Everytown-confidential: no real account ids, no private ARNs, no internal
  endpoints, no confidential reference material.
- Confidential reference files stay out of the repo (e.g. a git-ignored
  `private/` folder) until cleared; only non-confidential materials ship in
  the Resource Library.
