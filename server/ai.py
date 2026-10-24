"""Bounded AI workflow used by the feedback analysis route.

This module contains no database writes.  It retrieves bounded document
context, validates a model-selected read-only tool, and validates every final
document citation against the text shown to the model.  The API route owns
the persistence transaction and trace writes.
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

try:  # Keep `uvicorn main:app` usable when launched from server/ directly.
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - requirements include python-dotenv
    load_dotenv = None

try:
    from .schemas import AnalysisOut, EvidenceOut
    from .retrieval import MAX_RETRIEVED_DOCUMENTS, retrieval_diagnostics, retrieve_documents
except ImportError:  # pragma: no cover - direct-module compatibility
    from schemas import AnalysisOut, EvidenceOut
    from retrieval import MAX_RETRIEVED_DOCUMENTS, retrieval_diagnostics, retrieve_documents


MAX_DOCUMENT_CHARS = 4_000
MAX_FEEDBACK_CHARS = 8_000
MODEL_TIMEOUT_SECONDS = 35
MAX_TRACE_MODEL_CHARS = 120
MAX_TRACE_TOKEN_COUNT = 10_000_000
MAX_TRACE_ELAPSED_MS = 10 * 60 * 1_000

if load_dotenv is not None and os.getenv("FEEDBACK_OFFLINE") != "1":
    load_dotenv(Path(__file__).resolve().parent / ".env", override=False)


@dataclass(frozen=True)
class AISettings:
    api_key: str = field(repr=False)
    base_url: str
    model: str

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.base_url and self.model)


class NoCredentialRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward Authorization to a redirect destination.
        return None


def urlopen(request, *, timeout):
    return build_opener(NoCredentialRedirect()).open(request, timeout=timeout)


def get_ai_settings() -> AISettings:
    return AISettings(
        api_key=os.getenv("OPENAI_API_KEY", "").strip(),
        base_url=os.getenv("OPENAI_BASE_URL", "").strip(),
        model=os.getenv("OPENAI_MODEL", "").strip(),
    )


class AIProvider(Protocol):
    def complete(self, *, system_prompt: str, user_prompt: str, settings: AISettings) -> str:
        """Return the model's raw message content."""


def _bounded_nonnegative_int(value: Any, maximum: int) -> int | None:
    """Keep provider metadata numeric, finite, and small enough for a trace."""

    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return min(max(value, 0), maximum)


def _safe_model_identifier(value: Any) -> str | None:
    """Return a bounded model label without copying arbitrary response data."""

    if not isinstance(value, str):
        return None
    value = value.strip()
    return value[:MAX_TRACE_MODEL_CHARS] or None


def model_trace_fields(
    value: Any,
    *,
    configured_model: str,
    elapsed_ms: int,
) -> dict[str, Any]:
    """Build the allow-listed metadata persisted for one model call.

    Providers injected by tests and local integrations historically return a
    plain string.  Such values still get the configured model and measured
    elapsed time; richer :class:`ModelCompletion` values add only the small
    usage/model allow-list below.
    """

    fields: dict[str, Any] = {
        "model": _safe_model_identifier(configured_model) or "unknown",
        "elapsed_ms": _bounded_nonnegative_int(elapsed_ms, MAX_TRACE_ELAPSED_MS) or 0,
    }
    metadata = getattr(value, "metadata", None)
    if not isinstance(metadata, Mapping):
        return fields

    actual_model = _safe_model_identifier(metadata.get("model"))
    if actual_model:
        fields["model"] = actual_model
    for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
        token_count = _bounded_nonnegative_int(metadata.get(name), MAX_TRACE_TOKEN_COUNT)
        if token_count is not None:
            fields[name] = token_count
    return fields


class ModelCompletion(str):
    """String-compatible model content carrying safe response metadata.

    Returning a ``str`` subclass preserves the existing provider contract for
    callers that pass the result directly to ``json.loads`` or compare it to
    a string, while the API route can inspect ``metadata`` for observability.
    """

    def __new__(
        cls,
        content: str,
        *,
        model: Any = None,
        usage: Any = None,
        elapsed_ms: Any = None,
    ) -> "ModelCompletion":
        instance = str.__new__(cls, content)
        metadata: dict[str, Any] = {}
        safe_model = _safe_model_identifier(model)
        if safe_model:
            metadata["model"] = safe_model
        if isinstance(usage, Mapping):
            for name in ("prompt_tokens", "completion_tokens", "total_tokens"):
                token_count = _bounded_nonnegative_int(usage.get(name), MAX_TRACE_TOKEN_COUNT)
                if token_count is not None:
                    metadata[name] = token_count
        safe_elapsed = _bounded_nonnegative_int(elapsed_ms, MAX_TRACE_ELAPSED_MS)
        if safe_elapsed is not None:
            metadata["elapsed_ms"] = safe_elapsed
        instance.metadata = metadata
        return instance


class ProviderError(RuntimeError):
    """A provider failure with a safe code; response bodies and credentials stay private."""

    def __init__(self, code: str, *, elapsed_ms: Any = None):
        super().__init__(code)
        self.code = code
        self.elapsed_ms = _bounded_nonnegative_int(elapsed_ms, MAX_TRACE_ELAPSED_MS)


class OpenAICompatibleProvider:
    """Small dependency-free client for OpenAI-compatible chat APIs."""

    @staticmethod
    def _endpoint(base_url: str) -> str:
        base = base_url.rstrip("/")
        return base if base.endswith("/chat/completions") else f"{base}/chat/completions"

    def complete(self, *, system_prompt: str, user_prompt: str, settings: AISettings) -> str:
        started = time.perf_counter()
        payload = {
            "model": settings.model,
            "temperature": 0,
            "max_tokens": 1_200,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "response_format": {"type": "json_object"},
        }
        # DeepSeek defaults to high-effort thinking. These short JSON planning
        # and recommendation calls need a bounded final answer, not a long
        # reasoning trace that can exhaust max_tokens before content appears.
        if "api.deepseek.com" in settings.base_url or "deepseek" in settings.model.lower():
            payload["thinking"] = {"type": "disabled"}
        request = Request(
            self._endpoint(settings.base_url),
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {settings.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        # One short retry handles transient transport faults and the occasional
        # empty JSON content documented by DeepSeek. Never retry auth errors.
        for attempt in range(2):
            try:
                with urlopen(request, timeout=MODEL_TIMEOUT_SECONDS) as response:
                    raw = response.read().decode("utf-8")
            except HTTPError as exc:
                if attempt == 0 and exc.code in {429, 500, 502, 503, 504}:
                    time.sleep(1)
                    continue
                raise ProviderError(
                    f"http_{exc.code}", elapsed_ms=round((time.perf_counter() - started) * 1_000)
                ) from exc
            except (URLError, TimeoutError, OSError) as exc:
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise ProviderError(
                    "network_error", elapsed_ms=round((time.perf_counter() - started) * 1_000)
                ) from exc

            try:
                data = json.loads(raw)
                content = data["choices"][0]["message"]["content"]
            except (ValueError, KeyError, IndexError, TypeError) as exc:
                raise ProviderError(
                    "invalid_response", elapsed_ms=round((time.perf_counter() - started) * 1_000)
                ) from exc
            if isinstance(content, list):
                content = "".join(
                    item["text"] for item in content
                    if isinstance(item, Mapping) and isinstance(item.get("text"), str)
                )
            if not isinstance(content, str) or not content.strip():
                if attempt == 0:
                    time.sleep(1)
                    continue
                raise ProviderError(
                    "empty_content", elapsed_ms=round((time.perf_counter() - started) * 1_000)
                )
            usage = data.get("usage") if isinstance(data, Mapping) else None
            return ModelCompletion(
                content,
                model=data.get("model") if isinstance(data, Mapping) else None,
                usage=usage,
                elapsed_ms=round((time.perf_counter() - started) * 1_000),
            )
        raise ProviderError(
            "retry_exhausted", elapsed_ms=round((time.perf_counter() - started) * 1_000)
        )  # pragma: no cover


def clean_text(value: str) -> str:
    return " ".join(value.split())


def safe_excerpt(content: str, max_chars: int = 300) -> str:
    content = clean_text(content)
    return content[:max_chars] + ("…" if len(content) > max_chars else "")


def validate_tool_plan(value: Any) -> tuple[str, dict[str, Any]]:
    """Validate the model's one-step, read-only tool choice."""

    if not isinstance(value, Mapping):
        raise ValueError("tool plan must be an object")
    tool_name = value.get("tool", value.get("tool_name", value.get("name")))
    arguments = value.get("arguments", value.get("args", {}))
    if not isinstance(tool_name, str) or tool_name not in {"search_documents", "check_assignment_counts"}:
        raise ValueError("unsupported tool")
    if not isinstance(arguments, Mapping):
        raise ValueError("tool arguments must be an object")
    args = dict(arguments)

    if tool_name == "search_documents":
        query = args.get("query")
        if not isinstance(query, str) or not query.strip() or len(query.strip()) > 500:
            raise ValueError("search_documents requires a bounded query")
        return tool_name, {"query": query.strip()}

    participant_count = args.get("participant_count")
    if isinstance(participant_count, bool) or not isinstance(participant_count, int):
        raise ValueError("participant_count must be an integer")
    if not 1 <= participant_count <= 1_000:
        raise ValueError("participant_count is outside the allowed range")
    task_counts = args.get("task_counts")
    if isinstance(task_counts, Mapping):
        counts = list(task_counts.values())
    elif isinstance(task_counts, list):
        counts = task_counts
    else:
        raise ValueError("task_counts must be a list or object")
    if not 1 <= len(counts) <= 6:
        raise ValueError("task_counts must contain one to six task counts")
    if any(isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 1_000 for count in counts):
        raise ValueError("task_counts must contain bounded positive integers")
    return "check_assignment_counts", {
        "participant_count": participant_count,
        "task_counts": counts,
    }


def run_tool(
    tool_name: str,
    arguments: dict[str, Any],
    documents: list[sqlite3.Row],
    fallback_documents: list[sqlite3.Row],
) -> tuple[list[sqlite3.Row], dict[str, Any]]:
    """Run one validated, deterministic read-only tool."""

    if tool_name == "search_documents":
        selected = retrieve_documents(documents, arguments["query"])
        return selected, {
            "tool": tool_name,
            "arguments": arguments,
            "document_ids": [int(row["id"]) for row in selected],
            **retrieval_diagnostics(documents, arguments["query"]),
        }

    counts = list(arguments["task_counts"])
    assigned_total = sum(counts)
    return fallback_documents, {
        "tool": tool_name,
        "arguments": arguments,
        "result": {
            "assigned_total": assigned_total,
            "valid": assigned_total == arguments["participant_count"],
            "difference": assigned_total - arguments["participant_count"],
        },
        "document_ids": [int(row["id"]) for row in fallback_documents],
    }


def parse_json_object(raw: str) -> dict[str, Any]:
    text = raw.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE | re.DOTALL).strip()
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("model response was not valid JSON") from exc
    if not isinstance(value, dict):
        raise ValueError("model response was not a JSON object")
    return value


def as_text(value: Any, fallback: str = "") -> str:
    return value.strip() if isinstance(value, str) else fallback


def validated_evidence(
    value: Any, documents_by_id: dict[int, sqlite3.Row]
) -> tuple[list[EvidenceOut], int]:
    if not isinstance(value, list):
        return [], 0
    evidence: list[EvidenceOut] = []
    rejected = 0
    seen: set[int] = set()
    for item in value[:MAX_RETRIEVED_DOCUMENTS]:
        if not isinstance(item, Mapping):
            rejected += 1
            continue
        raw_id = item.get("document_id", item.get("id"))
        try:
            document_id = int(raw_id)
        except (TypeError, ValueError):
            rejected += 1
            continue
        row = documents_by_id.get(document_id)
        excerpt = as_text(item.get("excerpt"))
        normalized_excerpt = clean_text(excerpt)
        normalized_content = clean_text(row["content"]) if row is not None else ""
        # A citation is accepted only when its ID belongs to retrieved
        # documents and the quoted text is present in that document.
        if row is None or not normalized_excerpt or normalized_excerpt not in normalized_content:
            rejected += 1
            continue
        if document_id in seen:
            continue
        seen.add(document_id)
        evidence.append(
            EvidenceOut(
                document_id=document_id,
                title=str(row["title"]),
                excerpt=excerpt[:500],
            )
        )
    return evidence, rejected


def unavailable_analysis(feedback_id: int, reason: str) -> AnalysisOut:
    return AnalysisOut(
        feedback_id=feedback_id,
        category="unresolved",
        summary=reason,
        suggested_reply="暂时无法生成有依据的回复，请由人工核实后处理。",
        proposed_task="人工核实用户反馈并补充处理记录。",
        evidence=[],
        needs_review=True,
        model_mode="unavailable",
    )


SYSTEM_PROMPT = """你是软件产品支持团队的反馈分析助手。你只能使用提供的项目文档与只读工具结果，不能补充之外的事实。
输出严格的 JSON 对象，不要输出 Markdown：
{"category":"bug|question|feature|other","summary":"问题摘要","suggested_reply":"给用户的建议回复","proposed_task":"内部待办","citations":[{"document_id":1,"excerpt":"必须原样摘录文档中的连续文字"}],"needs_review":true}
回答当前反馈，保持简短；不要加入与问题无关的玩法、测试或历史说明。
citations 只引用直接支持核心答案的 1 到 2 段原文，不能为了凑引用加入无关内容；excerpt 必须是给出的文档中的连续原文。
check_assignment_counts 的 valid=true 只说明任务人数之和符合参与者人数。任务名称未提供或未核对时，不得说“可以开始分配”；须提醒名称仍需填写。
资料没有用户量、营收、上架日期或设备结论时明确说未知。不要从“无后端”等其他事实推断这些业务数据。
不要声称已经联系、转交、调查、修复或回复某人，除非工具结果明确显示该动作已经发生。proposed_task 是待办建议，不代表已执行。
信息不足时 needs_review 必须为 true。"""

TOOL_PLAN_PROMPT = """你是一个受限的反馈处理 Agent。根据用户反馈，从允许的工具中选择且只选择一个。
只输出 JSON，不要输出 Markdown：
{"tool":"search_documents","arguments":{"query":"与反馈相关的检索词"}}
或：
{"tool":"check_assignment_counts","arguments":{"participant_count":3,"task_counts":[2,1]}}
允许的工具只有 search_documents 和 check_assignment_counts。不要使用其他工具，不要写入数据。
check_assignment_counts 的 task_counts 表示每个任务分配的人数，必须是 1 到 6 个正整数；后端会核对其总和是否等于 participant_count。"""


def build_tool_plan_prompt(feedback: sqlite3.Row, documents: list[sqlite3.Row]) -> str:
    catalog = "\n".join(
        f"- DOCUMENT_ID={row['id']} {row['title']}: {safe_excerpt(str(row['content']), 220)}"
        for row in documents[:MAX_RETRIEVED_DOCUMENTS]
    )
    return (
        f"用户反馈来源：{feedback['source']}\n"
        f"用户反馈内容：{str(feedback['content'])[:MAX_FEEDBACK_CHARS]}\n\n"
        "项目文档目录：\n"
        f"{catalog}\n\n"
        "请根据反馈选择一个允许的工具。"
    )


def build_recommendation_prompt(
    feedback: sqlite3.Row,
    documents: list[sqlite3.Row],
    *,
    tool_name: str,
    tool_result: dict[str, Any],
) -> str:
    blocks = []
    for document in documents:
        blocks.append(
            f"[DOCUMENT_ID={document['id']}] {document['title']}\n"
            f"{str(document['content'])[:MAX_DOCUMENT_CHARS]}"
        )
    return (
        f"用户反馈来源：{feedback['source']}\n"
        f"用户反馈内容：{str(feedback['content'])[:MAX_FEEDBACK_CHARS]}\n\n"
        f"本轮已执行只读工具 {tool_name}，工具结果如下：\n"
        f"{json.dumps(tool_result, ensure_ascii=False)}\n\n"
        "以下是检索到的项目文档：\n"
        + "\n\n".join(blocks)
    )
