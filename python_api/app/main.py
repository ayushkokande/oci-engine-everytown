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

from .analytics import aggregate, load_for_analytics
from .config import Settings, load_settings
from .llm import LLMClient, ModelError, build_llm
from .orchestrator import merge_recommendations, orchestrate
from .pdf_report import render_pdf
from .question_chat import explain_question
from .questions import missing_answers, normalise_answers, questions_payload, validate_domain_config
from .resources import load_library
from .scoring_adapter import gaps_from_recs, score_submission
from .seed import SAMPLES, benchmark_answers, seed_if_empty
from .store import SubmissionRecord, SubmissionStore, build_store, new_submission_id

log = logging.getLogger("oci")

CATEGORIES = ("grantee", "non_grantee")


class Profile(BaseModel):
    org_name: str = Field(min_length=1, max_length=200)
    website_url: str = Field(default="", max_length=500)
    category: str = "grantee"


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
        for index, message in enumerate(messages):
            expected_role = "user" if index % 2 == 0 else "assistant"
            if message["role"] != expected_role:
                raise HTTPException(422, "chat messages must alternate user and assistant roles")
            if message["role"] == "user" and len(message["content"]) > 1000:
                raise HTTPException(422, "user messages must be 1000 characters or fewer")
        if messages[-1]["role"] != "user":
            raise HTTPException(422, "the final chat message must be from the user")
        if sum(len(message["content"]) for message in messages) > 12000:
            raise HTTPException(422, "chat history is too long")

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

    @app.get("/api/samples/{sample}")
    def sample(sample: str):
        """Demo helper: synthetic benchmark answers for the in-scope domains."""
        s = sample.upper()
        if s not in SAMPLES:
            raise HTTPException(404, "unknown sample")
        name, cat = SAMPLES[s]
        return {"sample": s, "org_name": name, "category": cat,
                "answers": benchmark_answers(s, settings.in_scope_domains)}

    def _narrate(record: SubmissionRecord, profile: dict, display: dict, gaps: list) -> None:
        """Run the Bedrock pipeline and attach its narrative to the record. Scores are untouched."""
        try:
            result = orchestrate(llm, profile, display, gaps, library,
                                 max_tokens=settings.bedrock_max_tokens,
                                 fetch_timeout=settings.research_fetch_timeout_s,
                                 skip_fetch=settings.llm_mode == "mock")
        except Exception as e:  # never let orchestration take the scores down with it
            log.exception("orchestration crashed")
            from .orchestrator import OrchestrationResult
            result = OrchestrationResult(status="error", error="orchestration_failed:%s" % type(e).__name__)

        record.research_summary = result.research_summary
        record.overview = result.overview
        record.action_plan = result.action_plan
        record.orchestration_status = result.status
        record.orchestration_error = result.error
        record.recommendations = (merge_recommendations(gaps, result.narratives)
                                  if result.status == "ok" else [])

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
            body = record.to_dict()
            body.pop("answers", None)
            body["persisted"] = persisted
            return JSONResponse(status_code=202, content=body)

        _narrate(record, profile, display, gaps)
        persisted = _save(record)
        body = record.to_dict()
        body.pop("answers", None)
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
        data = _load(submission_id)
        data.pop("answers", None)
        return data

    @app.get("/api/report/{submission_id}")
    def report(submission_id: str):
        data = _load(submission_id)
        pdf = render_pdf(data)
        slug = submission_id.split("_")[1] if "_" in submission_id else "report"
        return Response(pdf, media_type="application/pdf", headers={
            "Content-Disposition": 'attachment; filename="OCI_Recommendations_%s.pdf"' % slug})

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
