"""Stage profile: one deterministic stage view shared by results, the PDF and staff analytics.

The engine's ``estimated_stage`` for an area is the highest stage reached with
*every* practice in place at that stage and all stages below it. That is strict:
one gap at Seeding keeps an area at Seeding even when most later practices are in
place, which makes "Seeding at 82% capacity" look contradictory. This module
explains the stage instead of changing it:

* how many practices are in place at each of the five stages,
* which gaps hold the area at its current stage (the incomplete stage just above it),
* how many practices are already in place beyond the current stage.

Everything here is computed from the engine's own output (the stored gaps) and the
question bank; no model is involved and the engine's stage is never altered. A
property test checks that the stage this profile implies always equals the
engine's ``estimated_stage``.
"""
from __future__ import annotations

from utils.data_loader import get_domains, get_stage_names

STAGE_NAMES = {int(num): name for num, name in get_stage_names().items()}
STAGE_NUMBERS = {name: num for num, name in STAGE_NAMES.items()}

STAGE_EXPLAINER = (
    "An area's stage is the highest stage at which every practice, at that stage and all "
    "stages below it, is in place. Practices already in place at later stages are shown "
    "separately, so a lower stage with a high capacity percentage means a few earlier "
    "practices are holding the area back."
)


def _domains_by_id() -> dict[str, dict]:
    return {d["id"]: d for d in get_domains()}


def implied_stage(stages: list[dict]) -> str:
    """Stage implied by a profile, using the engine's rule (stops at the first incomplete stage)."""
    reached = STAGE_NAMES.get(1, "Seeding")
    for s in stages:
        if s["total"] and s["in_place"] == s["total"]:
            reached = s["name"]
        else:
            break
    return reached


def stage_profile(scores: dict, gaps: list[dict]) -> list[dict]:
    """Per-area stage profile for one submission.

    ``scores`` is the engine display dict stored on the record and ``gaps`` the
    engine gaps; both come straight from the unchanged engine.
    """
    domains = _domains_by_id()
    gap_ids = {g["question_id"] for g in gaps}
    out = []
    for d in scores.get("domains", []):
        qs = domains.get(d["domain_id"], {}).get("questions", [])
        stages = []
        for num in sorted(STAGE_NAMES):
            stage_qs = [q for q in qs if q["stage"] == num]
            missing = [q["id"] for q in stage_qs if q["id"] in gap_ids]
            stages.append({
                "stage": num,
                "name": STAGE_NAMES[num],
                "total": len(stage_qs),
                "in_place": len(stage_qs) - len(missing),
                "gap_ids": missing,
            })
        current = d["estimated_stage"]
        current_num = STAGE_NUMBERS.get(current, 1)
        # The first stage that is not complete is what holds the area at `current`.
        blocking = next((s for s in stages if s["total"] and s["in_place"] < s["total"]), None)
        # Practices in place from the first incomplete stage upward: progress the stage hides.
        beyond = sum(s["in_place"] for s in stages if blocking and s["stage"] >= blocking["stage"])
        out.append({
            "domain_id": d["domain_id"],
            "domain_name": d["domain_name"],
            "estimated_stage": current,
            "stage_number": current_num,
            "score_pct": d["score_pct"],
            "stages": stages,
            "next_stage": blocking["name"] if blocking else None,
            "blocking_gap_ids": list(blocking["gap_ids"]) if blocking else [],
            "in_place_beyond_stage": beyond,
        })
        out[-1]["summary"] = stage_summary_line(out[-1])
    return out


def stage_summary_line(p: dict) -> str:
    """One plain sentence that reconciles the stage with the capacity percentage."""
    if not p["next_stage"]:
        return "Every practice in this area is in place."
    n = len(p["blocking_gap_ids"])
    line = "To move past %s, %d practice%s at the %s stage still need%s to be in place" % (
        p["estimated_stage"], n, "" if n == 1 else "s", p["next_stage"], "s" if n == 1 else "")
    b = p["in_place_beyond_stage"]
    if b:
        line += "; %d practice%s from that stage upward %s already in place" % (
            b, "" if b == 1 else "s", "is" if b == 1 else "are")
    return line + "."


def network_stage_profile(profiles: list[list[dict]]) -> dict[str, list[dict]]:
    """Average share of practices in place at each stage, per area, across submissions."""
    acc: dict[str, dict[int, list[float]]] = {}
    for prof in profiles:
        for p in prof:
            slot = acc.setdefault(p["domain_id"], {})
            for s in p["stages"]:
                if s["total"]:
                    slot.setdefault(s["stage"], []).append(100.0 * s["in_place"] / s["total"])
    return {
        did: [{"stage": num, "name": STAGE_NAMES[num],
               "avg_in_place_pct": round(sum(v) / len(v), 1) if v else 0.0}
              for num, v in sorted(slot.items())]
        for did, slot in acc.items()
    }
