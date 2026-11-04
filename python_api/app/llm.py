"""Model clients.

``BedrockClaude`` is the only real model host: Claude on Amazon Bedrock via
the boto3 ``bedrock-runtime`` Converse API, in the configured region
(us-west-2). It keeps calls under 1 request/second and retries throttling /
transient errors with exponential backoff plus jitter.

``MockClaude`` is an offline stand-in used by automated tests and by
``OCI_LLM_MODE=mock`` for UI work without AWS credentials. It calls no model
service of any kind; its output is clearly labeled as mock text.
"""
from __future__ import annotations

import json
import random
import threading
import time
from typing import Callable, Protocol

RETRYABLE = {
    "ThrottlingException",
    "ServiceUnavailableException",
    "ModelNotReadyException",
    "InternalServerException",
    "ModelTimeoutException",
}


class ModelError(RuntimeError):
    def __init__(self, code: str, message: str = ""):
        super().__init__(message or code)
        self.code = code


class LLMClient(Protocol):
    def invoke(self, kind: str, system: str, prompt: str, *, max_tokens: int,
               context: dict | None = None) -> str: ...


class BedrockClaude:
    def __init__(self, model_id: str, region: str = "us-west-2", *, client=None,
                 min_interval: float = 1.05, max_retries: int = 5,
                 sleep: Callable[[float], None] = time.sleep,
                 clock: Callable[[], float] = time.monotonic):
        if client is None:
            import boto3
            from botocore.config import Config
            client = boto3.client(
                "bedrock-runtime", region_name=region,
                # Non-streaming calls return only when generation ends: up to ~16k
                # output tokens at ~85 tokens/s, so allow well over 180 s.
                config=Config(read_timeout=300, connect_timeout=10, retries={"max_attempts": 1}))
        self.client = client
        self.model_id = model_id
        self.min_interval = min_interval
        self.max_retries = max_retries
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._last_call = float("-inf")

    def _throttle(self) -> None:
        with self._lock:
            wait = self.min_interval - (self._clock() - self._last_call)
            if wait > 0:
                self._sleep(wait)
            self._last_call = self._clock()

    def invoke(self, kind, system, prompt, *, max_tokens, context=None) -> str:
        from botocore.exceptions import BotoCoreError, ClientError

        last_code = "bedrock_error"
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self.client.converse(
                    modelId=self.model_id,
                    system=[{"text": system}],
                    messages=[{"role": "user", "content": [{"text": prompt}]}],
                    inferenceConfig={"maxTokens": max_tokens, "temperature": 0.2},
                )
                parts = resp["output"]["message"]["content"]
                return "".join(p.get("text", "") for p in parts)
            except ClientError as e:
                last_code = e.response.get("Error", {}).get("Code", "ClientError")
                if last_code in RETRYABLE and attempt < self.max_retries - 1:
                    self._sleep((2 ** attempt) + random.uniform(0, 0.5))
                    continue
                raise ModelError(last_code, str(e)) from e
            except BotoCoreError as e:  # credentials, endpoint, read timeout
                raise ModelError(type(e).__name__, str(e)) from e
        raise ModelError(last_code)


class MockClaude:
    """Deterministic offline stand-in for research, recommendations, and chat."""

    def __init__(self, fail_on: set[str] | None = None, raw: dict | None = None):
        self.fail_on = fail_on or set()
        self.raw = raw or {}
        self.calls: list[dict] = []

    def invoke(self, kind, system, prompt, *, max_tokens, context=None) -> str:
        self.calls.append({"kind": kind, "system": system, "prompt": prompt})
        if kind in self.fail_on:
            raise ModelError("mock_failure", "mock %s call failed" % kind)
        if kind in self.raw:
            return self.raw[kind]
        ctx = context or {}
        if kind == "question_chat":
            statement = ctx.get("question_text", "the statement shown in the questionnaire")
            return ("[Offline mock - no model was called] In plain language, this asks whether the "
                    "following practice is currently in place: \"%s\" Think about a concrete routine, "
                    "example, or record that shows what happens today. This explanation does not choose "
                    "Yes or No for you." % statement)
        if kind == "feedback_chat":
            return ("[Offline mock - no model was called] Thanks, that helps. Your scores stay as "
                    "submitted, but when you press 'Update my feedback' the recommendations will take "
                    "what you said into account: \"%s\" What else about your team or constraints "
                    "should the feedback reflect?" % ctx.get("last", "")[:200])
        if kind == "staff_chat":
            return ("[Offline mock - no model was called] For %s, start the coaching conversation with "
                    "the gaps that hold each area at its stage (see the Stage insights), then the "
                    "High-priority items in its action plan. You asked: \"%s\""
                    % (ctx.get("org_name") or "this organization", ctx.get("last", "")[:200]))
        if kind == "research":
            return ("[Offline mock - no model was called] %s (%s). Set OCI_LLM_MODE=bedrock to "
                    "have Claude on Amazon Bedrock summarise the organization's public website."
                    % (ctx.get("org_name", "This organization"), ctx.get("website_url", "no URL")))
        gaps = ctx.get("gaps", [])
        library_ids = ctx.get("library_ids", [])
        org_context = ctx.get("org_context") or []
        tailored = (" (Updated with the context you added: %s.)" % "; ".join(org_context)[:160]
                    if org_context else "")
        recs = []
        for g in gaps:
            steps = g.get("next_steps") or []
            first = steps[0] if steps else "Review this practice with your team"
            recs.append({
                "question_id": g["question_id"],
                "narrative": ("[Mock] First step: %s. %s" % (
                    first.rstrip("."),
                    "Then work through the remaining next steps over the coming months."
                    if len(steps) > 1 else "")).strip() + tailored,
                "resource_ids": [r for r in library_ids if r in g.get("suggested_resources", [])][:2],
            })
        top = [g["question_id"] for g in gaps]
        plan = [
            {"timeframe": "Next 30 days", "actions": [
                {"text": "Work on the first High-priority item with your leadership team.", "question_ids": top[:1]}]},
            {"timeframe": "Next 60-90 days", "actions": [
                {"text": "Take on the next two items in your list.", "question_ids": top[1:3]}]},
            {"timeframe": "Next 3-6 months", "actions": [
                {"text": "Review progress and pick the next set of Medium-priority items.", "question_ids": top[3:5]}]},
        ]
        return json.dumps({
            "overview": "[Offline mock - no model was called] This narrative is placeholder text "
                        "built from the questionnaire's own next steps." + tailored,
            "domain_analysis": [{"domain_id": d, "analysis": "[Mock] Analysis for %s: start with the "
                                 "practices that hold this area at its current stage." % d}
                                for d in ctx.get("domain_ids", [])],
            "action_plan": plan,
            "recommendations": recs,
        })


def build_llm(settings) -> LLMClient:
    if settings.llm_mode == "mock":
        return MockClaude()
    return BedrockClaude(settings.bedrock_model_id, settings.aws_region)
