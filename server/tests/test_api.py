from __future__ import annotations

import json
import sqlite3

from fastapi.testclient import TestClient

from server.main import create_app


def make_client(tmp_path, ai_provider=None):
    return TestClient(create_app(tmp_path / "app.sqlite3", ai_provider=ai_provider))


def create_project(client, name="Project", description="Demo"):
    response = client.post("/api/projects", json={"name": name, "description": description})
    assert response.status_code == 201
    return response.json()


def create_document(client, project_id, title="Guide", content="Reset the password from Settings."):
    response = client.post(
        "/api/documents",
        json={"project_id": project_id, "title": title, "content": content},
    )
    assert response.status_code == 201
    return response.json()


def create_feedback(client, project_id, content="How do I reset the password?"):
    response = client.post(
        "/api/feedback",
        json={"project_id": project_id, "source": "test", "content": content},
    )
    assert response.status_code == 201
    return response.json()


class GoodProvider:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def complete(self, *, system_prompt, user_prompt, settings):
        self.calls += 1
        return json.dumps(self.payload, ensure_ascii=False)


class SequenceProvider:
    def __init__(self, *payloads):
        self.payloads = payloads
        self.calls = 0
        self.prompts = []

    def complete(self, *, system_prompt, user_prompt, settings):
        self.prompts.append((system_prompt, user_prompt))
        payload = self.payloads[min(self.calls, len(self.payloads) - 1)]
        self.calls += 1
        return json.dumps(payload, ensure_ascii=False)


def configure_ai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")


def valid_recommendation(document_id):
    return {
        "category": "question",
        "summary": "Password reset",
        "suggested_reply": "Use Settings.",
        "proposed_task": "Verify password reset instructions.",
        "needs_review": False,
        "citations": [{"document_id": document_id, "excerpt": "Reset the password from Settings."}],
    }


def test_health_reports_missing_ai_configuration(monkeypatch, tmp_path):
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    client = make_client(tmp_path)
    assert client.get("/api/health").json() == {"status": "ok", "ai_configured": False}


def test_in_memory_database_keeps_schema_across_short_lived_connections():
    client = TestClient(create_app(":memory:"))
    project = create_project(client)
    assert client.get("/api/projects").json()[0]["id"] == project["id"]


def test_sqlite_persistence_and_project_isolation(tmp_path):
    first = make_client(tmp_path)
    project_a = create_project(first, "A")
    project_b = create_project(first, "B")
    create_document(first, project_a["id"], content="A only")
    create_document(first, project_b["id"], content="B only")
    create_feedback(first, project_a["id"], content="A feedback")
    create_feedback(first, project_b["id"], content="B feedback")

    second = make_client(tmp_path)
    assert [item["name"] for item in second.get("/api/projects").json()] == ["B", "A"]
    assert [item["content"] for item in second.get(f"/api/documents?project_id={project_a['id']}").json()] == ["A only"]
    assert [item["content"] for item in second.get(f"/api/feedback?project_id={project_b['id']}").json()] == ["B feedback"]


def test_metrics_aggregate_safe_model_telemetry_per_project(tmp_path):
    app = create_app(tmp_path / "metrics.sqlite3")
    client = TestClient(app)
    project_a = create_project(client, "A")
    project_b = create_project(client, "B")
    create_document(client, project_a["id"])
    feedback_a = create_feedback(client, project_a["id"])
    feedback_b = create_feedback(client, project_b["id"])
    now = "2026-10-15T00:00:00Z"
    with app.state.db.transaction() as connection:
        for feedback_id, mode in ((feedback_a["id"], "ai"), (feedback_b["id"], "unavailable")):
            connection.execute(
                """INSERT INTO analyses(feedback_id, category, summary, suggested_reply,
                   proposed_task, evidence_json, needs_review, model_mode, updated_at)
                   VALUES (?, 'question', 's', 'r', 't', '[]', 1, ?, ?)""",
                (feedback_id, mode, now),
            )
        connection.execute(
            """INSERT INTO tickets(feedback_id, project_id, title, status, resolution_note,
               created_at, updated_at) VALUES (?, ?, 'done', 'done', 'verified', ?, ?)""",
            (feedback_a["id"], project_a["id"], now, now),
        )
        for elapsed, tokens in ((100, 20), (300, 30)):
            connection.execute(
                "INSERT INTO traces(feedback_id, step, detail, created_at) VALUES (?, 'model', ?, ?)",
                (feedback_a["id"], json.dumps({"elapsed_ms": elapsed, "total_tokens": tokens}), now),
            )
        connection.execute(
            "INSERT INTO traces(feedback_id, step, detail, created_at) VALUES (?, 'model', 'not-json', ?)",
            (feedback_b["id"], now),
        )

    response = client.get(f"/api/metrics?project_id={project_a['id']}")
    assert response.status_code == 200
    metrics = response.json()
    assert metrics == {
        "project_id": project_a["id"],
        "documents": 1,
        "feedback": 1,
        "analyses": 1,
        "ai_analyses": 1,
        "unavailable_analyses": 0,
        "tickets": 1,
        "completed_tickets": 1,
        "traces": 2,
        "model_calls": 2,
        "total_tokens": 50,
        "model_latency_p50_ms": 200,
        "model_latency_p95_ms": 290,
        "ai_to_ticket_rate": 1.0,
    }
    all_metrics = client.get("/api/metrics").json()
    assert all_metrics["feedback"] == 2
    assert all_metrics["unavailable_analyses"] == 1
    assert all_metrics["model_calls"] == 3
    assert client.get("/api/metrics?project_id=9999").status_code == 404


def test_no_ai_mode_is_honest_and_records_retrieval_error(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    client = make_client(tmp_path)
    project = create_project(client)
    create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])

    response = client.post(f"/api/feedback/{feedback['id']}/analyze")
    assert response.status_code == 200
    analysis = response.json()
    assert analysis["model_mode"] == "unavailable"
    assert analysis["evidence"] == []
    assert "未配置" in analysis["summary"]
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert [trace["step"] for trace in traces] == ["retrieval", "error"]
    assert client.get("/api/health").json()["ai_configured"] is False


def test_analysis_is_persisted_and_readable_from_new_app_instance(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    db_path = tmp_path / "persistent.sqlite3"
    writer = TestClient(create_app(db_path))
    project = create_project(writer)
    create_document(writer, project["id"])
    feedback = create_feedback(writer, project["id"])
    analyzed = writer.post(f"/api/feedback/{feedback['id']}/analyze")
    assert analyzed.status_code == 200

    reader = TestClient(create_app(db_path))
    fetched = reader.get(f"/api/feedback/{feedback['id']}/analysis")
    assert fetched.status_code == 200
    assert fetched.json() == analyzed.json()

    untouched = create_feedback(reader, project["id"], content="Not analyzed yet")
    assert reader.get(f"/api/feedback/{untouched['id']}/analysis").status_code == 404


def test_approval_requires_analysis_and_is_idempotent(tmp_path, monkeypatch):
    for name in ("OPENAI_API_KEY", "OPENAI_BASE_URL", "OPENAI_MODEL"):
        monkeypatch.delenv(name, raising=False)
    client = make_client(tmp_path)
    project = create_project(client)
    document = create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])
    blocked = client.post(f"/api/feedback/{feedback['id']}/approve")
    assert blocked.status_code == 409

    client.post(f"/api/feedback/{feedback['id']}/analyze")
    blocked_after_unavailable_analysis = client.post(f"/api/feedback/{feedback['id']}/approve")
    assert blocked_after_unavailable_analysis.status_code == 409

    configure_ai(monkeypatch)
    provider = SequenceProvider(
        {"tool": "search_documents", "arguments": {"query": "password"}},
        valid_recommendation(document["id"]),
    )
    client = make_client(tmp_path, provider)
    ai_feedback = create_feedback(client, project["id"])
    assert client.post(f"/api/feedback/{ai_feedback['id']}/analyze").json()["model_mode"] == "ai"
    first = client.post(f"/api/feedback/{ai_feedback['id']}/approve")
    second = client.post(f"/api/feedback/{ai_feedback['id']}/approve")
    assert first.status_code == second.status_code == 200
    assert first.json() == second.json()
    assert first.json()["reviewer_note"] == ""
    assert first.json()["original_proposed_task"] == "Verify password reset instructions."
    assert len(client.get(f"/api/tickets?project_id={project['id']}").json()) == 1


def test_approval_persists_reviewer_override_and_audit_trace(monkeypatch, tmp_path):
    configure_ai(monkeypatch)
    provider = SequenceProvider(
        {"tool": "search_documents", "arguments": {"query": "password"}},
        valid_recommendation(1),
    )
    client = make_client(tmp_path, provider)
    project = create_project(client)
    document = create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])
    client.post(f"/api/feedback/{feedback['id']}/analyze")

    response = client.post(
        f"/api/feedback/{feedback['id']}/approve",
        json={
            "title": "  Verify reset flow with the support team  ",
            "reviewer_note": "  Checked the cited guide before opening the ticket.  ",
        },
    )
    assert response.status_code == 200
    ticket = response.json()
    assert ticket["title"] == "Verify reset flow with the support team"
    assert ticket["reviewer_note"] == "Checked the cited guide before opening the ticket."
    assert ticket["original_proposed_task"] == "Verify password reset instructions."

    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    review_traces = [trace for trace in traces if trace["step"] == "review"]
    assert len(review_traces) == 1
    review_detail = json.loads(review_traces[0]["detail"])
    assert review_detail == {
        "status": "approved",
        "title_source": "reviewer",
        "title_length": len(ticket["title"]),
        "reviewer_note_length": len(ticket["reviewer_note"]),
        "original_proposed_task_length": len(ticket["original_proposed_task"]),
    }
    assert "Checked the cited guide" not in review_traces[0]["detail"]

    # A retry with different review text is idempotent and preserves the first
    # review, including its single audit event.
    retry = client.post(
        f"/api/feedback/{feedback['id']}/approve",
        json={"title": "Changed after approval", "reviewer_note": "Should not overwrite"},
    )
    assert retry.status_code == 200
    assert retry.json() == ticket
    traces_after_retry = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert len([trace for trace in traces_after_retry if trace["step"] == "review"]) == 1


def test_approval_rejects_invalid_review_input(monkeypatch, tmp_path):
    configure_ai(monkeypatch)
    provider = SequenceProvider(
        {"tool": "search_documents", "arguments": {"query": "password"}},
        valid_recommendation(1),
    )
    client = make_client(tmp_path, provider)
    project = create_project(client)
    document = create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])
    client.post(f"/api/feedback/{feedback['id']}/analyze")

    too_long_title = client.post(
        f"/api/feedback/{feedback['id']}/approve",
        json={"title": "x" * 241},
    )
    too_long_note = client.post(
        f"/api/feedback/{feedback['id']}/approve",
        json={"reviewer_note": "x" * 2_001},
    )
    blank_title = client.post(
        f"/api/feedback/{feedback['id']}/approve",
        json={"title": "   "},
    )
    assert too_long_title.status_code == 422
    assert too_long_note.status_code == 422
    assert blank_title.status_code == 422
    assert client.get(f"/api/tickets?project_id={project['id']}").json() == []


def create_approved_ticket(monkeypatch, tmp_path):
    """Create one AI-backed ticket for lifecycle tests."""

    configure_ai(monkeypatch)
    provider = SequenceProvider(
        {"tool": "search_documents", "arguments": {"query": "password"}},
        valid_recommendation(1),
    )
    client = make_client(tmp_path, provider)
    project = create_project(client)
    document = create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])
    analysis = client.post(f"/api/feedback/{feedback['id']}/analyze")
    assert analysis.status_code == 200
    # The fixture's citation points to the first document in this isolated DB.
    assert document["id"] == 1
    approval = client.post(f"/api/feedback/{feedback['id']}/approve")
    assert approval.status_code == 200
    return client, feedback, approval.json()


def test_ticket_lifecycle_allows_valid_transitions_and_audits_metadata(monkeypatch, tmp_path):
    client, feedback, ticket = create_approved_ticket(monkeypatch, tmp_path / "valid")
    assert ticket["status"] == "open"
    assert ticket["resolution_note"] == ""
    assert ticket["updated_at"] == ticket["created_at"]

    in_progress = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "in_progress"},
    )
    assert in_progress.status_code == 200
    assert in_progress.json()["status"] == "in_progress"
    assert in_progress.json()["resolution_note"] == ""

    done = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "done", "resolution_note": "  Verified the fix in the local demo.  "},
    )
    assert done.status_code == 200
    done_ticket = done.json()
    assert done_ticket["status"] == "done"
    assert done_ticket["resolution_note"] == "Verified the fix in the local demo."
    assert done_ticket["updated_at"]

    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    status_traces = [trace for trace in traces if trace["step"] == "ticket_status"]
    assert len(status_traces) == 2
    assert json.loads(status_traces[0]["detail"]) == {
        "from": "open",
        "to": "in_progress",
        "note_length": 0,
    }
    final_detail = json.loads(status_traces[1]["detail"])
    assert final_detail == {
        "from": "in_progress",
        "to": "done",
        "note_length": len(done_ticket["resolution_note"]),
    }
    assert "Verified the fix" not in status_traces[1]["detail"]


def test_ticket_lifecycle_rejects_backward_and_terminal_transitions(monkeypatch, tmp_path):
    client, feedback, ticket = create_approved_ticket(monkeypatch, tmp_path / "invalid")
    started = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "in_progress"},
    )
    assert started.status_code == 200

    backward = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "open"},
    )
    assert backward.status_code == 409
    assert "in_progress -> open" in backward.json()["detail"]

    completed = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "done", "resolution_note": "Completed."},
    )
    assert completed.status_code == 200
    terminal = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "in_progress"},
    )
    assert terminal.status_code == 409
    assert "done -> in_progress" in terminal.json()["detail"]

    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert len([trace for trace in traces if trace["step"] == "ticket_status"]) == 2


def test_ticket_completion_requires_bounded_non_empty_resolution_note(monkeypatch, tmp_path):
    client, feedback, ticket = create_approved_ticket(monkeypatch, tmp_path / "note")
    missing = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "done"},
    )
    blank = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "done", "resolution_note": "   "},
    )
    too_long = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "done", "resolution_note": "x" * 2_001},
    )
    assert missing.status_code == 422
    assert blank.status_code == 422
    assert too_long.status_code == 422
    persisted = client.get(f"/api/tickets?project_id={ticket['project_id']}").json()
    assert persisted[0]["status"] == "open"
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert [trace for trace in traces if trace["step"] == "ticket_status"] == []


def test_ticket_status_update_is_idempotent_without_duplicate_trace(monkeypatch, tmp_path):
    client, feedback, ticket = create_approved_ticket(monkeypatch, tmp_path / "idempotent")
    first = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "in_progress"},
    )
    second = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "in_progress", "resolution_note": "ignored on a no-op"},
    )
    assert first.status_code == second.status_code == 200
    assert second.json() == first.json()

    done = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "done", "resolution_note": "Fixed and verified."},
    )
    repeat = client.patch(
        f"/api/tickets/{ticket['id']}",
        json={"status": "done", "resolution_note": "A different note must not overwrite."},
    )
    assert done.status_code == repeat.status_code == 200
    assert repeat.json() == done.json()
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert len([trace for trace in traces if trace["step"] == "ticket_status"]) == 2


def test_existing_ticket_schema_is_migrated_and_snapshot_backfilled(tmp_path):
    db_path = tmp_path / "legacy.sqlite3"
    connection = sqlite3.connect(db_path)
    connection.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE feedback (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            source TEXT NOT NULL,
            content TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE analyses (
            feedback_id INTEGER PRIMARY KEY,
            category TEXT NOT NULL,
            summary TEXT NOT NULL,
            suggested_reply TEXT NOT NULL,
            proposed_task TEXT NOT NULL,
            evidence_json TEXT NOT NULL,
            needs_review INTEGER NOT NULL,
            model_mode TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE tickets (
            id INTEGER PRIMARY KEY,
            feedback_id INTEGER NOT NULL UNIQUE,
            project_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            status TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        INSERT INTO projects VALUES (1, 'Legacy', '', '2026-01-01T00:00:00Z');
        INSERT INTO feedback VALUES (1, 1, 'legacy-test', 'Old feedback', 'ticketed', '2026-01-01T00:00:00Z');
        INSERT INTO analyses VALUES (
            1, 'question', 'Summary', 'Reply', 'Historical AI task',
            '[]', 0, 'ai', '2026-01-01T00:00:00Z'
        );
        INSERT INTO tickets VALUES (
            1, 1, 1, 'Historical AI task', 'open', '2026-01-01T00:00:00Z'
        );
        """
    )
    connection.commit()
    connection.close()

    client = TestClient(create_app(db_path, ai_provider=GoodProvider(valid_recommendation(1))))
    ticket = client.get("/api/tickets").json()[0]
    assert ticket["reviewer_note"] == ""
    assert ticket["original_proposed_task"] == "Historical AI task"
    assert ticket["resolution_note"] == ""
    assert ticket["updated_at"] == ticket["created_at"]


def test_ai_citations_are_filtered_to_retrieved_document_text(monkeypatch, tmp_path):
    configure_ai(monkeypatch)
    provider = GoodProvider(
        {
            "category": "question",
            "summary": "Password reset",
            "suggested_reply": "Use Settings.",
            "proposed_task": "Verify password reset instructions.",
            "needs_review": False,
            "citations": [
                {"document_id": 1, "excerpt": "Reset the password from Settings."},
                {"document_id": 9999, "excerpt": "Invented document"},
                {"document_id": 1, "excerpt": "Invented unsupported quote"},
            ],
        }
    )
    client = make_client(tmp_path, provider)
    project = create_project(client)
    document = create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])

    response = client.post(f"/api/feedback/{feedback['id']}/analyze")
    assert response.status_code == 200
    analysis = response.json()
    assert analysis["model_mode"] == "ai"
    assert [e["document_id"] for e in analysis["evidence"]] == [document["id"]]
    assert analysis["needs_review"] is True
    assert provider.calls == 2
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert [trace["step"] for trace in traces] == ["retrieval", "model", "tool", "model"]
    model_detail = json.loads(traces[-1]["detail"])
    assert model_detail["rejected_citations"] == 2


def test_agent_search_tool_is_validated_and_recorded(monkeypatch, tmp_path):
    configure_ai(monkeypatch)
    provider = SequenceProvider(
        {"tool": "search_documents", "arguments": {"query": "password"}},
        valid_recommendation(1),
    )
    client = make_client(tmp_path, provider)
    project = create_project(client)
    create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])

    response = client.post(f"/api/feedback/{feedback['id']}/analyze")
    assert response.status_code == 200
    assert response.json()["model_mode"] == "ai"
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert [trace["step"] for trace in traces] == ["retrieval", "model", "tool", "model"]
    tool_trace = json.loads(traces[2]["detail"])
    assert tool_trace["tool"] == "search_documents"
    assert tool_trace["fallback"] is False
    assert tool_trace["arguments"] == {"query": "password"}
    assert provider.calls == 2


def test_agent_assignment_count_tool_is_read_only_and_bounded(monkeypatch, tmp_path):
    configure_ai(monkeypatch)
    valid_provider = SequenceProvider(
        {
            "tool": "check_assignment_counts",
            "arguments": {"participant_count": 3, "task_counts": [2, 1]},
        },
        valid_recommendation(1),
    )
    client = make_client(tmp_path / "valid", valid_provider)
    project = create_project(client)
    create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])

    response = client.post(f"/api/feedback/{feedback['id']}/analyze")
    assert response.status_code == 200
    assert response.json()["model_mode"] == "ai"
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    tool_trace = json.loads(traces[2]["detail"])
    assert tool_trace["tool"] == "check_assignment_counts"
    assert tool_trace["result"] == {
        "assigned_total": 3,
        "valid": True,
        "difference": 0,
    }
    assert client.get(f"/api/tickets?project_id={project['id']}").json() == []

    invalid_provider = SequenceProvider(
        {
            "tool": "check_assignment_counts",
            "arguments": {"participant_count": 3, "task_counts": [2, 2]},
        },
        valid_recommendation(1),
    )
    invalid_client = make_client(tmp_path / "invalid", invalid_provider)
    invalid_project = create_project(invalid_client)
    create_document(invalid_client, invalid_project["id"])
    invalid_feedback = create_feedback(invalid_client, invalid_project["id"])
    invalid_response = invalid_client.post(f"/api/feedback/{invalid_feedback['id']}/analyze")
    assert invalid_response.status_code == 200
    invalid_traces = invalid_client.get(f"/api/traces?feedback_id={invalid_feedback['id']}").json()
    invalid_tool_trace = json.loads(invalid_traces[2]["detail"])
    assert invalid_tool_trace["result"] == {
        "assigned_total": 4,
        "valid": False,
        "difference": 1,
    }


def test_malformed_agent_plan_falls_back_without_executing_write(monkeypatch, tmp_path):
    configure_ai(monkeypatch)
    provider = SequenceProvider(
        {"tool": "delete_ticket", "arguments": {"ticket_id": 1}},
        valid_recommendation(1),
    )
    client = make_client(tmp_path, provider)
    project = create_project(client)
    create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])

    response = client.post(f"/api/feedback/{feedback['id']}/analyze")
    assert response.status_code == 200
    assert response.json()["model_mode"] == "ai"
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert [trace["step"] for trace in traces] == ["retrieval", "model", "tool", "model"]
    plan_trace = json.loads(traces[1]["detail"])
    fallback_trace = json.loads(traces[2]["detail"])
    assert plan_trace["phase"] == "tool_plan"
    assert plan_trace["status"] == "malformed"
    assert fallback_trace["fallback"] is True
    assert fallback_trace["fallback_reason"] == "validation_error"
    assert client.get(f"/api/tickets?project_id={project['id']}").json() == []


def test_ai_provider_failure_does_not_create_fake_result(monkeypatch, tmp_path):
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "http://provider.test/v1")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")

    class BrokenProvider:
        def complete(self, **kwargs):
            raise RuntimeError("failure")

    client = make_client(tmp_path, BrokenProvider())
    project = create_project(client)
    create_document(client, project["id"])
    feedback = create_feedback(client, project["id"])
    analysis = client.post(f"/api/feedback/{feedback['id']}/analyze").json()
    assert analysis["model_mode"] == "unavailable"
    assert analysis["evidence"] == []
    traces = client.get(f"/api/traces?feedback_id={feedback['id']}").json()
    assert traces[-1]["step"] == "error"
