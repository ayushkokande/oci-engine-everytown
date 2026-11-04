"""Sample organizations from the OCI package, and seeding the store with them.

The demo uses only the three synthetic sample organizations shipped in
``Everytown_OCI_Package/03_Sample_Responses``: Southside Youth Peace
Collective (A), Riverbend Violence Interruption Network (B) and Metro
Community Safety Alliance (C). Their profiles are in
``sample_data/organizations.json`` and their answers are the benchmark answer
sets in ``benchmark/``. No other synthetic data is generated.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from .config import API_ROOT
from .questions import in_scope_question_ids
from .scoring_adapter import gaps_from_recs, score_submission
from .store import SubmissionRecord, new_submission_id

BENCH = API_ROOT / "benchmark"
SAMPLE_ORGS_FILE = API_ROOT / "sample_data" / "organizations.json"

SAMPLE_ORGS: dict[str, dict] = {
    o["id"]: o for o in json.loads(SAMPLE_ORGS_FILE.read_text(encoding="utf-8"))["organizations"]
}
# Seeded at these offsets so date filters in the staff view have something to show.
_SEED_DAYS_AGO = {"A": 21, "B": 45, "C": 75}


def sample_org(sample_id: str | None) -> dict | None:
    return SAMPLE_ORGS.get((sample_id or "").upper()) if sample_id else None


def benchmark_answers(sample: str, in_scope: list[str]) -> dict:
    data = json.loads((BENCH / ("sample_%s_answers.json" % sample)).read_text())["answers"]
    return {qid: data[qid] for qid in in_scope_question_ids(in_scope) if qid in data}


def seed_records(in_scope: list[str], now: datetime | None = None) -> list[SubmissionRecord]:
    now = now or datetime.now(timezone.utc)
    records = []
    for sid, org in SAMPLE_ORGS.items():
        ts = (now - timedelta(days=_SEED_DAYS_AGO.get(sid, 30))).replace(microsecond=0)
        answers = benchmark_answers(sid, in_scope)
        recs, _summ, display = score_submission(answers, in_scope)
        records.append(SubmissionRecord(
            submission_id=new_submission_id(org["org_name"], ts),
            timestamp=ts.strftime("%Y-%m-%dT%H:%M:%SZ"),
            profile={"org_name": org["org_name"], "website_url": org["website_url"],
                     "category": org["category"], "sample_id": sid},
            category=org["category"],
            in_scope_domains=list(in_scope),
            answers=answers,
            scores=display,
            gaps=gaps_from_recs(recs),
            research_summary=org["description"],
            research_source="sample_profile",
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
