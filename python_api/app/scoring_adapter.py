"""Thin wrapper around the unchanged Scoring_Engine.

Scoping is applied only by choosing which domains are passed in; no scoring
logic lives here.
"""
from __future__ import annotations

from engine.recommendations import format_for_display
from engine.scoring import calculate_recommendations
from utils.data_loader import get_stage_names, get_stage_weights

from .questions import scoped_domains

BAND_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def score_submission(answers: dict, in_scope_domain_ids: list[str]):
    """Returns (all_recs, summaries, display) straight from the engine."""
    all_recs, summaries = calculate_recommendations(
        answers, scoped_domains(in_scope_domain_ids), get_stage_weights(), get_stage_names())
    return all_recs, summaries, format_for_display(all_recs, summaries)


def gaps_from_recs(all_recs) -> list[dict]:
    """Every gap the engine found, in engine order (score descending)."""
    return [
        {
            "question_id": r.question_id,
            "domain_id": r.domain_id,
            "domain_name": r.domain_name,
            "stage": r.stage,
            "stage_name": r.stage_name,
            "text": r.question_text,
            "next_steps": list(r.next_steps),
            "priority_score": r.score,
            "priority": r.priority,
        }
        for r in all_recs
    ]
