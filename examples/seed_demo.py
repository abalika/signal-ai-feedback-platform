"""Import verified miniapp product facts. Mock feedback is opt-in and visibly labeled."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from pathlib import Path

BASE = Path(__file__).resolve().parent


def post(api_url: str, path: str, payload: dict) -> dict:
    request = urllib.request.Request(
        api_url.rstrip("/") + path,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        raise RuntimeError(f"{path}: HTTP {error.code}: {error.read().decode('utf-8', errors='replace')}") from error


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api-url", default="http://localhost:8000")
    parser.add_argument("--include-mock-feedback", action="store_true", help="Also import explicitly synthetic demonstration feedback")
    args = parser.parse_args()

    project = post(args.api_url, "/api/projects", {
        "name": "一按即定 · 产品试点",
        "description": "资料由本人微信小程序代码与测试核对；暂无真实用户反馈或运营数据。",
    })
    project_id = project["id"]
    for path in sorted((BASE / "miniapp").glob("*.md")):
        post(args.api_url, "/api/documents", {
            "project_id": project_id,
            "title": path.name,
            "content": path.read_text(encoding="utf-8"),
        })
        print(f"资料导入：{path.name}")

    if args.include_mock_feedback:
        mock = json.loads((BASE / "mock-feedback.json").read_text(encoding="utf-8"))
        for item in mock["items"]:
            post(args.api_url, "/api/feedback", {"project_id": project_id, **item})
        print(f"模拟反馈导入：{len(mock['items'])} 条（非真实用户反馈）")
    print(f"项目已建立：{project_id}。模型结果与真实用户指标尚未产生。")


if __name__ == "__main__":
    main()
