import copy

import pytest

from scripts.evaluate import REPORT_SCHEMA, classify, compare, render_html


def test_four_failure_categories_and_success():
    known = {"expected_document": "rules.md"}
    valid = {"model_mode": "demo", "outcome": "recommendation", "proposed_task": "review", "evidence": [{"title": "rules.md", "excerpt": "proof"}]}
    assert classify(known, valid, 200, True, "rules.md") is None
    assert classify(known, valid, 200, True, "other.md") == "retrieval"
    assert classify(known, {**valid, "evidence": []}, 200, True, "rules.md") == "evidence_format"
    assert classify(known, valid, 503, False, "rules.md") == "workflow_runtime"
    held = {"model_mode": "demo", "outcome": "insufficient_context", "proposed_task": "", "evidence": []}
    assert classify({}, held, 409, False, None) is None
    assert classify({}, {**held, "proposed_task": "Create a ticket"}, 409, False, None) == "unknown_safety"
    assert classify({}, {"model_mode": "unavailable", "outcome": "unavailable"}, 409, False, None) == "workflow_runtime"
    assert classify({}, valid, 200, True, None) == "unknown_safety"


def sample_report():
    return {"schema": REPORT_SCHEMA, "mode": "offline_replay", "fixture_sha256": "fixture", "generated_at": "today", "revision": "commit", "workflow": {"passed": 1, "total": 1, "pass_rate": 1, "p95_ms": 10}, "retrieval": {"current": {"recall_at_1": 1, "cases": 1}}, "failure_categories": {"retrieval": 0}, "cases": [{"id": "known-01", "question": '<script>alert("x")</script>', "passed": True, "category": None, "elapsed_ms": 10, "reason": "", "outcome": "recommendation"}]}


def test_baseline_comparison_detects_regression_and_incompatible_data():
    baseline = sample_report()
    current = copy.deepcopy(baseline)
    current["cases"][0]["passed"] = False
    current["workflow"]["pass_rate"] = 0
    assert compare(current, baseline)["regressions"] == ["known-01"]
    assert compare(baseline, current)["recoveries"] == ["known-01"]
    for key in ("schema", "mode", "fixture_sha256"):
        mismatch = {**baseline, key: "changed"}
        with pytest.raises(ValueError, match="differs"):
            compare(current, mismatch)
    mismatch = copy.deepcopy(baseline)
    mismatch["cases"][0]["id"] = "other"
    with pytest.raises(ValueError, match="IDs differ"):
        compare(current, mismatch)


def test_report_escapes_question_and_metadata():
    report = sample_report()
    report["revision"] = '<img src=x onerror="alert(1)">'
    document = render_html(report)
    assert '<script>' not in document
    assert '<img' not in document
    assert '&lt;script&gt;' in document
    assert '模型语义质量本轮未测' in document
