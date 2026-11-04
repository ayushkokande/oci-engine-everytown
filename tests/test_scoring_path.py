"""Deterministic path: questionnaire scope, completeness, engine fidelity (Properties 3-9)."""
import hashlib
import subprocess
import sys
from unittest import mock

from hypothesis import HealthCheck, given, settings, strategies as st

from conftest import API
from app import questions as qmod
from app.scoring_adapter import score_submission
from utils.data_loader import get_domains

ALL_IDS = [d["id"] for d in get_domains()]
QUESTIONS = {q["id"]: q for d in get_domains() for q in d["questions"]}
scopes = st.lists(st.sampled_from(ALL_IDS), min_size=1, max_size=8, unique=True)


def test_engine_files_unchanged():
    """Benchmark guard: vendored engine must match the recorded checksums byte for byte."""
    for line in (API / "ENGINE_CHECKSUMS.sha256").read_text().splitlines():
        digest, rel = line.split(maxsplit=1)
        assert hashlib.sha256((API / rel).read_bytes()).hexdigest() == digest, rel


def test_verify_benchmark_passes():
    """Property 9: samples A, B, C all PASS against the vendored engine."""
    out = subprocess.run([sys.executable, "verify_benchmark.py"], cwd=API, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert out.stdout.count("PASS") == 3


def test_default_scope_is_72_statements(in_scope):
    assert len(qmod.in_scope_question_ids(in_scope)) == 72


@settings(max_examples=100)
@given(scopes)
def test_questionnaire_matches_configured_domains(scope):
    """Property 3."""
    payload = qmod.questions_payload(scope)
    shown = [q["id"] for d in payload["domains"] for q in d["questions"]]
    expected = [q["id"] for d in get_domains() if d["id"] in scope for q in d["questions"]]
    assert sorted(shown) == sorted(expected)
    assert all(q["options"] == ["yes", "no"] for d in payload["domains"] for q in d["questions"])


answer_values = st.sampled_from(["yes", "no", "YES", " No ", "", "maybe", None, 1])


@settings(max_examples=150)
@given(scopes, st.data())
def test_completeness_is_exact(scope, data):
    """Property 4."""
    ids = qmod.in_scope_question_ids(scope)
    answers = {}
    for qid in ids:
        if data.draw(st.booleans()):
            answers[qid] = data.draw(answer_values)
    truly_missing = [q for q in ids if not (isinstance(answers.get(q), str)
                                            and answers[q].strip().lower() in ("yes", "no"))]
    assert qmod.missing_answers(answers, scope) == truly_missing


@settings(max_examples=60, deadline=None, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.data())
def test_scoring_withheld_until_complete(client_factory, data):
    """Property 5: the engine is never invoked for an incomplete submission."""
    client, _, _ = client_factory()
    ids = qmod.in_scope_question_ids(["PL", "FR", "FM", "ML"])
    drop = data.draw(st.lists(st.sampled_from(ids), min_size=1, unique=True))
    answers = {q: "yes" for q in ids if q not in drop}
    with mock.patch("app.main.score_submission") as spy:
        r = client.post("/api/submit", json={"profile": {"org_name": "X", "website_url": "", "category": "grantee"},
                                             "answers": answers})
    assert r.status_code == 422
    assert r.json()["missing_count"] == len(drop)
    assert sorted(r.json()["missing_ids"]) == sorted(drop)
    spy.assert_not_called()


def _random_answers(scope, data):
    return {q: data.draw(st.sampled_from(["yes", "no"])) for q in qmod.in_scope_question_ids(scope)}


@settings(max_examples=100)
@given(scopes, st.data())
def test_priority_bands_are_relative_thirds(scope, data):
    """Property 7, checked against an independent recomputation of the documented rule."""
    answers = _random_answers(scope, data)
    recs, _, _ = score_submission(answers, scope)
    n = len(recs)
    scores = [r.score for r in recs]
    assert scores == sorted(scores, reverse=True)
    for i, r in enumerate(recs):
        pct = i / n
        assert r.priority == ("High" if pct < 0.33 else "Medium" if pct < 0.66 else "Low")


@settings(max_examples=100)
@given(st.data())
def test_pl1_reverse_coded(data):
    """Property 8."""
    scope = ["PL", "FR"]
    answers = _random_answers(scope, data)
    recs, _, _ = score_submission(answers, scope)
    gap_ids = {r.question_id for r in recs}
    assert ("PL1" in gap_ids) == (answers["PL1"] == "yes")
    for qid, a in answers.items():
        if qid != "PL1":
            assert (qid in gap_ids) == (a == "no")


def test_bad_domain_config_fails_fast():
    import pytest
    with pytest.raises(qmod.DomainConfigError):
        qmod.validate_domain_config(["PL", "XX"])
