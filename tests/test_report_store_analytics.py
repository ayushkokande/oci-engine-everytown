"""PDF (Properties 12-13), persistence, analytics (Property 14), API wiring, infra scan."""
import io
import json
import random
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from hypothesis import HealthCheck, given, settings, strategies as st
from pypdf import PdfReader

from conftest import ROOT
from app.analytics import aggregate
from app.pdf_report import latin1, render_pdf
from app.seed import benchmark_answers, seed_records
from app.store import LocalSubmissionStore, S3SubmissionStore, key_for, new_submission_id

SCOPE = ["PL", "FR", "FM", "ML"]


def _pdf_text(data: bytes) -> str:
    text = " ".join(p.extract_text() for p in PdfReader(io.BytesIO(data)).pages)
    return re.sub(r"\s+", " ", text)


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", latin1(s))


@settings(max_examples=12, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.sampled_from(["A", "B", "C"]), st.booleans())
def test_pdf_contains_all_recommendations_in_band_order(client_factory, sample, degrade):
    """Properties 12 and 13."""
    from app.llm import MockClaude
    llm = MockClaude(fail_on={"recommend"} if degrade else set())
    client, _, _ = client_factory(llm=llm)
    body = client.post("/api/submit", json={"profile": {"org_name": "Test Org", "website_url": "", "category": "grantee"},
                                            "answers": benchmark_answers(sample, SCOPE)}).json()
    r = client.get("/api/report/" + body["submission_id"])
    assert r.status_code == 200 and r.headers["content-type"] == "application/pdf"
    assert r.content.startswith(b"%PDF")
    text = _pdf_text(r.content)
    items = body["recommendations"] or body["gaps"]
    positions = []
    for item in items:
        needle = _norm("[%s] %s" % (item["question_id"], item["text"]))
        pos = text.find(needle)
        assert pos >= 0, needle
        if item.get("narrative"):
            assert _norm(item["narrative"])[:50] in text
        positions.append((pos, item["priority"]))
    order = {"High": 0, "Medium": 1, "Low": 2}
    bands = [order[b] for _, b in sorted(positions)]
    assert bands == sorted(bands)


def test_submission_key_scheme(tmp_store):
    sid = new_submission_id("Southside Youth Peace Collective!", datetime(2026, 5, 14, 18, 30, tzinfo=timezone.utc))
    assert re.match(r"^2026-05-14T18-30-00Z_southside-youth-peace-collective_[0-9a-f]{6}$", sid)
    assert key_for(sid) == "submissions/2026/05/%s.json" % sid


def test_local_store_roundtrip(tmp_store):
    rec = seed_records(SCOPE)[0]
    key = tmp_store.put(rec)
    assert (tmp_store.root / key).exists()
    assert tmp_store.get(rec.submission_id).to_dict() == rec.to_dict()


class FakeS3:
    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self):
        self.objects = {}

    def put_object(self, Bucket, Key, Body, ContentType):
        self.objects[Key] = Body

    def get_object(self, Bucket, Key):
        if Key not in self.objects:
            raise self.exceptions.NoSuchKey()
        return {"Body": io.BytesIO(self.objects[Key])}

    def list_objects_v2(self, Bucket, Prefix, MaxKeys=1000, ContinuationToken=None):
        keys = sorted(k for k in self.objects if k.startswith(Prefix))[:MaxKeys]
        return {"Contents": [{"Key": k} for k in keys], "KeyCount": len(keys), "IsTruncated": False}


def test_s3_store_roundtrip_and_prefixes():
    s3 = FakeS3()
    store = S3SubmissionStore("bucket", "us-west-2", client=s3)
    assert store.is_empty()
    recs = seed_records(SCOPE)
    for r in recs:
        store.put(r)
    assert all(k.startswith("submissions/") and k.endswith(".json") for k in s3.objects)
    assert len(store.list_records()) == len(recs)
    assert store.get(recs[0].submission_id).submission_id == recs[0].submission_id
    assert store.get(new_submission_id("missing")) is None


def test_store_write_failure_keeps_scores(client_factory):
    class Broken(LocalSubmissionStore):
        def put(self, record):
            raise IOError("disk full")

    client, _, _ = client_factory(store=Broken(Path("/nonexistent")))
    body = client.post("/api/submit", json={"profile": {"org_name": "X", "website_url": "", "category": "grantee"},
                                            "answers": benchmark_answers("B", SCOPE)}).json()
    assert body["persisted"] is False and body["scores"]["overall_stats"]["total_questions"] == 72
    assert client.get("/api/report/" + body["submission_id"]).status_code == 200


dates = st.dates(min_value=datetime(2026, 1, 1).date(), max_value=datetime(2026, 12, 31).date())


@settings(max_examples=100, deadline=None)
@given(st.lists(st.tuples(dates, st.sampled_from(["grantee", "non_grantee"]), st.sampled_from("ABC"), st.integers(0, 999)),
                min_size=0, max_size=8),
       st.one_of(st.none(), dates), st.one_of(st.none(), dates),
       st.one_of(st.none(), st.sampled_from(["grantee", "non_grantee"])))
def test_analytics_correct_and_aggregate_only(rows, d_from, d_to, category):
    """Property 14."""
    from app.scoring_adapter import gaps_from_recs, score_submission
    from app.store import SubmissionRecord
    records = []
    for day, cat, sample, salt in rows:
        rng = random.Random(salt)
        answers = {k: (v if rng.random() > 0.2 else ("no" if v == "yes" else "yes"))
                   for k, v in benchmark_answers(sample, SCOPE).items()}
        recs, _, display = score_submission(answers, SCOPE)
        ts = datetime(day.year, day.month, day.day, 12, tzinfo=timezone.utc)
        records.append(SubmissionRecord(
            submission_id=new_submission_id("Org %d" % salt, ts), timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            profile={"org_name": "Secret Org Name %d" % salt}, category=cat, in_scope_domains=SCOPE,
            answers=answers, scores=display, gaps=gaps_from_recs(recs)))
    f, t = (d_from.isoformat() if d_from else None), (d_to.isoformat() if d_to else None)
    out = aggregate(records, f, t, category)

    sel = [r for r in records if (not f or r.timestamp[:10] >= f) and (not t or r.timestamp[:10] <= t)
           and (not category or r.category == category)]
    assert out["total_submissions"] == len(sel)
    assert out["by_category"] == {"grantee": sum(r.category == "grantee" for r in sel),
                                  "non_grantee": sum(r.category == "non_grantee" for r in sel)}
    for d in out["domain_averages"]:
        pcts = [x["score_pct"] for r in sel for x in r.scores["domains"] if x["domain_id"] == d["domain_id"]]
        assert d["avg_capacity_pct"] == round(sum(pcts) / len(pcts), 1)
    counts = Counter(g["question_id"] for r in sel for g in r.gaps)
    for g in out["most_common_gaps"]:
        assert g["occurrences"] == counts[g["question_id"]]
    if out["most_common_gaps"]:
        assert out["most_common_gaps"][0]["occurrences"] == max(counts.values())
    assert "Secret Org Name" not in json.dumps(out)


def test_api_end_to_end(client_factory):
    client, store, llm = client_factory(seed=True)
    with client:
        q = client.get("/api/questions").json()
        assert q["in_scope_domains"] == SCOPE
        before = client.get("/api/analytics").json()["total_submissions"]
        assert before == 9
        body = client.post("/api/submit", json={"profile": {"org_name": "E2E Org", "website_url": "", "category": "non_grantee"},
                                                "answers": benchmark_answers("C", SCOPE)}).json()
        assert body["orchestration_status"] == "ok" and body["recommendations"]
        assert "answers" not in body
        assert client.get("/api/analytics").json()["total_submissions"] == 10
        assert client.get("/api/analytics", params={"category": "bogus"}).status_code == 422
        assert client.get("/api/report/not-a-real-id").status_code == 404
        assert client.get("/api/submissions/" + body["submission_id"]).json()["profile"]["org_name"] == "E2E Org"


def test_infra_template_static_scan():
    text = (ROOT / "infra" / "oci-stack.yaml").read_text()
    for flag in ("BlockPublicAcls", "IgnorePublicAcls", "BlockPublicPolicy", "RestrictPublicBuckets"):
        assert re.search(r"%s:\s*true" % flag, text), flag
    types = re.findall(r"^\s+Type:\s*(\S+)", text, re.M)
    assert types, "no resources found"
    for t in types:
        assert not re.match(r"AWS::(Cognito|RDS|ElasticLoadBalancing|ElasticLoadBalancingV2|WAF|WAFv2|WAFRegional|KMS|"
                            r"SecretsManager|Marketplace|MarketplaceCatalog)::", t), t
    assert set(types) <= {"AWS::S3::Bucket", "AWS::S3::BucketPolicy", "AWS::IAM::Role", "String"}, types
    assert not re.search(r"\b\d{12}\b", text), "no hardcoded account ids"
