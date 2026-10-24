"""FastAPI routes for the AI feedback and technical-ticket platform.

The implementation is intentionally split into small modules:

* :mod:`db` owns SQLite schema, transactions, and trace persistence.
* :mod:`schemas` owns request/response models and row conversion.
* :mod:`retrieval` owns deterministic BM25 ranking and diagnostics.
* :mod:`ai` owns the optional OpenAI-compatible provider and bounded Agent
  workflow; it never writes to the database.

This module wires those pieces together and keeps the HTTP contract in one
place.  ``create_app`` accepts an explicit database path and an injectable AI
provider so tests and local demos can run without a real model key.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

try:  # Package imports for `uvicorn server.main:app` and test execution.
    from .ai import (
        AIProvider,
        AISettings,
        OpenAICompatibleProvider,
        ProviderError,
        SYSTEM_PROMPT,
        TOOL_PLAN_PROMPT,
        as_text,
        build_recommendation_prompt,
        build_tool_plan_prompt,
        model_trace_fields,
        parse_json_object,
        retrieve_documents,
        run_tool,
        unavailable_analysis,
        validate_tool_plan,
        validated_evidence,
    )
    from .db import Database, insert_trace, utc_now
    from .retrieval import retrieval_diagnostics
    from .model_settings import ModelConfig, install_routes
    from .schemas import (
        AnalysisOut,
        DocumentCreate,
        DocumentOut,
        FeedbackCreate,
        FeedbackOut,
        MetricsOut,
        ProjectCreate,
        ProjectOut,
        TicketApproval,
        TicketStatusUpdate,
        TicketOut,
        TraceOut,
        analysis_from_row,
        document_from_row,
        feedback_from_row,
        project_from_row,
        ticket_from_row,
        trace_from_row,
    )
except ImportError:  # Direct-module compatibility for `cd server; uvicorn main:app`.
    from ai import (  # type: ignore[no-redef]
        AIProvider,
        AISettings,
        OpenAICompatibleProvider,
        ProviderError,
        SYSTEM_PROMPT,
        TOOL_PLAN_PROMPT,
        as_text,
        build_recommendation_prompt,
        build_tool_plan_prompt,
        model_trace_fields,
        parse_json_object,
        retrieve_documents,
        run_tool,
        unavailable_analysis,
        validate_tool_plan,
        validated_evidence,
    )
    from db import Database, insert_trace, utc_now  # type: ignore[no-redef]
    from retrieval import retrieval_diagnostics  # type: ignore[no-redef]
    from model_settings import ModelConfig, install_routes
    from schemas import (  # type: ignore[no-redef]
        AnalysisOut,
        DocumentCreate,
        DocumentOut,
        FeedbackCreate,
        FeedbackOut,
        MetricsOut,
        ProjectCreate,
        ProjectOut,
        TicketApproval,
        TicketStatusUpdate,
        TicketOut,
        TraceOut,
        analysis_from_row,
        document_from_row,
        feedback_from_row,
        project_from_row,
        ticket_from_row,
        trace_from_row,
    )


def create_app(
    db_path: str | Path | None = None,
    *,
    ai_provider: AIProvider | None = None,
    offline: bool = False,
    static_dir: str | Path | None = None,
    restore_saved_model: bool = False,
    connection_tester=None,
) -> FastAPI:
    """Build an API instance with isolated persistence and an injectable model."""

    if db_path is None:
        configured_path = os.getenv("DATABASE_PATH", os.getenv("DB_PATH", "")).strip()
        db_path = configured_path or (Path(__file__).resolve().parent / "data" / "app.db")
    db = Database(db_path)
    try:
        from .demo import ReplayProvider
    except ImportError:
        from demo import ReplayProvider
    replay_provider = ReplayProvider()
    live_provider = ai_provider or OpenAICompatibleProvider()
    config = ModelConfig(None if str(db_path) == ':memory:' else Path(db_path).parent / 'model-settings.json')
    if restore_saved_model and config.remembered:
        offline = not config.saved_enabled

    app = FastAPI(title="AI Feedback Ticket API", version="0.1.0")
    app.state.db = db
    app.state.ai_provider = replay_provider if offline else live_provider
    app.state.offline = offline
    app.state.model_config = config

    def activate_model_mode(use_offline):
        app.state.offline = use_offline
        app.state.ai_provider = replay_provider if use_offline else live_provider

    install_routes(app, config, activate_model_mode, connection_tester)

    @app.exception_handler(sqlite3.Error)
    async def database_error(_request, _exc):
        return JSONResponse(status_code=503, content={"detail": "数据暂时无法保存或读取，请稍后重试。", "code": "database_unavailable"})

    @app.exception_handler(Exception)
    async def unexpected_error(_request, _exc):
        return JSONResponse(status_code=500, content={"detail": "服务处理失败，请重试；若持续失败请检查本地服务。", "code": "internal_error"})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "http://localhost:3000",
            "http://127.0.0.1:3000",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    def require_project(project_id: int) -> sqlite3.Row:
        project = db.fetchone("SELECT * FROM projects WHERE id = ?", (project_id,))
        if project is None:
            raise HTTPException(status_code=404, detail="project not found")
        return project

    def require_feedback(feedback_id: int) -> sqlite3.Row:
        feedback = db.fetchone("SELECT * FROM feedback WHERE id = ?", (feedback_id,))
        if feedback is None:
            raise HTTPException(status_code=404, detail="feedback not found")
        return feedback

    @app.get("/api/health")
    def health() -> dict[str, Any]:
        if app.state.offline:
            return {"status": "ok", "ai_configured": False, "demo_mode": True, "mode": "offline_replay"}
        return {"status": "ok", "ai_configured": config.current().configured}

    @app.get("/api/projects", response_model=list[ProjectOut])
    def list_projects() -> list[ProjectOut]:
        rows = db.fetchall("SELECT * FROM projects ORDER BY id DESC")
        return [project_from_row(row) for row in rows]

    @app.post("/api/projects", response_model=ProjectOut, status_code=201)
    def create_project(payload: ProjectCreate) -> ProjectOut:
        with db.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO projects(name, description, created_at) VALUES (?, ?, ?)",
                (payload.name, payload.description, utc_now()),
            )
            row = connection.execute(
                "SELECT * FROM projects WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return project_from_row(row)

    @app.get("/api/documents", response_model=list[DocumentOut])
    def list_documents(project_id: int | None = Query(default=None, gt=0)) -> list[DocumentOut]:
        if project_id is None:
            rows = db.fetchall("SELECT * FROM documents ORDER BY id DESC")
        else:
            require_project(project_id)
            rows = db.fetchall(
                "SELECT * FROM documents WHERE project_id = ? ORDER BY id DESC", (project_id,)
            )
        return [document_from_row(row) for row in rows]

    @app.post("/api/documents", response_model=DocumentOut, status_code=201)
    def create_document(payload: DocumentCreate) -> DocumentOut:
        require_project(payload.project_id)
        with db.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO documents(project_id, title, content, created_at) VALUES (?, ?, ?, ?)",
                (payload.project_id, payload.title, payload.content, utc_now()),
            )
            row = connection.execute(
                "SELECT * FROM documents WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return document_from_row(row)

    @app.get("/api/feedback", response_model=list[FeedbackOut])
    def list_feedback(project_id: int | None = Query(default=None, gt=0)) -> list[FeedbackOut]:
        if project_id is None:
            rows = db.fetchall("SELECT * FROM feedback ORDER BY id DESC")
        else:
            require_project(project_id)
            rows = db.fetchall(
                "SELECT * FROM feedback WHERE project_id = ? ORDER BY id DESC", (project_id,)
            )
        return [feedback_from_row(row) for row in rows]

    @app.post("/api/feedback", response_model=FeedbackOut, status_code=201)
    def create_feedback(payload: FeedbackCreate) -> FeedbackOut:
        require_project(payload.project_id)
        with db.transaction() as connection:
            cursor = connection.execute(
                "INSERT INTO feedback(project_id, source, content, status, created_at) VALUES (?, ?, ?, 'new', ?)",
                (payload.project_id, payload.source, payload.content, utc_now()),
            )
            row = connection.execute(
                "SELECT * FROM feedback WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return feedback_from_row(row)

    @app.post("/api/feedback/{feedback_id}/analyze", response_model=AnalysisOut)
    def analyze_feedback(feedback_id: int) -> AnalysisOut:
        feedback = require_feedback(feedback_id)
        documents = db.fetchall(
            "SELECT * FROM documents WHERE project_id = ? ORDER BY id DESC", (feedback["project_id"],)
        )
        fallback_documents = retrieve_documents(documents, feedback["content"])
        selected_ids = [int(row["id"]) for row in fallback_documents]
        insert_trace(
            db,
            feedback_id,
            "retrieval",
            json.dumps(
                {
                    "document_count": len(documents),
                    "selected_document_ids": selected_ids,
                    **retrieval_diagnostics(documents, feedback["content"]),
                },
                ensure_ascii=False,
            ),
        )

        with config.lock:
            offline_mode = app.state.offline
            provider = app.state.ai_provider
            settings = AISettings("offline", "offline://replay", "fixture-replay-v1") if offline_mode else config.current()
        if not fallback_documents:
            reason = "该项目暂无可用于核验的文档。"
            insert_trace(db, feedback_id, "error", reason)
            result = unavailable_analysis(feedback_id, reason)
        elif not settings.configured:
            reason = "AI 服务未配置：请设置 OPENAI_API_KEY、OPENAI_BASE_URL 和 OPENAI_MODEL。"
            insert_trace(db, feedback_id, "error", reason)
            result = unavailable_analysis(feedback_id, reason)
        else:
            result = _run_agent_analysis(
                provider=provider,
                offline_mode=offline_mode,
                db=db,
                feedback=feedback,
                documents=documents,
                fallback_documents=fallback_documents,
                fallback_ids=selected_ids,
                settings=settings,
            )

        with db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO analyses(
                    feedback_id, category, summary, suggested_reply, proposed_task,
                    evidence_json, needs_review, model_mode, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(feedback_id) DO UPDATE SET
                    category=excluded.category,
                    summary=excluded.summary,
                    suggested_reply=excluded.suggested_reply,
                    proposed_task=excluded.proposed_task,
                    evidence_json=excluded.evidence_json,
                    needs_review=excluded.needs_review,
                    model_mode=excluded.model_mode,
                    updated_at=excluded.updated_at
                """,
                (
                    result.feedback_id,
                    result.category,
                    result.summary,
                    result.suggested_reply,
                    result.proposed_task,
                    json.dumps([item.model_dump() for item in result.evidence], ensure_ascii=False),
                    int(result.needs_review),
                    result.model_mode,
                    utc_now(),
                ),
            )
            connection.execute(
                "UPDATE feedback SET status = 'analyzed' WHERE id = ? AND status = 'new'",
                (feedback_id,),
            )
        return result

    @app.get("/api/feedback/{feedback_id}/analysis", response_model=AnalysisOut)
    def get_feedback_analysis(feedback_id: int) -> AnalysisOut:
        require_feedback(feedback_id)
        row = db.fetchone("SELECT * FROM analyses WHERE feedback_id = ?", (feedback_id,))
        if row is None:
            raise HTTPException(status_code=404, detail="feedback has not been analyzed")
        return analysis_from_row(row)

    @app.post("/api/feedback/{feedback_id}/approve", response_model=TicketOut)
    def approve_feedback(
        feedback_id: int,
        payload: TicketApproval | None = None,
    ) -> TicketOut:
        feedback = require_feedback(feedback_id)
        with db.transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM tickets WHERE feedback_id = ?", (feedback_id,)
            ).fetchone()
            if existing is not None:
                return ticket_from_row(existing)
            analysis = connection.execute(
                "SELECT * FROM analyses WHERE feedback_id = ?", (feedback_id,)
            ).fetchone()
            if analysis is None:
                raise HTTPException(status_code=409, detail="analyze feedback before approval")
            if analysis["model_mode"] != "ai" and not (app.state.offline and analysis["model_mode"] == "demo"):
                raise HTTPException(status_code=409, detail="only a completed AI analysis can be approved")
            try:
                persisted_evidence = json.loads(analysis["evidence_json"])
            except (TypeError, ValueError):
                persisted_evidence = []
            if not isinstance(persisted_evidence, list) or not persisted_evidence:
                raise HTTPException(status_code=409, detail="analysis has no supported evidence")
            if not analysis["proposed_task"].strip():
                raise HTTPException(status_code=409, detail="analysis has no proposed task")
            original_proposed_task = analysis["proposed_task"].strip()
            title = (
                payload.title.strip()
                if payload is not None and payload.title is not None
                else original_proposed_task[:240]
            )
            reviewer_note = payload.reviewer_note if payload is not None else ""
            created_at = utc_now()
            cursor = connection.execute(
                """
                INSERT INTO tickets(
                    feedback_id, project_id, title, reviewer_note,
                    original_proposed_task, status, resolution_note,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'open', '', ?, ?)
                """,
                (
                    feedback_id,
                    feedback["project_id"],
                    title,
                    reviewer_note,
                    original_proposed_task,
                    created_at,
                    created_at,
                ),
            )
            connection.execute("UPDATE feedback SET status = 'ticketed' WHERE id = ?", (feedback_id,))
            connection.execute(
                """
                INSERT INTO traces(feedback_id, step, detail, created_at)
                VALUES (?, 'review', ?, ?)
                """,
                (
                    feedback_id,
                    json.dumps(
                        {
                            "status": "approved",
                            "title_source": "reviewer"
                            if payload is not None and payload.title is not None
                            else "ai_proposed_task",
                            "title_length": len(title),
                            "reviewer_note_length": len(reviewer_note),
                            "original_proposed_task_length": len(original_proposed_task),
                        },
                        ensure_ascii=False,
                    ),
                    utc_now(),
                ),
            )
            row = connection.execute(
                "SELECT * FROM tickets WHERE id = ?", (cursor.lastrowid,)
            ).fetchone()
        return ticket_from_row(row)

    @app.get("/api/tickets", response_model=list[TicketOut])
    def list_tickets(project_id: int | None = Query(default=None, gt=0)) -> list[TicketOut]:
        if project_id is None:
            rows = db.fetchall("SELECT * FROM tickets ORDER BY id DESC")
        else:
            require_project(project_id)
            rows = db.fetchall(
                "SELECT * FROM tickets WHERE project_id = ? ORDER BY id DESC", (project_id,)
            )
        return [ticket_from_row(row) for row in rows]

    @app.patch("/api/tickets/{ticket_id}", response_model=TicketOut)
    def update_ticket_status(ticket_id: int, payload: TicketStatusUpdate) -> TicketOut:
        """Advance a ticket through its monotonic lifecycle.

        Status transitions are serialized with the same database transaction
        used for the audit trace. Repeating a request for the current status
        is a no-op and therefore cannot create duplicate ``ticket_status``
        traces.
        """

        allowed_transitions = {
            "open": {"in_progress", "done"},
            "in_progress": {"done"},
            "done": set(),
        }
        with db.transaction() as connection:
            current = connection.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
            if current is None:
                raise HTTPException(status_code=404, detail="ticket not found")

            requested_status = payload.status
            current_status = str(current["status"])
            if requested_status == current_status:
                return ticket_from_row(current)
            if requested_status not in allowed_transitions.get(current_status, set()):
                raise HTTPException(
                    status_code=409,
                    detail=f"invalid ticket status transition: {current_status} -> {requested_status}",
                )

            resolution_note = payload.resolution_note or ""
            if requested_status == "done" and not resolution_note:
                raise HTTPException(
                    status_code=422,
                    detail="resolution_note is required when completing a ticket",
                )

            updated_at = utc_now()
            connection.execute(
                """
                UPDATE tickets
                SET status = ?, resolution_note = ?, updated_at = ?
                WHERE id = ?
                """,
                (requested_status, resolution_note, updated_at, ticket_id),
            )
            connection.execute(
                """
                INSERT INTO traces(feedback_id, step, detail, created_at)
                VALUES (?, 'ticket_status', ?, ?)
                """,
                (
                    current["feedback_id"],
                    json.dumps(
                        {
                            "from": current_status,
                            "to": requested_status,
                            "note_length": len(resolution_note),
                        },
                        ensure_ascii=False,
                    ),
                    updated_at,
                ),
            )
            row = connection.execute(
                "SELECT * FROM tickets WHERE id = ?", (ticket_id,)
            ).fetchone()
        return ticket_from_row(row)

    @app.get("/api/traces", response_model=list[TraceOut])
    def list_traces(feedback_id: int = Query(..., gt=0)) -> list[TraceOut]:
        require_feedback(feedback_id)
        rows = db.fetchall(
            "SELECT * FROM traces WHERE feedback_id = ? ORDER BY id ASC", (feedback_id,)
        )
        return [trace_from_row(row) for row in rows]

    @app.get("/api/metrics", response_model=MetricsOut)
    def metrics(project_id: int | None = Query(default=None, gt=0)) -> MetricsOut:
        """Aggregate workflow outcomes and safe model telemetry.

        This endpoint deliberately reads only counts and allow-listed numeric
        trace fields. Prompts, feedback text, model responses and keys are
        never returned.
        """

        if project_id is not None:
            require_project(project_id)
        project_clause = " WHERE project_id = ?" if project_id is not None else ""
        params: tuple[Any, ...] = (project_id,) if project_id is not None else ()

        def count(table: str, extra: str = "", extra_params: tuple[Any, ...] = ()) -> int:
            row = db.fetchone(
                f"SELECT COUNT(*) AS value FROM {table}{project_clause}{extra}",
                params + extra_params,
            )
            return int(row["value"]) if row is not None else 0

        documents_count = count("documents")
        feedback_count = count("feedback")
        tickets_count = count("tickets")
        completed_tickets = count("tickets", " AND status = ?" if project_clause else " WHERE status = ?", ("done",))

        analysis_where = " WHERE f.project_id = ?" if project_id is not None else ""
        analysis_rows = db.fetchall(
            "SELECT a.model_mode, COUNT(*) AS value FROM analyses a "
            f"JOIN feedback f ON f.id = a.feedback_id{analysis_where} GROUP BY a.model_mode",
            params,
        )
        analysis_modes = {str(row["model_mode"]): int(row["value"]) for row in analysis_rows}
        analyses_count = sum(analysis_modes.values())

        trace_where = " WHERE f.project_id = ?" if project_id is not None else ""
        trace_rows = db.fetchall(
            "SELECT t.step, t.detail FROM traces t "
            f"JOIN feedback f ON f.id = t.feedback_id{trace_where} ORDER BY t.id",
            params,
        )
        latencies: list[int] = []
        total_tokens = 0
        model_calls = 0
        for row in trace_rows:
            if row["step"] != "model":
                continue
            model_calls += 1
            try:
                detail = json.loads(row["detail"])
            except (TypeError, ValueError):
                continue
            if not isinstance(detail, dict):
                continue
            elapsed_ms = detail.get("elapsed_ms")
            tokens = detail.get("total_tokens")
            if isinstance(elapsed_ms, int) and not isinstance(elapsed_ms, bool) and elapsed_ms >= 0:
                latencies.append(elapsed_ms)
            if isinstance(tokens, int) and not isinstance(tokens, bool) and tokens >= 0:
                total_tokens += tokens

        def percentile(values: list[int], fraction: float) -> int | None:
            if not values:
                return None
            ordered = sorted(values)
            position = (len(ordered) - 1) * fraction
            lower = int(position)
            upper = min(len(ordered) - 1, lower + 1)
            weight = position - lower
            return round(ordered[lower] * (1 - weight) + ordered[upper] * weight)

        ai_analyses = analysis_modes.get("ai", 0)
        return MetricsOut(
            project_id=project_id,
            documents=documents_count,
            feedback=feedback_count,
            analyses=analyses_count,
            ai_analyses=ai_analyses,
            unavailable_analyses=analysis_modes.get("unavailable", 0),
            tickets=tickets_count,
            completed_tickets=completed_tickets,
            traces=len(trace_rows),
            model_calls=model_calls,
            total_tokens=total_tokens,
            model_latency_p50_ms=percentile(latencies, 0.50),
            model_latency_p95_ms=percentile(latencies, 0.95),
            ai_to_ticket_rate=round(tickets_count / ai_analyses, 4) if ai_analyses else 0.0,
        )

    if static_dir is not None:
        import mimetypes
        from fastapi.staticfiles import StaticFiles

        # Windows registry associations can map .js to text/plain. Browsers
        # reject ES modules with that MIME type, leaving an empty screen.
        mimetypes.init()
        mimetypes.add_type("text/javascript", ".js")
        mimetypes.add_type("text/css", ".css")
        mimetypes.add_type("image/svg+xml", ".svg")

        @app.api_route("/api/{unknown_path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
        def unknown_api(unknown_path: str):
            raise HTTPException(status_code=404, detail="API route not found")

        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="web")

    return app


def _safe_failure_code(exc: Exception) -> str:
    """Expose only fixed internal codes; never trace provider response bodies."""

    if isinstance(exc, ProviderError):
        return exc.code
    if isinstance(exc, ValueError):
        return {
            "model response was not valid JSON": "invalid_json",
            "model response was not a JSON object": "invalid_json_object",
            "model response lacked a complete, supported recommendation": "incomplete_or_uncited_recommendation",
        }.get(str(exc), "validation_error")
    return type(exc).__name__


def _run_agent_analysis(
    *,
    provider: AIProvider,
    offline_mode: bool,
    db: Database,
    feedback: sqlite3.Row,
    documents: list[sqlite3.Row],
    fallback_documents: list[sqlite3.Row],
    fallback_ids: list[int],
    settings: Any,
) -> AnalysisOut:
    """Run the bounded planner -> tool -> recommendation workflow."""

    model_step = "replay" if offline_mode else "model"
    selected = fallback_documents
    tool_name = "search_documents"
    tool_result: dict[str, Any] = {
        "tool": tool_name,
        "arguments": {"query": str(feedback["content"])[:500]},
        "document_ids": fallback_ids,
        "fallback": True,
    }
    planner_trace: dict[str, Any] = {
        "model": settings.model,
        "phase": "tool_plan",
        "status": "requested",
    }
    planner_started = time.perf_counter()
    try:
        raw_plan = provider.complete(
            system_prompt=TOOL_PLAN_PROMPT,
            user_prompt=build_tool_plan_prompt(feedback, documents),
            settings=settings,
        )
        planner_elapsed = round((time.perf_counter() - planner_started) * 1_000)
        planner_trace.update(model_trace_fields(raw_plan, configured_model=settings.model, elapsed_ms=planner_elapsed))
        planner_trace["status"] = "response_received"
        parsed_plan = parse_json_object(raw_plan)
        tool_name, tool_arguments = validate_tool_plan(parsed_plan)
        selected, tool_result = run_tool(
            tool_name,
            tool_arguments,
            documents,
            fallback_documents,
        )
        tool_result["fallback"] = False
        planner_trace["status"] = "accepted"
        insert_trace(db, feedback["id"], model_step, json.dumps(planner_trace, ensure_ascii=False))
        insert_trace(db, feedback["id"], "tool", json.dumps(tool_result, ensure_ascii=False))
    except Exception as exc:
        # An invalid plan never reaches a tool. Fall back to deterministic
        # document search and continue to the recommendation call.
        planner_trace["status"] = "malformed" if isinstance(exc, ValueError) else "failed"
        planner_elapsed = getattr(exc, "elapsed_ms", None) or round((time.perf_counter() - planner_started) * 1_000)
        planner_trace.update(model_trace_fields(exc, configured_model=settings.model, elapsed_ms=planner_elapsed))
        planner_trace["error_code"] = _safe_failure_code(exc)
        insert_trace(db, feedback["id"], model_step, json.dumps(planner_trace, ensure_ascii=False))
        tool_result["fallback_reason"] = _safe_failure_code(exc)
        insert_trace(db, feedback["id"], "tool", json.dumps(tool_result, ensure_ascii=False))
        if not isinstance(exc, ValueError):
            insert_trace(db, feedback["id"], "error", "AI tool planning failed; deterministic search used")

    model_trace: dict[str, Any] = {
        "model": settings.model,
        "phase": "recommendation",
        "status": "requested",
    }
    recommendation_started = time.perf_counter()
    try:
        raw = provider.complete(
            system_prompt=SYSTEM_PROMPT,
            user_prompt=build_recommendation_prompt(
                feedback,
                selected,
                tool_name=tool_name,
                tool_result=tool_result,
            ),
            settings=settings,
        )
        recommendation_elapsed = round((time.perf_counter() - recommendation_started) * 1_000)
        model_trace.update(model_trace_fields(raw, configured_model=settings.model, elapsed_ms=recommendation_elapsed))
        model_trace["status"] = "response_received"
        parsed = parse_json_object(raw)
        evidence, rejected_citations = validated_evidence(
            parsed.get("citations", parsed.get("evidence")),
            {int(row["id"]): row for row in selected},
        )
        category = as_text(parsed.get("category"), "other")
        if category not in {"bug", "question", "feature", "other"}:
            category = "other"
        summary = as_text(parsed.get("summary"))
        suggested_reply = as_text(parsed.get("suggested_reply"))
        proposed_task = as_text(parsed.get("proposed_task"))
        if not summary or not suggested_reply or not proposed_task or not evidence:
            raise ValueError("model response lacked a complete, supported recommendation")
        result = AnalysisOut(
            feedback_id=int(feedback["id"]),
            category=category,
            summary=summary,
            suggested_reply=suggested_reply,
            proposed_task=proposed_task,
            evidence=evidence,
            needs_review=bool(parsed.get("needs_review", True)) or bool(rejected_citations),
            model_mode="demo" if offline_mode else "ai",
        )
        model_trace.update(
            {
                "status": "accepted",
                "evidence_count": len(evidence),
                "rejected_citations": rejected_citations,
            }
        )
        insert_trace(db, feedback["id"], model_step, json.dumps(model_trace, ensure_ascii=False))
        return result
    except Exception as exc:
        # Provider errors and unsupported responses are not surfaced as fake
        # recommendations. Keep the user-facing analysis explicitly unavailable.
        model_trace["status"] = "failed"
        recommendation_elapsed = getattr(exc, "elapsed_ms", None) or round((time.perf_counter() - recommendation_started) * 1_000)
        model_trace.update(model_trace_fields(exc, configured_model=settings.model, elapsed_ms=recommendation_elapsed))
        model_trace["error_code"] = _safe_failure_code(exc)
        insert_trace(db, feedback["id"], model_step, json.dumps(model_trace, ensure_ascii=False))
        insert_trace(db, feedback["id"], "error", f"AI analysis failed: {model_trace['error_code']}")
        return unavailable_analysis(
            int(feedback["id"]),
            "AI 分析暂时不可用，无法生成已核验的建议。请人工处理。",
        )


app = create_app(restore_saved_model=True)


if __name__ == "__main__":  # pragma: no cover - convenience for local demos
    import uvicorn

    uvicorn.run("main:app", host="127.0.0.1", port=int(os.getenv("PORT", "8000")), reload=False)
