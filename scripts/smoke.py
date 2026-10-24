"""Start an isolated offline server, verify real HTTP delivery, then stop it."""
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]


def smoke():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    # Keep temporary files inside project (also works in an extracted package).
    (ROOT / "work").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="smoke-", dir=ROOT / "work") as folder:
        env = {**os.environ, "FEEDBACK_OFFLINE": "1", "PYTHONIOENCODING": "utf-8"}
        with open(Path(folder) / "server.log", "w", encoding="utf-8") as log:
            process = subprocess.Popen([sys.executable, str(ROOT / "scripts/serve.py"), "--port", str(port), "--database", str(Path(folder) / "isolated.db")], cwd=ROOT, env=env, stdout=log, stderr=log)
            def request(path, method="GET", body=None):
                data = json.dumps(body).encode() if body is not None else None
                req = Request(base + path, data=data, method=method, headers={"Content-Type": "application/json"})
                try:
                    with urlopen(req, timeout=4) as response:
                        return response.status, response.headers, response.read()
                except HTTPError as exc:
                    return exc.code, exc.headers, exc.read()
            def api(path, method="GET", body=None, status=200):
                actual, _, raw = request(path, method, body)
                assert actual == status, (path, actual, raw)
                return json.loads(raw)
            try:
                for _ in range(80):
                    if process.poll() is not None:
                        raise RuntimeError("Server exited before readiness")
                    try:
                        health = api("/api/health")
                        break
                    except OSError:
                        time.sleep(.15)
                else:
                    raise RuntimeError("Readiness timeout")
                assert health["demo_mode"] and not health["ai_configured"]
                status, _, raw = request("/")
                assert status == 200 and b"<html" in raw
                script = re.search(rb'<script[^>]+src="([^"]+\.js)"', raw).group(1).decode()
                status, headers, js = request(script)
                assert status == 200 and "javascript" in headers["Content-Type"] and len(js) > 100
                for path in ("/api/not-found", "/server/.env", "/../server/.env"):
                    assert request(path)[0] == 404
                rows = api("/api/feedback")
                known = next(row for row in rows if "known-07" in row["source"])
                unknown = next(row for row in rows if "unknown" in row["source"])
                assert api(f"/api/feedback/{known['id']}/analyze", "POST")["model_mode"] == "demo"
                ticket = api(f"/api/feedback/{known['id']}/approve", "POST")
                assert api(f"/api/feedback/{known['id']}/approve", "POST")["id"] == ticket["id"]
                api(f"/api/tickets/{ticket['id']}", "PATCH", {"status": "done"}, 422)
                assert api(f"/api/tickets/{ticket['id']}", "PATCH", {"status": "done", "resolution_note": "Offline smoke passed"})["status"] == "done"
                assert api(f"/api/feedback/{unknown['id']}/analyze", "POST")["model_mode"] == "unavailable"
                api(f"/api/feedback/{unknown['id']}/approve", "POST", status=409)
                assert api("/api/metrics")["model_calls"] == 0
                print("PASS: HTTP UI/JS MIME, isolated replay, review, idempotency, resolution, safe rejection, zero model calls")
            finally:
                # Windows venv redirector launches a child interpreter. Stop the
                # entire tree we created, otherwise the port/log stay locked.
                if os.name == "nt" and process.poll() is None:
                    subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
                elif process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    smoke()
