"""Runtime configuration, read from environment variables.

Nothing environment-specific is hardcoded in app code: the region, bucket,
model id and in-scope domains all come from here (and, when deployed, from the
CloudFormation stack outputs exported into the environment).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

API_ROOT = Path(__file__).resolve().parent.parent  # python_api/
REPO_ROOT = API_ROOT.parent

DEFAULT_IN_SCOPE = ["PL", "FR", "FM", "ML"]
DEFAULT_MODEL_ID = "us.anthropic.claude-sonnet-4-5-20250929-v1:0"


def _csv(value: str | None, default: list[str]) -> list[str]:
    if not value:
        return list(default)
    return [v.strip().upper() for v in value.split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    in_scope_domains: list[str] = field(default_factory=lambda: list(DEFAULT_IN_SCOPE))
    aws_region: str = "us-west-2"
    # "bedrock" calls Claude on Amazon Bedrock. "mock" is an offline stand-in
    # for local UI work and tests; it never calls any model service.
    llm_mode: str = "bedrock"
    bedrock_model_id: str = DEFAULT_MODEL_ID
    # Measured on Sonnet 4.6: a 60-gap submission needs ~9,200 output tokens, 71 gaps ~10,000.
    bedrock_max_tokens: int = 16000
    # A short, separate budget for one question-explanation chat response.
    question_chat_max_tokens: int = 500
    # Budget for one reply in the feedback-refinement and staff assessment chats.
    assessment_chat_max_tokens: int = 900
    # "local" writes JSON files under local_store_dir using the same key scheme
    # as S3; "s3" writes to the submissions bucket.
    store_backend: str = "local"
    local_store_dir: Path = API_ROOT / ".data"
    s3_bucket: str | None = None
    seed_on_startup: bool = True
    # True: POST /api/submit saves the scores and returns 202 at once; the Bedrock
    # pipeline runs in the background and the client polls GET /api/submissions/{id}.
    # Use behind proxies with short request timeouts (CloudFront's default is 30 s).
    async_orchestration: bool = False
    research_fetch_timeout_s: float = 6.0
    cors_origins: list[str] = field(default_factory=lambda: ["http://localhost:5173"])
    frontend_dist: Path = REPO_ROOT / "frontend" / "dist"


def load_settings() -> Settings:
    env = os.environ
    return Settings(
        in_scope_domains=_csv(env.get("OCI_IN_SCOPE_DOMAINS"), DEFAULT_IN_SCOPE),
        aws_region=env.get("OCI_AWS_REGION", env.get("AWS_REGION", "us-west-2")),
        llm_mode=env.get("OCI_LLM_MODE", "bedrock").lower(),
        bedrock_model_id=env.get("OCI_BEDROCK_MODEL_ID", DEFAULT_MODEL_ID),
        bedrock_max_tokens=int(env.get("OCI_BEDROCK_MAX_TOKENS", "16000")),
        question_chat_max_tokens=int(env.get("OCI_BEDROCK_CHAT_MAX_TOKENS", "500")),
        assessment_chat_max_tokens=int(env.get("OCI_BEDROCK_ASSESSMENT_CHAT_MAX_TOKENS", "900")),
        store_backend=env.get("OCI_STORE", "local").lower(),
        local_store_dir=Path(env.get("OCI_LOCAL_STORE_DIR", str(API_ROOT / ".data"))),
        s3_bucket=env.get("OCI_S3_BUCKET") or None,
        seed_on_startup=env.get("OCI_SEED_ON_STARTUP", "true").lower() in ("1", "true", "yes"),
        async_orchestration=env.get("OCI_ASYNC_ORCHESTRATION", "false").lower() in ("1", "true", "yes"),
        research_fetch_timeout_s=float(env.get("OCI_RESEARCH_FETCH_TIMEOUT", "6")),
        cors_origins=[o.strip() for o in env.get("OCI_CORS_ORIGINS", "http://localhost:5173").split(",") if o.strip()],
        frontend_dist=Path(env.get("OCI_FRONTEND_DIST", str(REPO_ROOT / "frontend" / "dist"))),
    )
