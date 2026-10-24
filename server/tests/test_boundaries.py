"""Contract boundaries and persistence faults; all data is temporary."""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from server.db import Database
from server.main import create_app


@pytest.fixture
def client(tmp_path):
    return TestClient(create_app(tmp_path / "boundaries.db"))


@pytest.mark.parametrize("value", ["", " ", "\n\t", "x" * 121, None, [], {}])
def test_project_invalid_name_is_rejected_without_write(client, value):
    assert client.post("/api/projects", json={"name": value}).status_code == 422
    assert client.get("/api/projects").json() == []


@pytest.mark.parametrize("route,field,limit,base", [
    ("projects", "name", 120, {}),
    ("projects", "description", 2000, {"name": "P"}),
    ("documents", "title", 200, {"content": "body"}),
    ("documents", "content", 100000, {"title": "Doc"}),
    ("feedback", "source", 100, {"content": "body"}),
    ("feedback", "content", 20000, {"source": "test"}),
])
def test_exact_limit_accepted_and_one_extra_rejected(client, route, field, limit, base):
    payload = dict(base)
    if route != "projects":
        payload["project_id"] = client.post("/api/projects", json={"name": "P"}).json()["id"]
    payload[field] = "界" * limit
    assert client.post(f"/api/{route}", json=payload).status_code == 201
    payload[field] += "界"
    assert client.post(f"/api/{route}", json=payload).status_code == 422
    assert len(client.get(f"/api/{route}").json()) == 1


@pytest.mark.parametrize("route", ["documents", "feedback", "tickets", "metrics"])
@pytest.mark.parametrize("project_id,status", [(0, 422), (-1, 422), (999999, 404), ("oops", 422)])
def test_project_filter_rejects_invalid_or_unknown_ids(client, route, project_id, status):
    assert client.get(f"/api/{route}?project_id={project_id}").status_code == status


@pytest.mark.parametrize("method,path", [
    ("post", "/api/feedback/999/analyze"),
    ("post", "/api/feedback/999/approve"),
    ("get", "/api/feedback/999/analysis"),
    ("get", "/api/traces?feedback_id=999"),
])
def test_missing_feedback_does_not_write(client, method, path):
    assert getattr(client, method)(path).status_code == 404
    assert client.get("/api/feedback").json() == []
    assert client.get("/api/tickets").json() == []


def test_sql_text_is_stored_as_data_and_unicode_is_preserved(client):
    name = "  项目🍀'; DROP TABLE projects;--  "
    row = client.post("/api/projects", json={"name": name}).json()
    assert row["name"] == name.strip()
    assert client.get("/api/projects").json() == [row]


def test_transaction_failure_rolls_back_and_releases_connection(tmp_path):
    db = Database(tmp_path / "rollback.db")
    with pytest.raises(sqlite3.IntegrityError):
        with db.transaction() as conn:
            conn.execute("INSERT INTO projects VALUES (1, 'P', '', 'now')")
            conn.execute("INSERT INTO feedback VALUES (1, 999, 'test', 'body', 'new', 'now')")
    assert db.fetchall("SELECT * FROM projects") == []
    with db.transaction() as conn:
        conn.execute("INSERT INTO projects VALUES (1, 'Recovered', '', 'now')")
    assert db.fetchone("SELECT name FROM projects")["name"] == "Recovered"


def test_concurrent_writes_keep_unique_ids_and_persist(tmp_path):
    path = tmp_path / "concurrent.db"
    app = create_app(path)
    def write(index):
        with TestClient(app) as local:
            response = local.post("/api/projects", json={"name": f"P-{index}"})
            assert response.status_code == 201
            return response.json()["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(write, range(12)))
    assert len(set(ids)) == 12
    assert len(TestClient(create_app(path)).get("/api/projects").json()) == 12
