# API contract (v0.1)

The web app calls the FastAPI service at `VITE_API_URL` (default `http://localhost:8000`). JSON responses use UTF-8. Every resource belongs to a project.

| Method | Path | Request | Response |
| --- | --- | --- | --- |
| GET | `/api/health` | — | `{status:"ok", ai_configured:boolean}` |
| GET | `/api/projects` | — | `Project[]` |
| POST | `/api/projects` | `{name,description}` | `Project` |
| GET | `/api/documents?project_id=1` | — | `Document[]` |
| POST | `/api/documents` | `{project_id,title,content}` | `Document` |
| GET | `/api/feedback?project_id=1` | — | `Feedback[]` |
| POST | `/api/feedback` | `{project_id,source,content}` | `Feedback` |
| POST | `/api/feedback/{id}/analyze` | — | `Analysis` |
| GET | `/api/feedback/{id}/analysis` | — | `Analysis` or `404` if never analyzed |
| POST | `/api/feedback/{id}/approve` | optional `{title,reviewer_note}` | `Ticket` |
| GET | `/api/tickets?project_id=1` | — | `Ticket[]` |
| PATCH | `/api/tickets/{id}` | `{status:"open"|"in_progress"|"done",resolution_note?}` | `Ticket` |
| GET | `/api/traces?feedback_id=1` | — | `Trace[]` |
| GET | `/api/metrics?project_id=1` | — | `Metrics` |

Types: `Project {id,name,description,created_at}`; `Document {id,project_id,title,content,created_at}`; `Feedback {id,project_id,source,content,status,created_at}`; `Analysis {feedback_id,category,summary,suggested_reply,proposed_task,evidence: Evidence[],needs_review,model_mode}`; `Evidence {document_id,title,excerpt}`; `Ticket {id,feedback_id,project_id,title,reviewer_note,original_proposed_task,status,resolution_note,created_at,updated_at}`; `Trace {id,feedback_id,step,detail,created_at}`; `Metrics {project_id,documents,feedback,analyses,ai_analyses,unavailable_analyses,tickets,completed_tickets,traces,model_calls,total_tokens,model_latency_p50_ms,model_latency_p95_ms,ai_to_ticket_rate}`.

`/api/metrics` returns counts and allow-listed numeric model telemetry only. It never exposes feedback text, prompts, model responses, reasoning content, or API keys. Omitting `project_id` returns an all-project aggregate.

`model_mode` is `ai` or `unavailable`. When no AI API is configured, `/analyze` returns an explicit unavailable response and must not pretend to be AI. An analysis does not mutate tickets. Approval writes a ticket only after the reviewer sees the proposed task; the first approval stores an immutable AI suggestion snapshot and optional human edits, while repeated approval is idempotent. No external communication or publishing occurs.

Ticket status transitions are monotonic: `open -> in_progress -> done`, with `open -> done` also allowed. Completing a ticket requires a non-empty resolution note. Repeating the current status is idempotent; completed tickets are terminal.
