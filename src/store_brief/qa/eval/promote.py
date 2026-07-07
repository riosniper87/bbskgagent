"""Promote repeated eval failures to regression fixtures."""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from store_brief.qa.eval.schema import EvalCase


def find_repeated_failures(
    data_dir: Path,
    *,
    min_occurrences: int = 2,
) -> list[tuple[str, int]]:
    """Return (question_key, count) for failures seen multiple times."""
    summary_path = data_dir / "eval" / "summary.json"
    if not summary_path.is_file():
        return []

    data = json.loads(summary_path.read_text(encoding="utf-8"))
    counter: Counter[str] = Counter()
    for run in data.get("runs", []):
        seen_in_run: set[str] = set()
        for f in run.get("failures", []):
            key = f"{f.get('post_id')}|{f.get('question', '')[:60]}"
            if key not in seen_in_run:
                counter[key] += 1
                seen_in_run.add(key)

    return [(k, c) for k, c in counter.most_common() if c >= min_occurrences]


def load_regression_cases(data_dir: Path) -> list[EvalCase]:
    """Load frozen regression cases from data/eval/regression_cases.json."""
    path = data_dir / "eval" / "regression_cases.json"
    if not path.is_file():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    return [EvalCase.model_validate(c) for c in raw.get("cases", [])]


def save_regression_cases(data_dir: Path, cases: list[EvalCase]) -> Path:
    path = data_dir / "eval" / "regression_cases.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"cases": [c.model_dump(mode="json") for c in cases]}
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def promote_from_run(
    data_dir: Path,
    run_id: str,
    *,
    min_occurrences: int = 2,
) -> int:
    """Add failures from a run to regression_cases if seen >= min_occurrences."""
    report_path = None
    eval_as_of = data_dir / "eval"
    for as_of_dir in eval_as_of.iterdir():
        if not as_of_dir.is_dir() or as_of_dir.name == "summary.json":
            continue
        candidate = as_of_dir / run_id / "report.json"
        if candidate.is_file():
            report_path = candidate
            break

    if report_path is None:
        return 0

    from store_brief.qa.eval.schema import EvalRunSummary

    summary = EvalRunSummary.model_validate_json(report_path.read_text(encoding="utf-8"))
    existing = load_regression_cases(data_dir)
    existing_keys = {f"{c.post_id}|{c.question[:60]}" for c in existing}
    repeated = {k for k, c in find_repeated_failures(data_dir, min_occurrences=min_occurrences)}

    added = 0
    for r in summary.results:
        if r.passed:
            continue
        key = f"{r.case.post_id}|{r.case.question[:60]}"
        if key in existing_keys:
            continue
        if key not in repeated and min_occurrences > 1:
            continue
        existing.append(r.case)
        existing_keys.add(key)
        added += 1

    if added:
        save_regression_cases(data_dir, existing)
    return added
