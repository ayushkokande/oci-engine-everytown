"""Bedrock_Orchestrator with the model always mocked (Properties 6, 10, 11) and the boto3 client."""
import io
import json

import pytest
from botocore.exceptions import ClientError
from hypothesis import HealthCheck, given, settings, strategies as st

from app import orchestrator as orch
from app.llm import BedrockClaude, MockClaude, ModelError
from app.questions import in_scope_question_ids
from app.resources import load_library
from app.scoring_adapter import gaps_from_recs, score_submission
from app.seed import benchmark_answers

SCOPE = ["PL", "FR", "FM", "ML"]
LIB = load_library()


def scored(sample="A"):
    answers = benchmark_answers(sample, SCOPE)
    recs, _, display = score_submission(answers, SCOPE)
    return answers, display, gaps_from_recs(recs)


PROFILE = {"org_name": "Test Org", "website_url": "https://example.org", "category": "grantee"}


def fake_fetch(url, timeout=6.0):
    return "Test Org runs street outreach and youth mentoring in the city."


def test_call_order_and_research_flows_into_recommendation():
    """Property 10."""
    _, display, gaps = scored()
    llm = MockClaude(raw={"research": "RESEARCH-SUMMARY-MARKER"})
    res = orch.orchestrate(llm, PROFILE, display, gaps, LIB, fetch=fake_fetch)
    assert [c["kind"] for c in llm.calls] == ["research", "recommend"]
    assert "RESEARCH-SUMMARY-MARKER" in llm.calls[1]["prompt"]
    assert res.status == "ok" and res.research_summary == "RESEARCH-SUMMARY-MARKER"


@settings(max_examples=30, deadline=None)
@given(st.sampled_from(["A", "B", "C"]), st.booleans())
def test_recommendation_prompt_is_grounded(sample, with_url):
    """Property 11: scores, research-or-note, and every library entry are in the prompt."""
    _, display, gaps = scored(sample)
    llm = MockClaude()
    profile = dict(PROFILE, website_url=PROFILE["website_url"] if with_url else "")
    orch.orchestrate(llm, profile, display, gaps, LIB, fetch=fake_fetch)
    prompt = [c for c in llm.calls if c["kind"] == "recommend"][0]["prompt"]
    for d in display["domains"]:
        assert '"capacity_pct": %s' % d["score_pct"] in prompt
    for g in gaps:
        assert g["question_id"] in prompt
    for r in LIB:
        assert '<resource id="%s"' % r.id in prompt and r.body[:60] in prompt
    if not with_url:
        assert orch.NO_RESEARCH_NOTE in prompt
        assert [c["kind"] for c in llm.calls] == ["recommend"]


def test_unreachable_url_falls_back_without_research():
    _, display, gaps = scored()
    llm = MockClaude()
    res = orch.orchestrate(llm, PROFILE, display, gaps, LIB, fetch=lambda u, timeout=0: None)
    assert res.research_summary is None and res.status == "ok"
    assert [c["kind"] for c in llm.calls] == ["recommend"]


def test_research_failure_continues():
    _, display, gaps = scored()
    llm = MockClaude(fail_on={"research"})
    res = orch.orchestrate(llm, PROFILE, display, gaps, LIB, fetch=fake_fetch)
    assert res.research_summary is None and res.status == "ok"


bad_outputs = st.one_of(
    st.text(max_size=200),
    st.just("```json\n{not json}\n```"),
    st.just(json.dumps({"recommendations": [{"question_id": "PL2", "narrative": "x", "priority": "Low",
                                             "score_pct": 100}], "overview": "All scores are 100%"})),
    st.just(json.dumps({"recommendations": "nope"})),
)


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.sampled_from(["A", "B", "C"]), bad_outputs, st.booleans())
def test_scores_independent_of_model(client_factory, sample, output, fail):
    """Property 6: any model output (or failure) leaves scores and bands exactly as the engine computed."""
    answers, display, gaps = scored(sample)
    llm = MockClaude(fail_on={"recommend"} if fail else set(), raw={"recommend": output})
    client, _, _ = client_factory(llm=llm)
    body = client.post("/api/submit", json={"profile": dict(PROFILE, website_url=""), "answers": answers}).json()
    assert body["scores"] == display
    assert body["gaps"] == gaps
    for r in body["recommendations"]:
        g = next(x for x in gaps if x["question_id"] == r["question_id"])
        assert (r["priority"], r["priority_score"], r["text"]) == (g["priority"], g["priority_score"], g["text"])
    if fail:
        assert body["orchestration_status"] == "error" and body["recommendations"] == []


def test_model_cannot_cite_unknown_resources_or_gaps():
    _, display, gaps = scored()
    raw = json.dumps({"overview": "ok", "action_plan": [],
                      "recommendations": [{"question_id": gaps[0]["question_id"], "narrative": "Do it.",
                                           "resource_ids": ["R1", "R999"]},
                                          {"question_id": "ZZ9", "narrative": "invented"}]})
    res = orch.orchestrate(MockClaude(raw={"recommend": raw}), dict(PROFILE, website_url=""), display, gaps, LIB)
    assert set(res.narratives) == {gaps[0]["question_id"]}
    assert res.narratives[gaps[0]["question_id"]]["resource_ids"] == ["R1"]


# ---------------------------------------------------------------- boto3 Bedrock client

class FakeBedrock:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def converse(self, **kwargs):
        self.calls.append(kwargs)
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return {"output": {"message": {"content": [{"text": item}]}}}


def client_error(code):
    return ClientError({"Error": {"Code": code, "Message": code}}, "Converse")


def test_bedrock_retries_throttling_then_succeeds():
    sleeps = []
    fake = FakeBedrock([client_error("ThrottlingException"), client_error("ServiceUnavailableException"), "hello"])
    c = BedrockClaude("model-x", client=fake, sleep=sleeps.append, clock=lambda: 0.0)
    assert c.invoke("research", "sys", "prompt", max_tokens=10) == "hello"
    assert len(fake.calls) == 3
    assert fake.calls[0]["modelId"] == "model-x" and fake.calls[0]["system"] == [{"text": "sys"}]
    backoffs = [s for s in sleeps if s >= 1.0 and s != 1.05]
    assert len(backoffs) == 2 and 1.0 <= backoffs[0] < 1.6 and 2.0 <= backoffs[1] < 2.6


def test_bedrock_non_retryable_raises_model_error():
    fake = FakeBedrock([client_error("AccessDeniedException")])
    c = BedrockClaude("m", client=fake, sleep=lambda s: None)
    with pytest.raises(ModelError) as e:
        c.invoke("recommend", "s", "p", max_tokens=10)
    assert e.value.code == "AccessDeniedException" and len(fake.calls) == 1


def test_bedrock_throttle_keeps_calls_under_one_per_second():
    t = [0.0]
    sleeps = []

    def sleep(s):
        sleeps.append(s)
        t[0] += s

    fake = FakeBedrock(["a", "b", "c"])
    c = BedrockClaude("m", client=fake, sleep=sleep, clock=lambda: t[0])
    for _ in range(3):
        c.invoke("x", "s", "p", max_tokens=5)
    assert sum(sleeps) >= 2 * 1.05 - 1e-9


def test_bedrock_region_default():
    c = BedrockClaude("m")
    assert c.client.meta.region_name == "us-west-2"
    assert c.client.meta.service_model.service_name == "bedrock-runtime"


def test_fetch_refuses_private_addresses():
    assert orch.fetch_website_text("http://127.0.0.1:8000/") is None
    assert orch.fetch_website_text("http://169.254.169.254/latest/meta-data/") is None
    assert orch.fetch_website_text("file:///etc/passwd") is None


def test_html_text_extraction():
    p = orch._TextExtractor()
    p.feed("<html><head><title>Peace Org</title><meta name='description' content='We mentor youth'>"
           "<script>x=1</script></head><body><p>Street outreach</p></body></html>")
    assert p.title == "Peace Org" and p.meta_description == "We mentor youth"
    assert p.parts == ["Street outreach"]
