"""Organization-specific insights for CSF staff, computed by code.

Each insight links back to the feedback the organization received at the end of
the questionnaire through ``question_ids`` (the same ids as its recommendations),
so staff can open the exact narrative and next steps the organization saw.

Nothing here is model-generated, and no score, stage or band is changed: the
figures are counts and differences over stored engine output. Network figures
are aggregates across all stored assessments (this one included) and never name
another organization.
"""
from __future__ import annotations

from collections import Counter

from .stage_profile import network_stage_profile, stage_profile, stage_summary_line
from .store import SubmissionRecord

COMMON_SHARE = 50.0      # a gap at least this many % of assessments share
DISTINCT_SHARE = 25.0    # a gap at most this many % of assessments share


def network_summary(records: list[SubmissionRecord]) -> dict:
    """Aggregate figures the per-assessment view compares against."""
    n = len(records)
    pcts: dict[str, list[float]] = {}
    stages: dict[str, Counter] = {}
    gap_counter: Counter = Counter()
    profiles = []
    for r in records:
        for d in r.scores.get("domains", []):
            pcts.setdefault(d["domain_id"], []).append(d["score_pct"])
            stages.setdefault(d["domain_id"], Counter())[d["estimated_stage"]] += 1
        gap_counter.update({g["question_id"] for g in r.gaps})
        profiles.append(stage_profile(r.scores, r.gaps))
    return {
        "assessments": n,
        "avg_capacity_pct": {k: round(sum(v) / len(v), 1) for k, v in pcts.items()},
        "stage_counts": {k: dict(v) for k, v in stages.items()},
        "gap_share_pct": {q: round(100.0 * c / n, 1) for q, c in gap_counter.items()} if n else {},
        "stage_profile": network_stage_profile(profiles),
    }


def _recs_by_id(record: dict) -> dict[str, dict]:
    recs = record.get("recommendations") or record.get("gaps") or []
    return {r["question_id"]: r for r in recs}


def assessment_insights(record: dict, network: dict) -> list[dict]:
    """Insight cards for one assessment, most actionable first.

    Kinds: ``stage`` (what holds each area at its stage), ``relative`` (area capacity
    against the network average), ``common_gap`` (gaps most of the network shares: a
    cohort or group-training opportunity; High priority only), ``distinctive_gap`` (High-priority gaps few
    organizations share: worth a one-to-one conversation), ``context`` (what the
    organization added after reading its report).
    """
    profile = stage_profile(record.get("scores", {}), record.get("gaps", []))
    recs = _recs_by_id(record)
    gap_ids = [g["question_id"] for g in record.get("gaps", [])]
    share = network.get("gap_share_pct", {})
    avg = network.get("avg_capacity_pct", {})
    n = network.get("assessments", 0)
    out: list[dict] = []

    for p in profile:
        if p["blocking_gap_ids"]:
            out.append({
                "kind": "stage",
                "domain_id": p["domain_id"],
                "title": "%s: %s stage" % (p["domain_name"], p["estimated_stage"]),
                "detail": stage_summary_line(p),
                "question_ids": p["blocking_gap_ids"],
            })

    for d in record.get("scores", {}).get("domains", []):
        net = avg.get(d["domain_id"])
        if net is None or n < 2:
            continue
        delta = round(d["score_pct"] - net, 1)
        if abs(delta) < 10:
            continue
        direction = "above" if delta > 0 else "below"
        out.append({
            "kind": "relative",
            "domain_id": d["domain_id"],
            "title": "%s is %.0f points %s the network average" % (d["domain_name"], abs(delta), direction),
            "detail": "%.1f%% here against a %.1f%% average across %d assessments. %s" % (
                d["score_pct"], net, n,
                "A possible strength to share with peers." if delta > 0
                else "A likely focus area for support."),
            "question_ids": [q for q in gap_ids if recs.get(q, {}).get("domain_id") == d["domain_id"]
                             and recs.get(q, {}).get("priority") == "High"][:5],
        })

    if n >= 2:
        # Only High-priority gaps: where this org should start AND where peers could work together.
        common = sorted((q for q in gap_ids if share.get(q, 0) >= COMMON_SHARE
                         and recs.get(q, {}).get("priority") == "High"),
                        key=lambda q: (-share[q], q))
        if common:
            out.append({
                "kind": "common_gap",
                "domain_id": None,
                "title": "%d High-priority gap%s shared by most of the network" % (
                    len(common), "" if len(common) == 1 else "s"),
                "detail": "Each is a gap for at least %.0f%% of assessments, so group training or a "
                          "peer cohort may serve this organization and others at once." % COMMON_SHARE,
                "question_ids": common[:8],
            })
        distinct = [q for q in gap_ids if share.get(q, 100) <= DISTINCT_SHARE
                    and recs.get(q, {}).get("priority") == "High"]
        if distinct:
            out.append({
                "kind": "distinctive_gap",
                "domain_id": None,
                "title": "%d High-priority gap%s few organizations share" % (len(distinct), "" if len(distinct) == 1 else "s"),
                "detail": "At most %.0f%% of assessments share each of these, so they are worth a "
                          "one-to-one conversation rather than group support." % DISTINCT_SHARE,
                "question_ids": distinct[:8],
            })

    contexts = record.get("org_context") or []
    if contexts:
        out.append({
            "kind": "context",
            "domain_id": None,
            "title": "The organization added context %d time%s" % (len(contexts), "" if len(contexts) == 1 else "s"),
            "detail": " / ".join(c.get("text", "") for c in contexts)[:600],
            "question_ids": [],
        })
    return out
