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
        assert before == 3
        body = client.post("/api/submit", json={"profile": {"org_name": "E2E Org", "website_url": "", "category": "non_grantee"},
                                                "answers": benchmark_answers("C", SCOPE)}).json()
        assert body["orchestration_status"] == "ok" and body["recommendations"]
        assert "answers" not in body
        assert client.get("/api/analytics").json()["total_submissions"] == 4
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


def test_seed_is_exactly_the_three_package_samples():
    from app.seed import SAMPLE_ORGS
    recs = seed_records(SCOPE)
    names = sorted(r.profile["org_name"] for r in recs)
    assert names == sorted(["Southside Youth Peace Collective", "Riverbend Violence Interruption Network",
                            "Metro Community Safety Alliance"])
    assert all(r.synthetic and r.research_source == "sample_profile" for r in recs)
    for r in recs:  # scores match the package's own answer sets
        sid = r.profile["sample_id"]
        assert r.answers == benchmark_answers(sid, SCOPE)
        assert r.research_summary == SAMPLE_ORGS[sid]["description"]


def test_sample_scores_match_package_expected_results():
    """Per-domain capacity, stage and gap counts for A/B/C equal the package's expected files."""
    from conftest import API
    from app.scoring_adapter import score_submission
    for sid in "ABC":
        expected = json.loads((API / "benchmark" / ("sample_%s_expected.json" % sid)).read_text())
        want = {d["domain_id"]: d for d in expected["domains"]}
        _, _, display = score_submission(benchmark_answers(sid, SCOPE), SCOPE)
        for d in display["domains"]:
            w = want[d["domain_id"]]
            assert (d["score_pct"], d["estimated_stage"], d["gap_count"]) == (
                w["capacity_pct"], w["estimated_stage"], w["gap_count"])


def test_sample_submission_uses_profile_instead_of_website(client_factory):
    from app.llm import MockClaude
    llm = MockClaude()
    client, _, _ = client_factory(llm=llm)
    with client:
        s = client.get("/api/samples").json()["samples"]
        assert [x["org_name"] for x in s] == ["Southside Youth Peace Collective",
                                             "Riverbend Violence Interruption Network",
                                             "Metro Community Safety Alliance"]
        a = client.get("/api/samples/a").json()
        body = client.post("/api/submit", json={"profile": {"org_name": a["org_name"], "website_url": a["website_url"],
                                                            "category": a["category"], "sample_id": "A"},
                                                "answers": a["answers"]}).json()
    assert body["research_source"] == "sample_profile"
    assert body["research_summary"] == a["description"]
    assert [c["kind"] for c in llm.calls] == ["recommend"]
    assert 'source="sample_profile"' in llm.calls[0]["prompt"] and a["description"] in llm.calls[0]["prompt"]
    pdf = _pdf_text(client.get("/api/report/" + body["submission_id"]).content)
    assert "sample profile from the OCI package" in pdf


def test_renamed_sample_is_treated_as_a_normal_org(client_factory):
    client, _, llm = client_factory()
    a = client.get("/api/samples/A").json()
    body = client.post("/api/submit", json={"profile": {"org_name": "Giggles", "website_url": "",
                                                        "category": "grantee", "sample_id": "A"},
                                            "answers": a["answers"]}).json()
    assert body["research_source"] is None and body["research_summary"] is None
    assert "sample_id" not in body["profile"]
    assert client.post("/api/submit", json={"profile": {"org_name": "X", "sample_id": "Z"},
                                            "answers": a["answers"]}).status_code == 422


def test_existing_store_gets_samples_and_hides_retired_seeds(client_factory, tmp_path):
    """A store seeded by an older build (generated variants, unlinked A/B/C) still demos cleanly."""
    from app.seed import ensure_samples, seed_records as new_seeds
    from app.store import LocalSubmissionStore, SubmissionRecord
    store = LocalSubmissionStore(tmp_path / "old")
    for name in ["Synthetic Variant 1", "Synthetic Variant 2", "Southside Youth Peace Collective"]:
        old = new_seeds(SCOPE)[0].to_dict()
        old["submission_id"] = new_submission_id(name)
        old["profile"] = {"org_name": name, "website_url": "", "category": "grantee"}  # no sample_id
        store.put(SubmissionRecord.from_dict(old))
    real = new_seeds(SCOPE)[1].to_dict()
    real.update(submission_id=new_submission_id("Bubbles"), synthetic=False,
                profile={"org_name": "Bubbles", "website_url": "", "category": "grantee"})
    store.put(SubmissionRecord.from_dict(real))

    assert ensure_samples(store, SCOPE) == 3
    assert ensure_samples(store, SCOPE) == 0          # idempotent
    client, _, _ = client_factory(store=store, seed=True)
    with client:
        names = sorted(r["org_name"] for r in client.get("/api/staff/assessments").json()["assessments"])
        assert names == sorted(["Bubbles", "Southside Youth Peace Collective",
                                "Riverbend Violence Interruption Network", "Metro Community Safety Alliance"])
        assert client.get("/api/analytics").json()["total_submissions"] == 4
