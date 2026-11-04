# Infrastructure (CloudFormation, us-west-2, sandbox only)

`oci-stack.yaml` creates exactly three things:

| Resource | Notes |
|---|---|
| `SubmissionsBucket` | All four Block Public Access flags on, bucket-owner-enforced, SSE-S3, versioned |
| `SubmissionsBucketPolicy` | Only denies non-TLS access; grants nothing |
| `OciApiRole` | `s3:GetObject`/`PutObject` on `submissions/*`, `s3:ListBucket` on the bucket, `bedrock:InvokeModel` on the configured Claude profile and model |

No Cognito, RDS, load balancers, WAF, KMS, Secrets Manager or Marketplace resources. The template
refuses to deploy outside us-west-2. A test (`tests/test_report_store_analytics.py::test_infra_template_static_scan`)
checks Block Public Access, banned resource types, and that no account ids are hardcoded.

## Prerequisite (one time, not a template resource)

Enable access to your chosen Claude model in the Bedrock console for **us-west-2** in the sandbox account.

## Deploy

```bash
cfn-lint infra/oci-stack.yaml

aws cloudformation deploy \
  --region us-west-2 \
  --stack-name oci-mvp \
  --template-file infra/oci-stack.yaml \
  --capabilities CAPABILITY_NAMED_IAM \
  --parameter-overrides \
      ProjectName=oci-mvp \
      BedrockInferenceProfileId=us.anthropic.claude-sonnet-4-6 \
      BedrockFoundationModelId=anthropic.claude-sonnet-4-6

aws cloudformation describe-stacks --region us-west-2 --stack-name oci-mvp \
  --query "Stacks[0].Outputs" --output table
```

## Run the API against the stack

```bash
# Run as the stack's least-privilege role. The SDK assumes it and refreshes it automatically.
aws configure set profile.oci-api.role_arn <ApiRoleArn output>
aws configure set profile.oci-api.credential_source Ec2InstanceMetadata   # or Environment, or set source_profile
aws configure set profile.oci-api.region us-west-2
export AWS_PROFILE=oci-api

export OCI_STORE=s3
export OCI_S3_BUCKET=<SubmissionsBucketName output>
export OCI_BEDROCK_MODEL_ID=us.anthropic.claude-sonnet-4-6   # must match the stack parameter
export OCI_ASYNC_ORCHESTRATION=true                           # behind the IDE preview or CloudFront
make dev-api
```

The role can read, write and list only `submissions/` in the bucket and call only the configured
Claude profile. It cannot delete objects, list other buckets or call other models.

On first start with an empty bucket, the API seeds 9 synthetic submissions so staff analytics has data.

## Teardown

The bucket is versioned, so empty it (all versions) before deleting the stack:

```bash
aws s3api delete-objects --bucket <bucket> --delete "$(aws s3api list-object-versions --bucket <bucket> \
  --query '{Objects: Versions[].{Key:Key,VersionId:VersionId}}' --output json)"
aws cloudformation delete-stack --region us-west-2 --stack-name oci-mvp
```

A fresh `deploy` reproduces the environment with no manual steps (apart from the one-time model access).
