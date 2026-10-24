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
# 网页模型设置（新增）

仅本机工作台可访问；以下所有响应均为 `Cache-Control: no-store`。GET 返回当前 Base URL、模型、`has_key`、固定掩码、`remembered`、`source`、`mode`、`csrf_token`，**不返回 API key**。

| 接口 | 行为 |
|---|---|
| `GET /api/model-settings` | 查询配置状态和本次后端会话令牌 |
| `POST /api/model-settings/test` | 用提交的 Base URL、model、api_key 发送一次短请求，返回延迟及五分钟有效的 `verification_token` |
| `PUT /api/model-settings` | 提交同一连接信息、验证令牌和 `remember`；保存成功后立即启用 |
| `POST /api/model-settings/offline` | 切回回放，保留网页密钥；已记住的配置持久化为离线模式 |
| `DELETE /api/model-settings` | 删除网页配置，切回离线，保留原环境变量 |

写请求须带 `X-Signal-Settings-Token`（GET 中取得的 `csrf_token`）。非本机 Host、不可信 Origin、会话失效返回 403。API key 留空仅能在地址不变时复用后端现有密钥；更换地址需重填。HTTP 只允许本机网关，其他地址使用 HTTPS，URL 不允许内嵌凭证、查询串或片段。

未经测试、配置变更或测试凭证过期返回 409；验证失败返回 422 且不回显输入；网关测试失败返回安全的 502；本机保存失败返回 503 并保留原配置。配置变更不会取消正在执行的分析，请求会沿用开始时的配置和模式。
