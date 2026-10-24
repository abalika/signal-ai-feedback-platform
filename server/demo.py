"""Explicit fixture replay for offline workflow demos, never a model substitute."""

import json
from pathlib import Path

try:
    from .ai import TOOL_PLAN_PROMPT
    from .db import utc_now
except ImportError:  # `cd server; uvicorn main:app`
    from ai import TOOL_PLAN_PROMPT
    from db import utc_now

ROOT = Path(__file__).resolve().parents[1]


class ReplayProvider:
    """Only fixed questions replay fixture answers. Unknown input fails closed."""

    def complete(self, *, system_prompt, user_prompt, settings):
        question = user_prompt.split("用户反馈内容：", 1)[1].split("\n\n", 1)[0]
        if system_prompt == TOOL_PLAN_PROMPT:
            return json.dumps({"tool": "search_documents", "arguments": {"query": question[:500]}})
        fixture = json.loads((ROOT / "examples/eval_cases.json").read_text(encoding="utf-8"))
        case = next((item for item in fixture["cases"] if item["question"] == question), None)
        if case is None or not case.get("expected_document"):
            # The API turns unsupported responses into an unavailable result;
            # it cannot create a ticket from an invented answer.
            return "{}"
        import re
        blocks = re.findall(r"\[DOCUMENT_ID=(\d+)\] ([^\n]+)\n(.*?)(?=\n\n\[DOCUMENT_ID=|\Z)", user_prompt, re.S)
        match = next((block for block in blocks if block[1] == case["expected_document"]), None)
        if match is None:
            return "{}"
        return json.dumps({
            "category": "question", "summary": "【离线固定回放】" + question,
            "suggested_reply": "【演示数据，非模型输出】" + case["reference_answer"],
            "proposed_task": "【演示工单】人工核验：" + question,
            "needs_review": True,
            "citations": [{"document_id": int(match[0]), "excerpt": match[2].strip()[:250]}],
        }, ensure_ascii=False)


def seed_demo(db):
    """Idempotent, explicit demo data only; refuses to add to an existing DB."""
    if db.fetchone("SELECT id FROM projects LIMIT 1"):
        return
    fixture = json.loads((ROOT / "examples/eval_cases.json").read_text(encoding="utf-8"))
    with db.transaction() as conn:
        project_id = conn.execute(
            "INSERT INTO projects(name, description, created_at) VALUES (?, ?, ?)",
            ("一按即定 · 离线演示", "固定题集回放，不调用模型。数据仅用于操作演示。", utc_now()),
        ).lastrowid
        for path in sorted((ROOT / "examples/miniapp").glob("*.md")):
            conn.execute("INSERT INTO documents(project_id, title, content, created_at) VALUES (?, ?, ?, ?)",
                         (project_id, path.name, path.read_text(encoding="utf-8"), utc_now()))
        for case in fixture["cases"]:
            if case["id"] in {"known-07", "known-21", "unknown-01"}:
                conn.execute("INSERT INTO feedback(project_id, source, content, status, created_at) VALUES (?, ?, ?, 'new', ?)",
                             (project_id, "离线演示 · " + case["id"], case["question"], utc_now()))
