"""Reproducible offline workflow + retrieval gate. Never calls a model."""
from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import statistics
import subprocess
import sys
import tempfile
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ["FEEDBACK_OFFLINE"] = "1"
CATEGORIES = ("retrieval", "evidence_format", "unknown_safety", "workflow_runtime")
LABELS = dict(zip(CATEGORIES, ("检索", "证据 / 格式", "未知问题安全拒绝", "工作流 / 运行错误")))


def fingerprint():
    paths = [ROOT / "examples/eval_cases.json", *sorted((ROOT / "examples/miniapp").glob("*.md"))]
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(ROOT).as_posix().encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def classify(case, analysis, approval_status, complete, top_document):
    """First failing gate determines one of four mutually exclusive classes."""
    if not case.get("expected_document"):
        return None if analysis.get("model_mode") == "unavailable" and approval_status == 409 else "unknown_safety"
    if top_document != case["expected_document"]:
        return "retrieval"
    evidence = analysis.get("evidence", [])
    if (analysis.get("model_mode") != "demo" or not analysis.get("proposed_task") or
            not any(row.get("title") == case["expected_document"] and row.get("excerpt") for row in evidence)):
        return "evidence_format"
    return None if approval_status == 200 and complete else "workflow_runtime"


def compare(report, baseline):
    if any(report.get(key) != baseline.get(key) for key in ("schema", "mode", "fixture_sha256")):
        raise ValueError("Baseline schema/mode/fixture differs; comparison refused")
    old = {row["id"]: row for row in baseline["cases"]}
    if set(old) != {row["id"] for row in report["cases"]}:
        raise ValueError("Baseline case IDs differ")
    return {
        "pass_rate_delta": round(report["workflow"]["pass_rate"] - baseline["workflow"]["pass_rate"], 4),
        "workflow_p95_ms_delta": round(report["workflow"]["p95_ms"] - baseline["workflow"]["p95_ms"], 2),
        "cost_usd_delta": 0,
        "regressions": [row["id"] for row in report["cases"] if not row["passed"] and old[row["id"]]["passed"]],
        "recoveries": [row["id"] for row in report["cases"] if row["passed"] and not old[row["id"]]["passed"]],
    }


def run_suite():
    # Set import-time global app's DB before importing routes; all data stays in
    # the temporary directory, including module initialization side effects.
    (ROOT / "work").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="eval-", dir=ROOT / "work") as folder:
        previous = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(Path(folder) / "import.db")
        try:
            from fastapi.testclient import TestClient
            from server.main import create_app
            from server.demo import seed_demo
            from examples.run_retrieval_eval import build_summary
            app = create_app(Path(folder) / "suite.db", offline=True)
            seed_demo(app.state.db)
            retrieval = build_summary()
            ranks = {row["case_id"]: row["current_top_document"] for row in retrieval["cases"]}
            fixture = json.loads((ROOT / "examples/eval_cases.json").read_text(encoding="utf-8"))["cases"]
            results = []
            # Any accidental real provider call is a hard failure even if no key.
            import server.ai as ai
            original_urlopen = ai.urlopen
            def forbidden(*args, **kwargs):
                raise AssertionError("Model network is forbidden in offline evaluation")
            ai.urlopen = forbidden
            try:
                with TestClient(app) as client:
                    project_id = client.get("/api/projects").json()[0]["id"]
                    for case in fixture:
                        started = time.perf_counter()
                        reason, category, mode = "", None, "error"
                        try:
                            response = client.post("/api/feedback", json={"project_id": project_id, "source": "offline-eval", "content": case["question"]})
                            response.raise_for_status()
                            fid = response.json()["id"]
                            response = client.post(f"/api/feedback/{fid}/analyze")
                            response.raise_for_status()
                            analysis = response.json()
                            mode = analysis["model_mode"]
                            approved = client.post(f"/api/feedback/{fid}/approve")
                            complete = False
                            if approved.status_code == 200:
                                tid = approved.json()["id"]
                                duplicate = client.post(f"/api/feedback/{fid}/approve")
                                missing_note = client.patch(f"/api/tickets/{tid}", json={"status": "done"})
                                done = client.patch(f"/api/tickets/{tid}", json={"status": "done", "resolution_note": "离线固定集验收"})
                                complete = (duplicate.status_code == 200 and duplicate.json()["id"] == tid and missing_note.status_code == 422 and done.status_code == 200 and done.json()["status"] == "done")
                            category = classify(case, analysis, approved.status_code, complete, ranks.get(case["id"]))
                            reason = LABELS[category] + "门禁未通过" if category else ""
                        except Exception as exc:
                            category, reason = "workflow_runtime", type(exc).__name__
                        results.append({"id": case["id"], "question": case["question"], "passed": category is None, "category": category, "reason": reason, "model_mode": mode, "elapsed_ms": round((time.perf_counter() - started) * 1000, 2)})
                    metrics = client.get("/api/metrics").json()
                    if metrics["model_calls"] or metrics["total_tokens"]:
                        raise RuntimeError("Offline suite unexpectedly recorded model usage")
            finally:
                ai.urlopen = original_urlopen
        finally:
            if previous is None:
                os.environ.pop("DATABASE_PATH", None)
            else:
                os.environ["DATABASE_PATH"] = previous
    elapsed = sorted(row["elapsed_ms"] for row in results)
    try:
        revision = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        manifest = ROOT / "MANIFEST.json"
        revision = json.loads(manifest.read_text(encoding="utf-8")).get("revision", "unknown") if manifest.exists() else "unknown"
    counts = Counter(row["category"] for row in results if row["category"])
    passed = sum(row["passed"] for row in results)
    return {"schema": 1, "mode": "offline_replay", "generated_at": datetime.now(timezone.utc).isoformat(), "revision": revision, "fixture_sha256": fingerprint(), "workflow": {"passed": passed, "total": len(results), "pass_rate": passed / len(results), "median_ms": round(statistics.median(elapsed), 2), "p95_ms": elapsed[min(len(elapsed) - 1, int(len(elapsed) * .95))]}, "model": {"tested": False, "calls": 0, "tokens": 0, "cost_usd": 0, "p95_ms": None, "semantic_score": None, "note": "dsh/真实模型本轮跳过；离线结果不代表模型质量"}, "failure_categories": {key: counts[key] for key in CATEGORIES}, "retrieval": retrieval, "cases": results}


def render_html(report):
    escape = lambda value: html.escape(str(value), quote=True)
    flow, retrieval = report["workflow"], report["retrieval"]["current"]
    cards = [("流程通过率", f'{flow["passed"]} / {flow["total"]}', "固定回放 · 含拒绝建单"), ("检索 Recall@1", f'{retrieval["recall_at_1"]:.0%}', f'{retrieval["cases"]} 道项目内固定题'), ("流程 P95", f'{flow["p95_ms"]} ms', "本机端到端回放 · 非模型延迟"), ("模型成本", "$0.00", "0 调用 · 0 Token · 真实接口未测")]
    cards_html = "".join(f'<article><span>{escape(label)}</span><strong>{escape(value)}</strong><small>{escape(note)}</small></article>' for label, value, note in cards)
    categories = "".join(f'<div class="failure"><span>{escape(LABELS[key])}</span><b>{value}</b></div>' for key, value in report["failure_categories"].items())
    rows = "".join(f'<tr><td><code>{escape(row["id"])}</code></td><td>{escape(row["question"])}</td><td><span class="{ "pass" if row["passed"] else "fail" }">{ "通过" if row["passed"] else escape(LABELS[row["category"]]) }</span></td><td>{row["elapsed_ms"]} ms</td><td>{escape(row["reason"])}</td></tr>' for row in report["cases"])
    comparison = report.get("comparison")
    diff = '<p>首次运行。可用 <code>--baseline 上次/report.json</code> 生成对比。</p>'
    if comparison:
        diff = f'<p>通过率变化 {comparison["pass_rate_delta"]:+.2%} · 流程 P95 变化 {comparison["workflow_p95_ms_delta"]:+.2f} ms · 模型成本变化 $0.00</p><p>新增失败：{escape(", ".join(comparison["regressions"]) or "无")}　恢复：{escape(", ".join(comparison["recoveries"]) or "无")}</p>'
    return f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Signal · 离线回归报告</title><style>
*{{box-sizing:border-box}}body{{margin:0;background:#f4f6f5;color:#20372e;font:15px/1.65 system-ui,"Microsoft YaHei",sans-serif}}main{{max-width:1200px;margin:auto;padding:48px 28px}}header{{display:flex;justify-content:space-between;align-items:center;border-bottom:1px solid #dce4df;padding-bottom:24px}}.brand{{font-size:22px;font-weight:750;letter-spacing:-1px}}.pill,.pass{{color:#287453;background:#eaf4ed;padding:4px 10px;border-radius:6px;font-size:12px}}h1{{font-size:36px;letter-spacing:-1px;margin:32px 0 8px}}p,small{{color:#687b71}}.cards{{display:grid;grid-template-columns:repeat(4,1fr);gap:16px;margin:28px 0}}article,section{{background:white;border:1px solid #dce4df;border-radius:12px;padding:24px}}article span,small{{display:block;font-size:12px}}article strong{{display:block;font-size:29px;margin:8px 0}}section{{margin-top:20px}}h2{{font-size:18px;margin:0 0 16px}}.failures{{display:grid;grid-template-columns:repeat(4,1fr);gap:18px}}.failure{{display:flex;justify-content:space-between;border-bottom:2px solid #dce4df;padding:10px 0}}.table{{overflow:auto}}table{{width:100%;border-collapse:collapse;font-size:13px}}th{{text-align:left;color:#687b71}}th,td{{padding:14px 10px;border-bottom:1px solid #edf0ee}}td:nth-child(2){{min-width:220px}}code{{font:12px/1.4 ui-monospace,monospace}}.fail{{color:#a34232}}footer{{margin-top:24px;color:#687b71;font-size:12px;overflow-wrap:anywhere}}@media(max-width:800px){{.cards,.failures{{grid-template-columns:repeat(2,1fr)}}main{{padding:24px 16px}}h1{{font-size:28px}}}}@media(max-width:440px){{.cards,.failures{{grid-template-columns:1fr}}}}
</style><main><header><span class="brand">◒ Signal</span><span class="pill">OFFLINE REGRESSION</span></header><h1>每一次改动，都有回归记录。</h1><p>36 条流程回放与 30 题检索，独立数据、无模型请求。dsh 接口及模型语义质量本轮未测。</p><div class="cards">{cards_html}</div><section><h2>与基线比较</h2>{diff}</section><section><h2>四类失败</h2><div class="failures">{categories}</div></section><section><h2>逐题验收</h2><div class="table"><table><thead><tr><th>编号</th><th>问题</th><th>结果</th><th>流程耗时</th><th>说明</th></tr></thead><tbody>{rows}</tbody></table></div></section><footer>生成时间 {escape(report["generated_at"])}<br>源码 {escape(report["revision"])}<br>题集 SHA-256 {escape(report["fixture_sha256"])}<br>回放仅验证流程；检索仅覆盖本项目两份资料。成本为本轮零请求实计，模型 P95 与语义得分未测。</footer></main></html>'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=ROOT / "work" / ("eval-" + datetime.now().strftime("%Y%m%d-%H%M%S")))
    parser.add_argument("--baseline", type=Path)
    args = parser.parse_args()
    try:
        if args.output.exists():
            raise ValueError("Output directory exists; choose a new directory to preserve results")
        baseline = json.loads(args.baseline.read_text(encoding="utf-8")) if args.baseline else None
        report = run_suite()
        if baseline:
            report["comparison"] = compare(report, baseline)
        args.output.mkdir(parents=True, exist_ok=False)
        (args.output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (args.output / "report.html").write_text(render_html(report), encoding="utf-8")
        print(json.dumps({"output": str(args.output.resolve()), "workflow": report["workflow"], "retrieval": report["retrieval"]["current"], "model_tested": False}, ensure_ascii=False))
        return 0 if report["workflow"]["pass_rate"] == 1 and report["retrieval"]["current"]["recall_at_1"] == 1 else 1
    except (OSError, ValueError, KeyError) as exc:
        parser.exit(2, f"Evaluation failed: {exc}\n")


if __name__ == "__main__":
    raise SystemExit(main())
