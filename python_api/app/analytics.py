"""AnalyticsService: aggregate-only figures across stored submissions.

No output ever names an organization or compares one organization with
another; only counts, averages and frequencies are returned.
"""
from __future__ import annotations

from collections import Counter

from utils.data_loader import get_domains, get_stage_names

from .store import SubmissionRecord, month_prefixes

STAGE_ORDER = {name: int(num) for num, name in get_stage_names().items()}


def _in_range(ts: str, date_from: str | None, date_to: str | None) -> bool:
    day = ts[:10]
    if date_from and day < date_from[:10]:
        return False
    if date_to and day > date_to[:10]:
        return False
    return True


def filter_records(records: list[SubmissionRecord], date_from=None, date_to=None, category=None):
    return [r for r in records
            if _in_range(r.timestamp, date_from, date_to)
            and (not category or r.category == category)]


def aggregate(records: list[SubmissionRecord], date_from=None, date_to=None, category=None) -> dict:
    rows = filter_records(records, date_from, date_to, category)
    question_text = {q["id"]: (d["id"], d["name"], q["text"]) for d in get_domains() for q in d["questions"]}

    by_category = Counter(r.category for r in rows)
    per_domain: dict[str, dict] = {}
    gap_counter: Counter = Counter()
    for r in rows:
        for d in r.scores.get("domains", []):
            slot = per_domain.setdefault(d["domain_id"], {"name": d["domain_name"], "pcts": [], "stages": []})
            slot["pcts"].append(d["score_pct"])
            slot["stages"].append(d["estimated_stage"])
        gap_counter.update(g["question_id"] for g in r.gaps)

    domain_averages = []
    for did, slot in per_domain.items():
        stage_counts = Counter(slot["stages"])
        # modal stage; ties broken toward the earlier (less developed) stage
        modal = sorted(stage_counts.items(), key=lambda kv: (-kv[1], STAGE_ORDER.get(kv[0], 0)))[0][0]
        mean_stage_num = sum(STAGE_ORDER.get(s, 1) for s in slot["stages"]) / len(slot["stages"])
        domain_averages.append({
            "domain_id": did,
            "domain_name": slot["name"],
            "avg_capacity_pct": round(sum(slot["pcts"]) / len(slot["pcts"]), 1),
            "avg_stage": modal,
            "mean_stage_number": round(mean_stage_num, 2),
            "stage_distribution": {name: stage_counts.get(name, 0) for name in STAGE_ORDER},
            "submissions": len(slot["pcts"]),
        })

    most_common = []
    for qid, n in sorted(gap_counter.items(), key=lambda kv: (-kv[1], kv[0]))[:10]:
        did, dname, text = question_text.get(qid, ("", "", ""))
        most_common.append({"question_id": qid, "domain_id": did, "domain_name": dname,
                            "text": text, "occurrences": n,
                            "share_pct": round(100 * n / len(rows), 1) if rows else 0.0})

    return {
        "filters": {"from": date_from, "to": date_to, "category": category},
        "total_submissions": len(rows),
        "by_category": {"grantee": by_category.get("grantee", 0), "non_grantee": by_category.get("non_grantee", 0)},
        "domain_averages": domain_averages,
        "most_common_gaps": most_common,
    }


def load_for_analytics(store, date_from=None, date_to=None) -> list[SubmissionRecord]:
    return store.list_records(month_prefixes(date_from, date_to))
