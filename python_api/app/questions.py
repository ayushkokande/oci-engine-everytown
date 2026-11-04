"""QuestionService and CompletenessValidator.

Both read the vendored ``data/questions.json`` through the unchanged
``utils.data_loader`` so there is a single question bank.
"""
from __future__ import annotations

from utils.data_loader import get_domains


class DomainConfigError(ValueError):
    """Raised at startup when a configured in-scope domain id does not exist."""


def validate_domain_config(in_scope: list[str]) -> None:
    known = {d["id"] for d in get_domains()}
    unknown = [d for d in in_scope if d not in known]
    if not in_scope:
        raise DomainConfigError("OCI_IN_SCOPE_DOMAINS is empty")
    if unknown:
        raise DomainConfigError(
            "Unknown in-scope domain id(s) %s; valid ids are %s" % (unknown, sorted(known)))


def scoped_domains(in_scope: list[str]) -> list[dict]:
    """Domains from questions.json in the configured order."""
    by_id = {d["id"]: d for d in get_domains()}
    return [by_id[d] for d in in_scope if d in by_id]


def in_scope_question_ids(in_scope: list[str]) -> list[str]:
    return [q["id"] for d in scoped_domains(in_scope) for q in d["questions"]]


def questions_payload(in_scope: list[str]) -> dict:
    """Shape for ``GET /api/questions``. Polarity (``trigger_on``) is not sent:
    it lives entirely in scoring, so PL1 is an ordinary Yes/No question here."""
    return {
        "in_scope_domains": list(in_scope),
        "domains": [
            {
                "id": d["id"],
                "name": d["name"],
                "questions": [
                    {"id": q["id"], "text": q["text"], "stage": q["stage"], "options": ["yes", "no"]}
                    for q in d["questions"]
                ],
            }
            for d in scoped_domains(in_scope)
        ],
    }


def missing_answers(answers: dict, in_scope: list[str]) -> list[str]:
    """Ids of in-scope statements without a recorded "yes"/"no" answer.

    The engine treats an unanswered statement as favourable, so this check
    must pass before the engine is ever invoked.
    """
    missing = []
    for qid in in_scope_question_ids(in_scope):
        value = answers.get(qid)
        if not isinstance(value, str) or value.strip().lower() not in ("yes", "no"):
            missing.append(qid)
    return missing


def normalise_answers(answers: dict, in_scope: list[str]) -> dict:
    """Keep only in-scope ids, lower-cased. Call after ``missing_answers`` is empty."""
    return {qid: answers[qid].strip().lower() for qid in in_scope_question_ids(in_scope)}
