"""Tests for eval report and promotion."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.qa.eval.promote import find_repeated_failures, load_regression_cases
from store_brief.qa.eval.report import _mermaid_flow
from store_brief.qa.eval.schema import EvalRunSummary


def test_mermaid_flow_contains_stages():
    summary = EvalRunSummary(
        run_id="test",
        as_of="2026-06-17",
        started_at="2026-06-17T09:00:00Z",
        n_cases=10,
        n_passed=8,
        overall_pass_rate=0.8,
        retrieval_hit_at_1_rate=0.9,
        retrieval_hit_at_3_rate=0.95,
        attachment_match_rate=0.85,
        answer_adequacy_rate=0.8,
        threshold=0.85,
    )
    flow = _mermaid_flow(summary)
    assert "Suggest" in flow
    assert "Retrieval" in flow
    assert "Pass" in flow


def test_load_regression_cases(tmp_path):
    data = {
        "cases": [{
            "question": "test?",
            "post_id": "p1",
            "post_title": "t",
            "posted_date": "2026-06-01",
            "source_type": "body",
            "source_label": "본문",
            "source_ref": "p1#body",
            "excerpt_full": "content",
        }],
    }
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "regression_cases.json").write_text(
        json.dumps(data), encoding="utf-8",
    )
    cases = load_regression_cases(tmp_path)
    assert len(cases) == 1
    assert cases[0].post_id == "p1"


def test_find_repeated_failures(tmp_path):
    summary = {
        "runs": [
            {"failures": [{"post_id": "p1", "question": "same q"}]},
            {"failures": [{"post_id": "p1", "question": "same q"}]},
        ],
    }
    (tmp_path / "eval").mkdir()
    (tmp_path / "eval" / "summary.json").write_text(json.dumps(summary), encoding="utf-8")
    repeated = find_repeated_failures(tmp_path, min_occurrences=2)
    assert len(repeated) == 1
    assert repeated[0][1] == 2
