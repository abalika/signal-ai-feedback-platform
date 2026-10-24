"""SQLite persistence primitives for the feedback-ticket API.

The application deliberately uses a small repository layer instead of an ORM:
the schema is easy to inspect for an internship reviewer, and every operation
can be traced to a short SQL statement.  Connections are short-lived while a
re-entrant lock serializes transactions in the local demo process.
"""

from __future__ import annotations

import sqlite3
import threading
from contextlib import closing, contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utc_now() -> str:
    """Return a stable UTC timestamp suitable for SQLite and JSON."""

    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Database:
    """SQLite persistence with one short-lived connection per operation."""

    def __init__(self, path: str | Path):
        requested_path = str(path)
        self._uri = requested_path == ":memory:"
        self.path = f"file:feedback_ticket_{id(self)}?mode=memory&cache=shared" if self._uri else requested_path
        self._lock = threading.RLock()
        self._anchor: sqlite3.Connection | None = None
        if self._uri:
            # A shared in-memory database disappears when its last connection
            # closes. Keep one private anchor while normal operations continue
            # to use short-lived connections.
            self._anchor = self._new_connection()
        else:
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self.initialize()

    def _new_connection(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, check_same_thread=False, timeout=30, uri=self._uri)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 30000")
        return connection

    def connect(self) -> sqlite3.Connection:
        return self._new_connection()

    def initialize(self) -> None:
        with self._lock, closing(self.connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS projects (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    name TEXT NOT NULL,
                    description TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS documents (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    source TEXT NOT NULL,
                    content TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'new',
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS analyses (
                    feedback_id INTEGER PRIMARY KEY REFERENCES feedback(id) ON DELETE CASCADE,
                    category TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    suggested_reply TEXT NOT NULL,
                    proposed_task TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    needs_review INTEGER NOT NULL,
                    model_mode TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feedback_id INTEGER NOT NULL UNIQUE REFERENCES feedback(id) ON DELETE CASCADE,
                    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                    title TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'open',
                    resolution_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL DEFAULT ''
                );
                CREATE TABLE IF NOT EXISTS traces (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    feedback_id INTEGER NOT NULL REFERENCES feedback(id) ON DELETE CASCADE,
                    step TEXT NOT NULL,
                    detail TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_documents_project ON documents(project_id);
                CREATE INDEX IF NOT EXISTS idx_feedback_project ON feedback(project_id);
                CREATE INDEX IF NOT EXISTS idx_tickets_project ON tickets(project_id);
                CREATE INDEX IF NOT EXISTS idx_traces_feedback ON traces(feedback_id);
                """
            )
            # ``tickets`` was part of the first released local schema. Keep
            # startup migration deliberately small and additive so an
            # existing portfolio database remains readable after the review
            # fields are introduced.
            self._ensure_column(
                connection,
                "tickets",
                "reviewer_note",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "tickets",
                "original_proposed_task",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "tickets",
                "resolution_note",
                "TEXT NOT NULL DEFAULT ''",
            )
            self._ensure_column(
                connection,
                "tickets",
                "updated_at",
                "TEXT NOT NULL DEFAULT ''",
            )
            # For tickets created before the snapshot column existed, the
            # matching analysis is the safest available historical source.
            # Never replace a non-empty snapshot supplied by a newer schema.
            connection.execute(
                """
                UPDATE tickets
                SET original_proposed_task = COALESCE(
                    NULLIF(original_proposed_task, ''),
                    (SELECT proposed_task FROM analyses
                     WHERE analyses.feedback_id = tickets.feedback_id),
                    ''
                )
                WHERE original_proposed_task IS NULL OR original_proposed_task = ''
                """
            )
            # ``updated_at`` was introduced after the original ticket schema.
            # Backfill it from the creation timestamp so legacy rows expose a
            # complete, stable TicketOut without pretending they were edited.
            connection.execute(
                """
                UPDATE tickets
                SET updated_at = created_at
                WHERE updated_at IS NULL OR updated_at = ''
                """
            )

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        """Add one known schema column without rebuilding the SQLite table."""

        columns = {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
        }
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            connection = self.connect()
            try:
                connection.execute("BEGIN IMMEDIATE")
                yield connection
                connection.commit()
            except Exception:
                connection.rollback()
                raise
            finally:
                connection.close()

    def fetchone(self, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with self._lock, closing(self.connect()) as connection:
            return connection.execute(query, params).fetchone()

    def fetchall(self, query: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with self._lock, closing(self.connect()) as connection:
            return list(connection.execute(query, params).fetchall())


def insert_trace(db: Database, feedback_id: int, step: str, detail: str) -> None:
    """Persist a bounded execution trace without exposing provider secrets."""

    with db.transaction() as connection:
        connection.execute(
            "INSERT INTO traces(feedback_id, step, detail, created_at) VALUES (?, ?, ?, ?)",
            (feedback_id, step, detail[:4_000], utc_now()),
        )
