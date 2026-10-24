import json
import os
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from server.demo import seed_demo
from server.main import create_app

ROOT = Path(__file__).resolve().parents[2]


def test_direct_module_startup_and_offline_replay(tmp_path):
    code = '''
import main
from demo import seed_demo
from fastapi.testclient import TestClient
app = main.create_app(offline=True)
seed_demo(app.state.db)
client = TestClient(app)
assert client.get('/api/model-settings').status_code == 200
row = next(row for row in client.get('/api/feedback').json() if 'known-07' in row['source'])
result = client.post(f"/api/feedback/{row['id']}/analyze")
assert result.status_code == 200 and result.json()['model_mode'] == 'demo'
'''
    result = subprocess.run(
        [sys.executable, '-c', code], cwd=ROOT / 'server',
        env={**os.environ, 'FEEDBACK_OFFLINE': '1', 'DATABASE_PATH': str(tmp_path / 'direct.db')},
        capture_output=True, timeout=20,
    )
    assert result.returncode == 0, result.stderr.decode(errors='replace')


def test_offline_complete_workflow_without_network(monkeypatch, tmp_path):
    def forbidden(*args, **kwargs):
        raise AssertionError("Offline replay attempted network")
    monkeypatch.setattr("server.ai.urlopen", forbidden)
    app = create_app(tmp_path / "demo.db", offline=True)
    seed_demo(app.state.db)
    seed_demo(app.state.db)
    client = TestClient(app)
    assert client.get("/api/health").json()["demo_mode"] is True
    assert client.get("/api/health").json()["ai_configured"] is False
    assert len(client.get("/api/projects").json()) == 1
    rows = client.get("/api/feedback").json()
    assert len(rows) == 3
    known = next(row for row in rows if "known-07" in row["source"])
    response = client.post(f"/api/feedback/{known['id']}/analyze")
    assert response.json()["model_mode"] == "demo"
    assert "演示数据" in response.json()["suggested_reply"]
    ticket = client.post(f"/api/feedback/{known['id']}/approve").json()
    assert client.post(f"/api/feedback/{known['id']}/approve").json() == ticket
    assert client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done"}).status_code == 422
    assert client.patch(f"/api/tickets/{ticket['id']}", json={"status": "done", "resolution_note": "离线验收完成"}).json()["status"] == "done"
    unknown = next(row for row in rows if "unknown" in row["source"])
    assert client.post(f"/api/feedback/{unknown['id']}/analyze").json()["model_mode"] == "unavailable"
    assert client.post(f"/api/feedback/{unknown['id']}/approve").status_code == 409
    metrics = client.get("/api/metrics").json()
    assert metrics["model_calls"] == metrics["total_tokens"] == metrics["ai_analyses"] == 0
    traces = client.get(f"/api/traces?feedback_id={known['id']}").json()
    assert sum(row["step"] == "replay" for row in traces) == 2
    # Replay analyses must never become approvable in live mode.
    live = TestClient(create_app(tmp_path / "demo.db"))
    with app.state.db.transaction() as conn:
        conn.execute("DELETE FROM tickets")
    assert live.post(f"/api/feedback/{known['id']}/approve").status_code == 409


def test_static_delivery_serves_api_and_ui_without_path_leaks(tmp_path):
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("<title>Signal offline</title>")
    (web / "main.js").write_text("console.log('offline')")
    client = TestClient(create_app(tmp_path / "static.db", offline=True, static_dir=web))
    assert "Signal offline" in client.get("/").text
    assert client.get("/main.js").headers["content-type"].startswith("text/javascript")
    assert client.get("/api/health").json()["demo_mode"]
    assert client.get("/api/missing").status_code == 404
    assert client.get("/server/.env").status_code == 404
    assert client.get("/missing.js").status_code == 404


def test_all_fixed_questions_have_honest_replay_outcomes(tmp_path):
    app = create_app(tmp_path / "suite.db", offline=True)
    seed_demo(app.state.db)
    client = TestClient(app)
    project_id = client.get("/api/projects").json()[0]["id"]
    cases = json.loads((ROOT / "examples/eval_cases.json").read_text(encoding="utf-8"))["cases"]
    for case in cases:
        row = client.post("/api/feedback", json={"project_id": project_id, "source": "offline-test", "content": case["question"]}).json()
        result = client.post(f"/api/feedback/{row['id']}/analyze").json()
        assert result["model_mode"] == ("demo" if case.get("expected_document") else "unavailable"), case["id"]
