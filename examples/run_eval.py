"""Collect reproducible AI outputs from a fixed question set; no automatic score claims."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parent


def request(api_url: str, path: str, payload: dict | None = None) -> dict:
    headers = {"Content-Type": "application/json; charset=utf-8"} if payload is not None else {}
    req = urllib.request.Request(
        api_url.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{path}: HTTP {error.code}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--limit", type=int, default=5, help="Number of cases to call (default 5)")
    parser.add_argument("--all", action="store_true", help="Call all fixed cases; this consumes model API quota")
    parser.add_argument("--case-ids", nargs="+", help="Run selected case IDs, e.g. known-10 unknown-01")
    args = parser.parse_args()

    health = request(args.api_url, "/api/health")
    if not health.get("ai_configured"):
        raise SystemExit("模型 API 尚未配置；不会制造模拟 AI 成绩。请先查看 server/README.md。")

    fixture = json.loads((BASE / "eval_cases.json").read_text(encoding="utf-8"))
    if args.case_ids:
        wanted = set(args.case_ids)
        cases = [case for case in fixture["cases"] if case["id"] in wanted]
        missing = wanted - {case["id"] for case in cases}
        if missing:
            raise SystemExit(f"未知评测题 ID：{', '.join(sorted(missing))}")
    else:
        cases = fixture["cases"] if args.all else fixture["cases"][: max(0, args.limit)]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    project = request(args.api_url, "/api/projects", {
        "name": f"固定评测 {stamp}",
        "description": "评测资料由现有微信小程序代码与测试核对，问题含故意无答案样本。",
    })
    project_id = project["id"]
    for path in sorted((BASE / "miniapp").glob("*.md")):
        request(args.api_url, "/api/documents", {
            "project_id": project_id,
            "title": path.name,
            "content": path.read_text(encoding="utf-8"),
        })

    results = []
    for case in cases:
        feedback = request(args.api_url, "/api/feedback", {
            "project_id": project_id,
            "source": "固定评测题，非真实用户反馈",
            "content": case["question"],
        })
        analysis = request(args.api_url, f"/api/feedback/{feedback['id']}/analyze", {})
        traces = request(args.api_url, f"/api/traces?feedback_id={feedback['id']}")
        results.append({
            "case": case,
            "feedback_id": feedback["id"],
            "analysis": analysis,
            "traces": traces,
            "human_review": {
                "answer_correct": None,
                "evidence_relevant": None,
                "safe_unknown_handling": None,
                "notes": "",
            },
        })
        print(f"{case['id']}: {analysis['model_mode']} | 待人工评分")

    work = ROOT / "work"
    work.mkdir(exist_ok=True)
    output = work / f"eval-{stamp}.json"
    output.write_text(json.dumps({
        "created_at": stamp,
        "project_id": project_id,
        "api_url": args.api_url,
        "model": "由后端环境配置；此文件不记录密钥",
        "note": "结果待人工评分。脚本不自动宣称准确率。",
        "results": results,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"原始评测输出已保存：{output}")


if __name__ == "__main__":
    main()
