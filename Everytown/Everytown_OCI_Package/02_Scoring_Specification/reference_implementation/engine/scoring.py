"""Priority scoring algorithm for OCI recommendations."""
from dataclasses import dataclass


@dataclass
class ScoredRecommendation:
    question_id: str
    domain_id: str
    domain_name: str
    stage: int
    stage_name: str
    question_text: str
    next_steps: list
    score: float
    priority: str  # High, Medium, Low


@dataclass
class DomainSummary:
    domain_id: str
    domain_name: str
    total_questions: int
    favorable_count: int
    gap_count: int
    score_pct: float
    estimated_stage: str
    recommendations: list  # list of ScoredRecommendation


def calculate_recommendations(answers: dict, domains: list, stage_weights: dict, stage_names: dict):
    """
    Calculate scored recommendations from survey answers.

    Args:
        answers: dict of question_id -> "yes" or "no"
        domains: list of domain dicts from questions.json
        stage_weights: dict of stage_num_str -> weight
        stage_names: dict of stage_num_str -> name

    Returns:
        (all_recommendations: list[ScoredRecommendation], domain_summaries: list[DomainSummary])
    """
    all_recs = []

    # First pass: identify gaps per domain for density calculation
    domain_gaps = {}
    domain_totals = {}
    for domain in domains:
        did = domain["id"]
        gaps = 0
        total = len(domain["questions"])
        for q in domain["questions"]:
            answer = answers.get(q["id"], "").lower()
            if _is_gap(answer, q["trigger_on"]):
                gaps += 1
        domain_gaps[did] = gaps
        domain_totals[did] = total

    # Second pass: score each gap
    for domain in domains:
        did = domain["id"]
        d_weight = domain.get("weight", 1.0)
        gap_density_bonus = 1.0 + (domain_gaps[did] / max(domain_totals[did], 1))

        for q in domain["questions"]:
            answer = answers.get(q["id"], "").lower()
            if not _is_gap(answer, q["trigger_on"]):
                continue

            s_weight = stage_weights.get(str(q["stage"]), 1)
            score = s_weight * d_weight * gap_density_bonus

            all_recs.append(ScoredRecommendation(
                question_id=q["id"],
                domain_id=did,
                domain_name=domain["name"],
                stage=q["stage"],
                stage_name=stage_names.get(str(q["stage"]), "Unknown"),
                question_text=q["text"],
                next_steps=q["next_steps"],
                score=round(score, 2),
                priority="",  # assigned below
            ))

    # Assign priority labels by percentile
    if all_recs:
        all_recs.sort(key=lambda r: r.score, reverse=True)
        n = len(all_recs)
        for i, rec in enumerate(all_recs):
            pct = i / n
            if pct < 0.33:
                rec.priority = "High"
            elif pct < 0.66:
                rec.priority = "Medium"
            else:
                rec.priority = "Low"

    # Build domain summaries
    domain_summaries = []
    for domain in domains:
        did = domain["id"]
        total = domain_totals[did]
        gaps = domain_gaps[did]
        favorable = total - gaps
        score_pct = round((favorable / max(total, 1)) * 100, 1)

        # Estimated stage: highest stage where all questions are favorable
        estimated_stage = "Seeding"
        for stage_num in range(1, 6):
            stage_qs = [q for q in domain["questions"] if q["stage"] == stage_num]
            all_favorable = all(
                not _is_gap(answers.get(q["id"], "").lower(), q["trigger_on"])
                for q in stage_qs
            )
            if all_favorable and stage_qs:
                estimated_stage = stage_names.get(str(stage_num), "Unknown")
            else:
                break

        domain_recs = [r for r in all_recs if r.domain_id == did]
        domain_recs.sort(key=lambda r: r.score, reverse=True)

        domain_summaries.append(DomainSummary(
            domain_id=did,
            domain_name=domain["name"],
            total_questions=total,
            favorable_count=favorable,
            gap_count=gaps,
            score_pct=score_pct,
            estimated_stage=estimated_stage,
            recommendations=domain_recs,
        ))

    return all_recs, domain_summaries


def _is_gap(answer: str, trigger_on: str) -> bool:
    """Check if the answer triggers a recommendation."""
    return answer == trigger_on
