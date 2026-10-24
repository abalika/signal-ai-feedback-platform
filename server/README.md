# Backend

From the project root, keep Python dependencies inside the project and install them with:

```powershell
python -m venv server/.venv
server/.venv/Scripts/python.exe -m pip install -r server/requirements-lock.txt
```

Then start the API from `server/` with:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --reload --port 8000
```

This is a localhost portfolio demo. It has no user authentication or access-control layer, so keep it bound to `127.0.0.1`. Do not expose this server to a LAN or the public Internet until authentication, per-user project authorization, deployment secrets, HTTPS, and production storage have been added.

The default SQLite file is `server/data/app.db` when the command is run from
the `server` directory. Set `DATABASE_PATH` to use another file. The API has
no seed data: create a project and add documents/feedback through the API.

AI analysis stays in explicit unavailable mode until all of these environment
variables are set:

```powershell
$env:OPENAI_API_KEY="<your-provider-key>"
$env:OPENAI_BASE_URL="http://127.0.0.1:7863/v1"
$env:OPENAI_MODEL="cn:deepseek-v4.1-flash"
```

The configured endpoint must be OpenAI-compatible; the service appends
`/chat/completions` itself. A direct cloud provider can be used by replacing
the base URL and model ID with that provider's documented values. Keep the
real key in your local environment or a secret manager; never commit it to
this repository. The analyzer makes two
JSON chat-completions calls: a constrained read-only tool choice followed by
the cited recommendation. Each model trace stores only an allow-list of safe
observability fields: phase, status, bounded elapsed milliseconds, returned
model identifier, and provider token counts when available. Prompts, raw
response bodies, API keys, and reasoning content are never copied to traces.

For local setup, copy `server/.env.example` to `server/.env` and replace the
placeholder key. The backend loads that file with `python-dotenv`; an already
exported environment variable takes precedence. No real provider key is
needed for the test suite.

Use `POST /api/feedback/{id}/analyze` to create or refresh an analysis. A
reviewer must then call `POST /api/feedback/{id}/approve` before a ticket is
created. The request body is optional; a reviewer may override the proposed
ticket title and leave a bounded note:

```json
{
  "title": "Password reset instructions need verification",
  "reviewer_note": "Confirmed this requires a documentation update."
}
```

When omitted, `title` uses the AI `proposed_task`. The created ticket keeps
the final title, the reviewer note, and an immutable
`original_proposed_task` snapshot for audit. Repeating approval returns the
existing ticket and never overwrites the original review or creates another
trace. A successful first approval adds a `review` trace containing only
field lengths and the title source; free-text review content is not copied to
the trace.

Tickets use a monotonic lifecycle. Use `PATCH /api/tickets/{id}` to move an
`open` ticket to `in_progress` or `done`, or an `in_progress` ticket to `done`:

```json
{
  "status": "done",
  "resolution_note": "Verified the fix in the local demo."
}
```

Completing a ticket requires a non-empty, bounded `resolution_note`. Moving a
ticket backwards, changing a completed ticket, or using an unknown status is
rejected. Repeating the current status is idempotent: it returns the existing
ticket and does not update its timestamp or create another trace. A real
transition persists `resolution_note` and `updated_at`, and adds one
`ticket_status` trace containing only the source status, target status, and
resolution-note length; the note text is never copied into the trace. The
SQLite startup migration adds these ticket fields to existing databases and
backfills `updated_at` from `created_at`.

Module layout:

- `main.py` wires FastAPI routes, transactions, and the public API contract.
- `db.py` contains the SQLite schema, connection/transaction helpers, and trace writes.
- `schemas.py` contains request/response models and persisted-row conversion.
- `retrieval.py` contains deterministic Chinese/English BM25 ranking and safe diagnostics.
- `ai.py` contains provider configuration, bounded tool selection, and citation validation; it never writes to SQLite.
