"""Format recommendations for display and reports."""


def format_for_display(all_recs, domain_summaries):
    """
    Format recommendations into a structure suitable for Streamlit display.

    Returns a dict with:
        - overall_stats: dict with total_gaps, domains_assessed, etc.
        - domains: list of domain result dicts
    """
    total_gaps = sum(ds.gap_count for ds in domain_summaries)
    total_questions = sum(ds.total_questions for ds in domain_summaries)
    high_count = sum(1 for r in all_recs if r.priority == "High")
    medium_count = sum(1 for r in all_recs if r.priority == "Medium")
    low_count = sum(1 for r in all_recs if r.priority == "Low")

    domain_results = []
    for ds in domain_summaries:
        domain_results.append({
            "domain_id": ds.domain_id,
            "domain_name": ds.domain_name,
            "score_pct": ds.score_pct,
            "estimated_stage": ds.estimated_stage,
            "gap_count": ds.gap_count,
            "total_questions": ds.total_questions,
            "recommendations": [
                {
                    "question_id": r.question_id,
                    "question_text": r.question_text,
                    "stage_name": r.stage_name,
                    "priority": r.priority,
                    "score": r.score,
                    "next_steps": r.next_steps,
                }
                for r in ds.recommendations
            ],
        })

    return {
        "overall_stats": {
            "total_questions": total_questions,
            "total_gaps": total_gaps,
            "high_priority": high_count,
            "medium_priority": medium_count,
            "low_priority": low_count,
        },
        "domains": domain_results,
    }
