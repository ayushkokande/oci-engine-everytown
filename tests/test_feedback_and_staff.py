"""Feedback refinement, shared stage profile, staff per-assessment views and chats.

Bedrock is always mocked. The key properties: a revision never changes a score,
stage, gap or band, and the stage profile always agrees with the engine's stage.
"""
import io
import json
import re

from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st
from pypdf import PdfReader

from app.llm import MockClaude
from app.questions import in_scope_question_ids
from app.scoring_adapter import gaps_from_recs, score_submission
from app.seed import benchmark_answers, seed_records
from app.stage_profile import implied_stage, stage_profile

SCOPE = ["PL", "FR", "FM", "ML"]
PROFILE = {"org_name": "Test Org", "website_url": "", "category": "grantee"}
IDS = in_scope_question_ids(SCOPE)


def _submit(client, sample="B"):
    r = client.post("/api/submit", json={"profile": PROFILE, "answers": benchmark_answers(sample, SCOPE)})
    assert r.status_code == 200, r.text
    return r.json()


def _pdf_text(data: bytes) -> str:
    return re.sub(r"\s+", " ", " ".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages))


# ------------------------------------------------------------------ stage profile

@settings(max_examples=150, deadline=None)
@given(st.lists(st.sampled_from(["yes", "no"]), min_size=len(IDS), max_size=len(IDS)))
def test_stage_profile_agrees_with_engine(values):
    answers = dict(zip(IDS, values))
    recs, _summ, display = score_submission(answers, SCOPE)
    gaps = gaps_from_recs(recs)
    for p, d in zip(stage_profile(display, gaps), display["domains"]):
        assert p["estimated_stage"] == d["estimated_stage"]
        assert implied_stage(p["stages"]) == d["estimated_stage"]
        assert sum(s["total"] - s["in_place"] for s in p["stages"]) == d["gap_count"]
        assert sum(s["total"] for s in p["stages"]) == d["total_questions"]
        # what holds the area at its stage is always one of its gaps, at the first incomplete stage
        if p["next_stage"]:
            first_open = next(s for s in p["stages"] if s["in_place"] < s["total"])
            assert p["next_stage"] == first_open["name"] and p["blocking_gap_ids"] == first_open["gap_ids"]


def test_results_and_analytics_carry_the_same_stage_profile(client_factory):
    client, _, _ = client_factory()
    body = _submit(client)
    assert [p["estimated_stage"] for p in body["stage_profile"]] == \
        [d["estimated_stage"] for d in body["scores"]["domains"]]
    assert "stage_rule" in body
    analytics = client.get("/api/analytics").json()
    assert analytics["stage_rule"] == body["stage_rule"]
    for d in analytics["domain_averages"]:
        assert [s["name"] for s in d["stage_profile"]][:1] == ["Seeding"]


# ------------------------------------------------------------------ feedback chat + revise

def test_revise_updates_narrative_but_never_scores(client_factory):
    client, store, llm = client_factory()
    first = _submit(client)
    context = "We are a team of 4 and already hold a monthly budget review, just not in writing."
    r = client.post("/api/submissions/%s/revise" % first["submission_id"], json={"context": context})
    assert r.status_code == 200, r.text
    after = r.json()
    for key in ("scores", "gaps", "stage_profile", "submission_id", "timestamp"):
        assert after[key] == first[key], key
    assert [(x["question_id"], x["priority"]) for x in after["recommendations"]] == \
        [(x["question_id"], x["priority"]) for x in first["recommendations"]]
    assert after["revision_status"] == "ok" and after["revision_count"] == 1
    assert [c["text"] for c in after["org_context"]] == [context]
    assert "Updated with the context you added" in after["overview"]
    assert after["revisions"][-1]["overview"] == first["overview"]
    assert after["domain_analysis"].keys() == {d["domain_id"] for d in first["scores"]["domains"]}
    # the context reached the prompt, inside its untrusted block, and the website was not re-researched
    prompt = llm.calls[-1]["prompt"]
    assert "<organization_context" in prompt and context in prompt
    assert [c["kind"] for c in llm.calls].count("research") == 0
    # persisted
    stored = store.get(first["submission_id"])
    assert stored.revision_count == 1 and stored.scores == first["scores"]


def test_revise_accumulates_context_and_retries(client_factory):
    client, _, llm = client_factory()
    sid = _submit(client)["submission_id"]
    assert client.post("/api/submissions/%s/revise" % sid, json={"context": ""}).status_code == 422
    client.post("/api/submissions/%s/revise" % sid, json={"context": "First note."})
    body = client.post("/api/submissions/%s/revise" % sid, json={"context": "Second note."}).json()
    assert [c["text"] for c in body["org_context"]] == ["First note.", "Second note."]
    assert "First note." in llm.calls[-1]["prompt"] and "Second note." in llm.calls[-1]["prompt"]
    retry = client.post("/api/submissions/%s/revise" % sid, json={"context": ""}).json()
    assert retry["revision_count"] == 3 and len(retry["org_context"]) == 2


def test_failed_revision_keeps_previous_feedback(client_factory):
    llm = MockClaude()
    client, _, _ = client_factory(llm=llm)
    first = _submit(client)
    llm.fail_on = {"recommend"}
    body = client.post("/api/submissions/%s/revise" % first["submission_id"],
                       json={"context": "We have two staff."}).json()
    assert body["revision_status"] == "error" and body["revision_error"].startswith("bedrock_unavailable")
    assert body["recommendations"] == first["recommendations"] and body["overview"] == first["overview"]
    assert body["revisions"] == [] and body["revision_count"] == 0
    assert [c["text"] for c in body["org_context"]] == ["We have two staff."]  # kept for a retry


def test_revise_async_returns_202_then_completes(client_factory, tmp_path):
    from fastapi.testclient import TestClient
    from app.config import Settings
    from app.main import create_app
    from app.store import LocalSubmissionStore
    store = LocalSubmissionStore(tmp_path / "async-store")
    settings_ = Settings(in_scope_domains=SCOPE, llm_mode="mock", local_store_dir=tmp_path / "async-store",
                         seed_on_startup=False, frontend_dist=tmp_path / "no-dist", async_orchestration=True)
    client = TestClient(create_app(settings_, store=store, llm=MockClaude()))
    r = client.post("/api/submit", json={"profile": PROFILE, "answers": benchmark_answers("A", SCOPE)})
    sid = r.json()["submission_id"]
    r = client.post("/api/submissions/%s/revise" % sid, json={"context": "Volunteer-run."})
    assert r.status_code == 202 and r.json()["revision_status"] == "pending"
    done = client.get("/api/submissions/" + sid).json()  # background task ran after the response
    assert done["revision_status"] == "ok" and done["revision_count"] == 1


def test_feedback_chat_is_grounded_and_validated(client_factory):
    client, _, llm = client_factory()
    first = _submit(client)
    url = "/api/submissions/%s/feedback-chat" % first["submission_id"]
    r = client.post(url, json={"messages": [{"role": "user", "content": "Why is PL2 high priority?"}]})
    assert r.status_code == 200 and r.json()["reply"]
    call = llm.calls[-1]
    assert call["kind"] == "feedback_chat"
    assert "Never change, recompute" in call["system"]
    digest = json.loads(call["prompt"].split("<assessment>\n")[1].split("\n</assessment>")[0])
    assert digest["organization"]["name"] == "Test Org" and "answers" not in digest
    bad = client.post(url, json={"messages": [{"role": "assistant", "content": "hi"}]})
    assert bad.status_code == 422
    assert client.post("/api/submissions/nope/feedback-chat",
                       json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 404
    failing = MockClaude(fail_on={"feedback_chat"})
    client2, _, _ = client_factory(llm=failing)
    sid2 = _submit(client2)["submission_id"]
    assert client2.post("/api/submissions/%s/feedback-chat" % sid2,
                        json={"messages": [{"role": "user", "content": "hi"}]}).status_code == 503


# ------------------------------------------------------------------ staff per assessment

def _seeded_client(client_factory):
    client, store, llm = client_factory()
    for rec in seed_records(SCOPE):
        store.put(rec)
    return client, store, llm


def test_staff_list_and_detail_link_insights_to_feedback(client_factory):
    client, _, _ = _seeded_client(client_factory)
    mine = _submit(client, "A")
    rows = client.get("/api/staff/assessments").json()["assessments"]
    assert len(rows) == 10 and rows[0]["submission_id"] == mine["submission_id"]
    assert rows[0]["org_name"] == "Test Org" and "answers" not in rows[0]
    assert len(client.get("/api/staff/assessments?category=non_grantee").json()["assessments"]) == 4

    detail = client.get("/api/staff/assessments/" + mine["submission_id"]).json()
    assert "answers" not in detail and detail["network"]["assessments"] == 10
    own = {g["question_id"] for g in mine["gaps"]}
    kinds = {i["kind"] for i in detail["insights"]}
    assert "stage" in kinds and "common_gap" in kinds
    for insight in detail["insights"]:
        assert set(insight["question_ids"]) <= own  # every insight links to this org's own feedback
    assert set(detail["network"]["gap_share_pct"]) <= own


def test_staff_detail_shows_org_context(client_factory):
    client, _, _ = _seeded_client(client_factory)
    sid = _submit(client)["submission_id"]
    client.post("/api/submissions/%s/revise" % sid, json={"context": "Our ED is part-time."})
    detail = client.get("/api/staff/assessments/" + sid).json()
    ctx = [i for i in detail["insights"] if i["kind"] == "context"]
    assert ctx and "part-time" in ctx[0]["detail"]


def test_staff_chat_uses_aggregates_not_other_orgs(client_factory):
    client, _, llm = _seeded_client(client_factory)
    sid = _submit(client)["submission_id"]
    r = client.post("/api/staff/assessments/%s/chat" % sid,
                    json={"messages": [{"role": "user", "content": "What should I raise first?"}]})
    assert r.status_code == 200 and r.json()["reply"]
    call = llm.calls[-1]
    assert call["kind"] == "staff_chat"
    assert "<network_aggregates>" in call["prompt"] and "<computed_insights>" in call["prompt"]
    for other in ("Southside", "Riverbend", "Metro Community", "Synthetic Variant"):
        assert other not in call["prompt"]


# ------------------------------------------------------------------ report

def test_detailed_report_inline_with_analysis_and_context(client_factory):
    client, _, _ = client_factory()
    sid = _submit(client)["submission_id"]
    client.post("/api/submissions/%s/revise" % sid, json={"context": "We share one bookkeeper."})
    r = client.get("/api/report/%s?inline=true" % sid)
    assert r.status_code == 200 and r.headers["content-disposition"].startswith("inline")
    assert client.get("/api/report/" + sid).headers["content-disposition"].startswith("attachment")
    text = _pdf_text(r.content)
    for heading in ("At a glance", "Where to start", "Area-by-area analysis", "To reach the next stage",
                    "Context you added", "We share one bookkeeper", "Resources referenced"):
        assert heading in text, heading
