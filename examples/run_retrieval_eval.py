"""Compare the original overlap baseline with current BM25 retrieval offline."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server.retrieval import RETRIEVAL_ALGORITHM, legacy_overlap_rank, rank_documents  # noqa: E402

BASE = Path(__file__).resolve().parent


def metrics(ranks: list[int]) -> dict[str, float | int]:
    return {
        "cases": len(ranks),
        "recall_at_1": round(sum(rank <= 1 for rank in ranks) / len(ranks), 4),
        "recall_at_3": round(sum(rank <= 3 for rank in ranks) / len(ranks), 4),
        "mrr": round(sum(1 / rank for rank in ranks) / len(ranks), 4),
    }


def build_summary() -> dict:
    paths = sorted((BASE / "miniapp").glob("*.md"))
    documents = [
        {"id": index, "title": path.name, "content": path.read_text(encoding="utf-8")}
        for index, path in enumerate(paths, start=1)
    ]
    cases = json.loads((BASE / "eval_cases.json").read_text(encoding="utf-8"))["cases"]
    answerable = [case for case in cases if case.get("expected_document")]
    results = []
    baseline_ranks: list[int] = []
    current_ranks: list[int] = []
    for case in answerable:
        baseline = legacy_overlap_rank(documents, case["question"])
        current = [item.row for item in rank_documents(documents, case["question"])]
        baseline_rank = next(
            index for index, row in enumerate(baseline, start=1) if row["title"] == case["expected_document"]
        )
        current_rank = next(
            index for index, row in enumerate(current, start=1) if row["title"] == case["expected_document"]
        )
        baseline_ranks.append(baseline_rank)
        current_ranks.append(current_rank)
        results.append(
            {
                "case_id": case["id"],
                "expected_document": case["expected_document"],
                "baseline_rank": baseline_rank,
                "current_rank": current_rank,
                "current_top_document": current[0]["title"],
            }
        )

    summary = {
        "scope": {
            "documents": len(documents),
            "answerable_cases": len(answerable),
            "excluded_unknown_cases": len(cases) - len(answerable),
            "note": "小型、项目内固定题集，仅证明可复现的文档召回，不代表线上通用准确率。",
        },
        "baseline": {"algorithm": "unique_token_overlap_v0", **metrics(baseline_ranks)},
        "current": {"algorithm": RETRIEVAL_ALGORITHM, **metrics(current_ranks)},
        "cases": results,
    }
    return summary


def main() -> None:
    summary = build_summary()
    output = BASE / "retrieval_eval_summary.json"
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"output": str(output), **summary}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
