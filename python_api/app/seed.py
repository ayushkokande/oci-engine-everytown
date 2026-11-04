"""Seed the store with synthetic submissions so staff analytics has data on first run.

Seeds are the three public benchmark samples (A, B, C) plus deterministic
variants made by flipping a fixed fraction of answers. All synthetic, no PII.
They are scored by the same unchanged engine as live submissions.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta, timezone

from .config import API_ROOT
from .questions import in_scope_question_ids
from .scoring_adapter import gaps_from_recs, score_submission
from .store import SubmissionRecord, new_submission_id

BENCH = API_ROOT / "benchmark"

SAMPLES = {
    "A": ("Southside Youth Peace Collective", "grantee"),
    "B": ("Riverbend Violence Interruption Network", "grantee"),
    "C": ("Metro Community Safety Alliance", "non_grantee"),
}


def benchmark_answers(sample: str, in_scope: list[str]) -> dict:
    data = json.loads((BENCH / ("sample_%s_answers.json" % sample)).read_text())["answers"]
    return {qid: data[qid] for qid in in_scope_question_ids(in_scope) if qid in data}


def _variant(answers: dict, rng: random.Random, flip: float, toward: str | None) -> dict:
    out = dict(answers)
    for qid in sorted(out):
        if rng.random() < flip:
            out[qid] = toward or ("no" if out[qid] == "yes" else "yes")
    return out


def seed_records(in_scope: list[str], now: datetime | None = None) -> list[SubmissionRecord]:
    now = now or datetime.now(timezone.utc)
    rng = random.Random(20261104)
    plan = []
    for i, (s, (name, cat)) in enumerate(SAMPLES.items()):
        plan.append((name, cat, benchmark_answers(s, in_scope), 150 - 40 * i))
    base = [p[2] for p in plan]
    variants = [
        ("Synthetic Variant 1", "grantee", _variant(base[0], rng, 0.25, "yes"), 75),
        ("Synthetic Variant 2", "non_grantee", _variant(base[1], rng, 0.20, None), 60),
        ("Synthetic Variant 3", "grantee", _variant(base[1], rng, 0.30, "yes"), 45),
        ("Synthetic Variant 4", "non_grantee", _variant(base[0], rng, 0.15, None), 30),
        ("Synthetic Variant 5", "grantee", _variant(base[2], rng, 0.20, "no"), 20),
        ("Synthetic Variant 6", "non_grantee", _variant(base[2], rng, 0.10, None), 9),
    ]
    records = []
    for name, cat, answers, days_ago in plan + variants:
        ts = (now - timedelta(days=days_ago)).replace(microsecond=0)
        recs, _summ, display = score_submission(answers, in_scope)
        records.append(SubmissionRecord(
            submission_id=new_submission_id(name, ts),
            timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            profile={"org_name": name, "website_url": "", "category": cat},
            category=cat,
            in_scope_domains=list(in_scope),
            answers=answers,
            scores=display,
            gaps=gaps_from_recs(recs),
            orchestration_status="seed",
            synthetic=True,
        ))
    return records


def seed_if_empty(store, in_scope: list[str]) -> int:
    if not store.is_empty():
        return 0
    records = seed_records(in_scope)
    for r in records:
        store.put(r)
    return len(records)
