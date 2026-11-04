"""FastAPI entry point.

    uvicorn app.main:app --reload --port 8000     (run from python_api/)

Request flow for POST /api/submit:
    validate completeness -> score (unchanged engine) -> research call ->
    recommendation call -> persist -> respond
Scores are captured before any model call, so no model outcome can change or
lose them.
"""
from __future__ import annotations

import copy
import logging
import threading
from collections import OrderedDict
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

from fastapi import BackgroundTasks, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .analytics import aggregate, filter_records, load_for_analytics
from .assistant_chat import feedback_chat, staff_chat
from .config import Settings, load_settings
from .insights import assessment_insights, network_summary
from .llm import LLMClient, ModelError, build_llm
from .orchestrator import merge_recommendations, orchestrate
from .pdf_report import render_pdf
from .question_chat import explain_question
from .questions import missing_answers, normalise_answers, questions_payload, validate_domain_config
from .resources import load_library
from .scoring_adapter import gaps_from_recs, score_submission
from .seed import SAMPLE_ORGS, benchmark_answers, sample_org, seed_if_empty
from .stage_profile import STAGE_EXPLAINER, stage_profile
from .store import SubmissionRecord, SubmissionStore, build_store, new_submission_id

log = logging.getLogger("oci")

CATEGORIES = ("grantee", "non_grantee")


class Profile(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    website_url: str = Field(default="", max_length=500)
    category: str = "grantee"
    sample_id: str | None = Field(default=None, max_length=4)


class SubmitRequest(BaseModel):
    profile: Profile
    answers: dict[str, str] = Field(default_factory=dict)


class QuestionChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=4000)


class QuestionChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[QuestionChatMessage] = Field(min_length=1, max_length=11)


class AssessmentChatRequest(BaseModel):
    """Feedback-refinement and staff chats: longer than the per-question chat."""
    model_config = ConfigDict(extra="forbid")

    messages: list[QuestionChatMessage] = Field(min_length=1, max_length=21)


class ReviseRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    # The organization's own words. Empty = re-run with the context already saved (a retry).
    context: str = Field(default="", max_length=3000)


MAX_CONTEXT_ENTRIES = 20
MAX_KEPT_REVISIONS = 5


def check_transcript(messages: list[dict], *, max_user_chars: int, max_total_chars: int) -> None:
    """Shared rules for every chat: alternate roles, start and end with the user, bounded size."""
    for index, message in enumerate(messages):
        expected_role = "user" if index % 2 == 0 else "assistant"
        if message["role"] != expected_role:
            raise HTTPException(422, "chat messages must alternate user and assistant roles")
        if message["role"] == "user" and len(message["content"]) > max_user_chars:
            raise HTTPException(422, "user messages must be %d characters or fewer" % max_user_chars)
    if messages[-1]["role"] != "user":
        raise HTTPException(422, "the final chat message must be from the user")
    if sum(len(message["content"]) for message in messages) > max_total_chars:
        raise HTTPException(422, "chat history is too long")


def _clip_reply(reply: str) -> str:
    reply = reply.strip()
    if not reply:
        raise HTTPException(502, "The model returned an empty reply. Please try again.")
    return reply if len(reply) <= 6000 else reply[:5997].rstrip() + "..."


def public_view(data: dict) -> dict:
    """A stored record as the API returns it: no raw answers, plus the shared stage profile."""
    data = dict(data)
    data.pop("answers", None)
    data["stage_profile"] = stage_profile(data.get("scores", {}), data.get("gaps", []))
    data["stage_rule"] = STAGE_EXPLAINER
    return data


def create_app(settings: Settings | None = None, store: SubmissionStore | None = None,
               llm: LLMClient | None = None) -> FastAPI:
    settings = settings or load_settings()
    validate_domain_config(settings.in_scope_domains)  # fail fast on bad config
    store = store or build_store(settings)
    llm = llm or build_llm(settings)
    library = load_library()
    questionnaire = questions_payload(settings.in_scope_domains)
    question_index = {
        question["id"]: {
            **question,
            "domain_id": domain["id"],
            "domain_name": domain["name"],
        }
        for domain in questionnaire["domains"]
        for question in domain["questions"]
    }
    recent: "OrderedDict[str, dict]" = OrderedDict()  # last results, in case a store write fails
    recent_lock = threading.Lock()  # background narration threads write to `recent`
    revising: set[str] = set()  # submission ids with a revision in flight in this process

    @asynccontextmanager
    async def lifespan(_app):
        if settings.seed_on_startup:
            try:
                n = seed_if_empty(store, settings.in_scope_domains)
                if n:
                    log.info("seeded %d synthetic submissions", n)
            except Exception:  # analytics just starts empty
                log.exception("seeding failed")
        yield

    app = FastAPI(title="Everytown OCI API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                       allow_methods=["GET", "POST"], allow_headers=["*"])

    @app.get("/api/health")
    def health():
        return {"status": "ok"}

    @app.get("/api/config")
    def config():
        return {"in_scope_domains": settings.in_scope_domains, "llm_mode": settings.llm_mode,
                "model_id": settings.bedrock_model_id if settings.llm_mode == "bedrock" else None,
                "store": settings.store_backend, "region": settings.aws_region,
                "resource_count": len(library)}

    @app.get("/api/questions")
    def questions():
        return questionnaire

    @app.post("/api/questions/{question_id}/chat")
    def question_chat(question_id: str, req: QuestionChatRequest):
        question = question_index.get(question_id)
        if question is None:
            raise HTTPException(404, "unknown or out-of-scope question")

        messages = [message.model_dump() for message in req.messages]
        check_transcript(messages, max_user_chars=1000, max_total_chars=12000)

        try:
            reply = explain_question(
                llm,
                question,
                messages,
                max_tokens=settings.question_chat_max_tokens,
            ).strip()
        except ModelError as error:
            log.warning("question chat model failure for %s: %s", question_id, error.code)
            raise HTTPException(503, "Question explanation is temporarily unavailable. Please try again.")
        if not reply:
            raise HTTPException(502, "The model returned an empty explanation. Please try again.")
        if len(reply) > 4000:
            reply = reply[:3997].rstrip() + "..."
        return {"question_id": question_id, "reply": reply}

    @app.get("/api/resources")
    def resources():
        return {"resources": [{"id": r.id, "title": r.title, "domains": list(r.domains), "source": r.source}
                              for r in library]}

    def _sample_public(org: dict) -> dict:
        return {k: org[k] for k in ("id", "org_name", "category", "website_url", "profile_line",
                                    "description", "source")}

    @app.get("/api/samples")
    def samples():
        """The three synthetic sample organizations shipped with the OCI package."""
        return {"samples": [_sample_public(o) for o in SAMPLE_ORGS.values()]}

    @app.get("/api/samples/{sample}")
    def sample(sample: str):
        """One sample organization with its answers for the in-scope domains."""
        org = sample_org(sample)
        if org is None:
            raise HTTPException(404, "unknown sample")
        return dict(_sample_public(org), sample=org["id"],
                    answers=benchmark_answers(org["id"], settings.in_scope_domains))

    def _narrate(record: SubmissionRecord, profile: dict, display: dict, gaps: list) -> None:
        """Run the Bedrock pipeline and attach its narrative to the record. Scores are untouched."""
        org = sample_org(profile.get("sample_id"))
        try:
            result = orchestrate(llm, profile, display, gaps, library,
                                 max_tokens=settings.bedrock_max_tokens,
                                 fetch_timeout=settings.research_fetch_timeout_s,
                                 skip_fetch=settings.llm_mode == "mock",
                                 research_override=org["description"] if org else None)
        except Exception as e:  # never let orchestration take the scores down with it
            log.exception("orchestration crashed")
            from .orchestrator import OrchestrationResult
            result = OrchestrationResult(status="error", error="orchestration_failed:%s" % type(e).__name__)

        record.research_summary = result.research_summary
        record.research_source = result.research_source
        record.overview = result.overview
        record.action_plan = result.action_plan
        record.orchestration_status = result.status
        record.orchestration_error = result.error
        record.recommendations = (merge_recommendations(gaps, result.narratives)
                                  if result.status == "ok" else [])
        record.domain_analysis = result.domain_analysis if result.status == "ok" else {}

    def _revise(record: SubmissionRecord) -> None:
        """Regenerate the narrative with the organization's added context.

        Scores, stages, gaps and bands are read from the record and never written. On
        failure the previous narrative stays in place and the snapshot taken for it is dropped.
        """
        try:
            result = orchestrate(llm, record.profile, record.scores, record.gaps, library,
                                 max_tokens=settings.bedrock_max_tokens,
                                 org_context=[c["text"] for c in record.org_context],
                                 reuse_research=True, research=record.research_summary,
                                 research_source=record.research_source)
        except Exception as e:
            log.exception("revision crashed")
            from .orchestrator import OrchestrationResult
            result = OrchestrationResult(status="error", error="revision_failed:%s" % type(e).__name__)
        if result.status != "ok":
            record.revision_status, record.revision_error = "error", result.error
            if record.revisions:
                record.revisions.pop()
            return
        record.overview = result.overview
        record.action_plan = result.action_plan
        record.recommendations = merge_recommendations(record.gaps, result.narratives)
        record.domain_analysis = result.domain_analysis
        record.orchestration_status, record.orchestration_error = "ok", None
        record.revision_status, record.revision_error = "ok", None
        record.revision_count += 1

    def _revise_and_save(record: SubmissionRecord) -> None:
        try:
            _revise(record)
            _save(record)
        finally:
            with recent_lock:
                revising.discard(record.submission_id)

    def _save(record: SubmissionRecord) -> bool:
        """Persist the record and keep an in-memory copy in case the store write fails."""
        persisted = True
        try:
            store.put(record)
        except Exception:
            log.exception("store write failed for %s", record.submission_id)
            persisted = False
        with recent_lock:
            recent[record.submission_id] = record.to_dict()
            recent.move_to_end(record.submission_id)
            while len(recent) > 50:
                recent.popitem(last=False)
        return persisted

    def _narrate_and_save(record: SubmissionRecord, profile: dict, display: dict, gaps: list) -> None:
        _narrate(record, profile, display, gaps)
        _save(record)

    @app.post("/api/submit")
    def submit(req: SubmitRequest, background: BackgroundTasks):
        profile = req.profile.model_dump()
        profile["org_name"] = profile["org_name"].strip()
        profile["website_url"] = profile["website_url"].strip()
        if not profile["org_name"]:
            raise HTTPException(422, "org_name is required")
        if profile["category"] not in CATEGORIES:
            raise HTTPException(422, "category must be one of %s" % (CATEGORIES,))
        org = sample_org(profile.get("sample_id"))
        if profile.get("sample_id") and org is None:
            raise HTTPException(422, "unknown sample_id")
        if org is not None and profile["org_name"] != org["org_name"]:
            org = None  # renamed after picking a sample: treat as a normal organization
        if org is None:
            profile.pop("sample_id", None)
        else:
            profile["sample_id"] = org["id"]

        missing = missing_answers(req.answers, settings.in_scope_domains)
        if missing:  # engine is never invoked for an incomplete submission
            return JSONResponse(status_code=422, content={
                "error": "incomplete_submission", "missing_count": len(missing), "missing_ids": missing})

        answers = normalise_answers(req.answers, settings.in_scope_domains)
        all_recs, _summaries, display = score_submission(answers, settings.in_scope_domains)
        gaps = gaps_from_recs(all_recs)
        now = datetime.now(timezone.utc).replace(microsecond=0)
        record = SubmissionRecord(
            submission_id=new_submission_id(profile["org_name"], now),
            timestamp=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            profile=profile, category=profile["category"],
            in_scope_domains=list(settings.in_scope_domains),
            answers=answers, scores=display, gaps=gaps)

        if settings.async_orchestration:
            # Save the scores now and answer at once (status "pending"); the narrative is
            # added in the background and the client polls GET /api/submissions/{id}.
            persisted = _save(record)
            background.add_task(_narrate_and_save, record, profile, display, gaps)
            body = public_view(record.to_dict())
            body["persisted"] = persisted
            return JSONResponse(status_code=202, content=body)

        _narrate(record, profile, display, gaps)
        persisted = _save(record)
        body = public_view(record.to_dict())
        body["persisted"] = persisted
        return body

    def _load(submission_id: str) -> dict:
        with recent_lock:
            cached = recent.get(submission_id)
        if cached is not None:  # this process's copy is never older than the stored one
            return copy.deepcopy(cached)
        try:
            rec = store.get(submission_id)
        except ValueError:
            raise HTTPException(404, "submission not found")
        except Exception:
            rec = None
        if rec is not None:
            return rec.to_dict()
        raise HTTPException(404, "submission not found")

    @app.get("/api/submissions/{submission_id}")
    def get_submission(submission_id: str):
        return public_view(_load(submission_id))

    @app.post("/api/submissions/{submission_id}/feedback-chat")
    def submission_feedback_chat(submission_id: str, req: AssessmentChatRequest):
        """The organization asks about its feedback and adds context in its own words."""
        data = _load(submission_id)
        messages = [m.model_dump() for m in req.messages]
        check_transcript(messages, max_user_chars=1500, max_total_chars=20000)
        try:
            reply = feedback_chat(llm, data, messages, max_tokens=settings.assessment_chat_max_tokens)
        except ModelError as error:
            log.warning("feedback chat model failure for %s: %s", submission_id, error.code)
            raise HTTPException(503, "The feedback assistant is temporarily unavailable. Please try again.")
        return {"submission_id": submission_id, "reply": _clip_reply(reply)}

    @app.post("/api/submissions/{submission_id}/revise")
    def revise_submission(submission_id: str, req: ReviseRequest, background: BackgroundTasks):
        """Regenerate the narrative with the organization's added context. Scores never change."""
        record = SubmissionRecord.from_dict(_load(submission_id))
        if record.orchestration_status == "pending":
            raise HTTPException(409, "The first report is still being prepared. Try again in a minute.")
        with recent_lock:
            if submission_id in revising:
                raise HTTPException(409, "An update is already in progress.")
            revising.add(submission_id)
        try:
            if req.context:
                if len(record.org_context) >= MAX_CONTEXT_ENTRIES:
                    raise HTTPException(422, "This report already has the maximum amount of added context.")
                stamp = datetime.now(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")
                record.org_context.append({"text": req.context, "timestamp": stamp})
            elif not record.org_context:
                raise HTTPException(422, "Add some context before updating your feedback.")
            if record.orchestration_status == "ok":
                record.revisions.append({
                    "revision": record.revision_count, "overview": record.overview,
                    "action_plan": record.action_plan, "recommendations": record.recommendations,
                    "domain_analysis": record.domain_analysis,
                    "context_entries": len(record.org_context) - (1 if req.context else 0)})
                record.revisions = record.revisions[-MAX_KEPT_REVISIONS:]
            record.revision_status, record.revision_error = "pending", None
        except HTTPException:
            with recent_lock:
                revising.discard(submission_id)
            raise

        if settings.async_orchestration:
            persisted = _save(record)
            background.add_task(_revise_and_save, record)
            body = public_view(record.to_dict())
            body["persisted"] = persisted
            return JSONResponse(status_code=202, content=body)

        _revise_and_save(record)
        with recent_lock:
            body = public_view(copy.deepcopy(recent[submission_id]))
        return body

    @app.get("/api/report/{submission_id}")
    def report(submission_id: str, inline: bool = False):
        data = _load(submission_id)
        pdf = render_pdf(data, library)
        slug = submission_id.split("_")[1] if "_" in submission_id else "report"
        disposition = "inline" if inline else "attachment"
        return Response(pdf, media_type="application/pdf", headers={
            "Content-Disposition": '%s; filename="OCI_Report_%s.pdf"' % (disposition, slug)})

    # ------------------------------------------------------------------ staff: per assessment
    # Staff-only views of individual assessments (named). Other organizations never see them.
    # Login is mocked in the front end for the MVP; real access control is still to be decided.

    def _all_records() -> list[SubmissionRecord]:
        by_id = {r.submission_id: r for r in store.list_records()}
        with recent_lock:  # this process's copy is never older than the stored one
            for sid, data in recent.items():
                by_id[sid] = SubmissionRecord.from_dict(copy.deepcopy(data))
        return list(by_id.values())

    def _network_for(data: dict) -> tuple[dict, list[dict]]:
        network = network_summary(_all_records())
        return network, assessment_insights(data, network)

    @app.get("/api/staff/assessments")
    def staff_assessments(date_from: str | None = Query(None, alias="from"),
                          date_to: str | None = Query(None, alias="to"),
                          category: str | None = None):
        if category and category not in CATEGORIES:
            raise HTTPException(422, "category must be one of %s" % (CATEGORIES,))
        rows = filter_records(_all_records(), date_from, date_to, category)
        rows.sort(key=lambda r: r.timestamp, reverse=True)
        return {"assessments": [{
            "submission_id": r.submission_id,
            "timestamp": r.timestamp,
            "org_name": r.profile.get("org_name", ""),
            "category": r.category,
            "synthetic": r.synthetic,
            "orchestration_status": r.orchestration_status,
            "overall_stats": r.scores.get("overall_stats", {}),
            "domains": [{k: d[k] for k in ("domain_id", "domain_name", "score_pct", "estimated_stage")}
                        for d in r.scores.get("domains", [])],
            "context_count": len(r.org_context),
            "revision_count": r.revision_count,
        } for r in rows]}

    @app.get("/api/staff/assessments/{submission_id}")
    def staff_assessment(submission_id: str):
        data = _load(submission_id)
        network, insights = _network_for(data)
        own_gaps = {g["question_id"] for g in data.get("gaps", [])}
        body = public_view(data)
        body["insights"] = insights
        body["network"] = {
            "assessments": network["assessments"],
            "avg_capacity_pct": network["avg_capacity_pct"],
            "stage_counts": network["stage_counts"],
            "stage_profile": network["stage_profile"],
            "gap_share_pct": {q: v for q, v in network["gap_share_pct"].items() if q in own_gaps},
        }
        return body

    @app.post("/api/staff/assessments/{submission_id}/chat")
    def staff_assessment_chat(submission_id: str, req: AssessmentChatRequest):
        data = _load(submission_id)
        messages = [m.model_dump() for m in req.messages]
        check_transcript(messages, max_user_chars=1500, max_total_chars=20000)
        network, insights = _network_for(data)
        try:
            reply = staff_chat(llm, data, messages, network, insights,
                               max_tokens=settings.assessment_chat_max_tokens)
        except ModelError as error:
            log.warning("staff chat model failure for %s: %s", submission_id, error.code)
            raise HTTPException(503, "The assessment assistant is temporarily unavailable. Please try again.")
        return {"submission_id": submission_id, "reply": _clip_reply(reply)}

    @app.get("/api/analytics")
    def analytics(date_from: str | None = Query(None, alias="from"),
                  date_to: str | None = Query(None, alias="to"),
                  category: str | None = None):
        if category and category not in CATEGORIES:
            raise HTTPException(422, "category must be one of %s" % (CATEGORIES,))
        for v in (date_from, date_to):
            if v:
                try:
                    datetime.fromisoformat(v[:10])
                except ValueError:
                    raise HTTPException(422, "dates must be YYYY-MM-DD")
        records = load_for_analytics(store, date_from, date_to)
        return aggregate(records, date_from, date_to, category)

    # Serve the built front end (frontend/dist) from the same origin when present.
    dist = settings.frontend_dist
    if dist.exists() and (dist / "index.html").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        def spa(path: str):
            target = dist / path
            if path and target.is_file() and dist in target.resolve().parents:
                return FileResponse(target)
            return FileResponse(dist / "index.html")

    return app


app = create_app()
