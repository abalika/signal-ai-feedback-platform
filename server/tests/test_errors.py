import sqlite3

import pytest
from fastapi.testclient import TestClient

from server.main import create_app


@pytest.mark.parametrize("failure,status,code", [
    (sqlite3.OperationalError("locked /private/db secret"), 503, "database_unavailable"),
    (RuntimeError("private internal token"), 500, "internal_error"),
])
def test_storage_and_internal_errors_are_safe(monkeypatch, tmp_path, failure, status, code):
    app = create_app(tmp_path / "fault.db")
    def broken(*_args, **_kwargs):
        raise failure
    monkeypatch.setattr(app.state.db, "fetchall", broken)
    response = TestClient(app, raise_server_exceptions=False).get("/api/projects")
    assert response.status_code == status
    assert response.json()["code"] == code
    assert "private" not in response.text and "secret" not in response.text
