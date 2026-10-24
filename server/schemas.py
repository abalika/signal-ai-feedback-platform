"""Request and response schemas shared by API routes and AI helpers."""

from __future__ import annotations

import json
import sqlite3
from typing import Any
from typing import Literal

from pydantic import BaseModel, Field, field_validator


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2_000)

    @field_validator("name", "description", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class DocumentCreate(BaseModel):
    project_id: int = Field(gt=0)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)

    @field_validator("title", "content", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class FeedbackCreate(BaseModel):
    project_id: int = Field(gt=0)
    source: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=20_000)

    @field_validator("source", "content", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class ProjectOut(BaseModel):
    id: int
    name: str
    description: str
    created_at: str


class DocumentOut(BaseModel):
    id: int
    project_id: int
    title: str
    content: str
    created_at: str


class FeedbackOut(BaseModel):
    id: int
    project_id: int
    source: str
    content: str
    status: str
    created_at: str


class EvidenceOut(BaseModel):
    document_id: int
    title: str
    excerpt: str


class AnalysisOut(BaseModel):
    feedback_id: int
    category: str
    summary: str
    suggested_reply: str
    proposed_task: str
    evidence: list[EvidenceOut]
    needs_review: bool
    model_mode: str


class TicketApproval(BaseModel):
    """Optional reviewer overrides accepted when an AI suggestion is approved."""

    title: str | None = Field(default=None, min_length=1, max_length=240)
    reviewer_note: str = Field(default="", max_length=2_000)

    @field_validator("title", "reviewer_note", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class TicketStatusUpdate(BaseModel):
    """A monotonic ticket status transition requested by a reviewer."""

    status: Literal["open", "in_progress", "done"]
    resolution_note: str | None = Field(default=None, max_length=2_000)

    @field_validator("resolution_note", mode="before")
    @classmethod
    def normalize_resolution_note(cls, value: Any) -> Any:
        if isinstance(value, str):
            return value.strip()
        return value


class TicketOut(BaseModel):
    id: int
    feedback_id: int
    project_id: int
    title: str
    reviewer_note: str
    original_proposed_task: str
    status: str
    resolution_note: str
    created_at: str
    updated_at: str


class TraceOut(BaseModel):
    id: int
    feedback_id: int
    step: str
    detail: str
    created_at: str


class MetricsOut(BaseModel):
    """Aggregated operational evidence safe to expose in the local dashboard."""

    project_id: int | None
    documents: int
    feedback: int
    analyses: int
    ai_analyses: int
    unavailable_analyses: int
    tickets: int
    completed_tickets: int
    traces: int
    model_calls: int
    total_tokens: int
    model_latency_p50_ms: int | None
    model_latency_p95_ms: int | None
    ai_to_ticket_rate: float


def project_from_row(row: sqlite3.Row) -> ProjectOut:
    return ProjectOut(**dict(row))


def document_from_row(row: sqlite3.Row) -> DocumentOut:
    return DocumentOut(**dict(row))


def feedback_from_row(row: sqlite3.Row) -> FeedbackOut:
    return FeedbackOut(**dict(row))


def ticket_from_row(row: sqlite3.Row) -> TicketOut:
    return TicketOut(**dict(row))


def trace_from_row(row: sqlite3.Row) -> TraceOut:
    return TraceOut(**dict(row))


def analysis_from_row(row: sqlite3.Row) -> AnalysisOut:
    try:
        raw_evidence = json.loads(row["evidence_json"])
    except (TypeError, ValueError):
        raw_evidence = []
    evidence = [EvidenceOut(**item) for item in raw_evidence if isinstance(item, dict)]
    return AnalysisOut(
        feedback_id=int(row["feedback_id"]),
        category=str(row["category"]),
        summary=str(row["summary"]),
        suggested_reply=str(row["suggested_reply"]),
        proposed_task=str(row["proposed_task"]),
        evidence=evidence,
        needs_review=bool(row["needs_review"]),
        model_mode=str(row["model_mode"]),
    )
