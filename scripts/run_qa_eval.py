#!/usr/bin/env python3
"""Run QA eval loop: suggest → ask → score → report."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from store_brief.qa.eval.promote import promote_from_run
from store_brief.qa.eval.runner import run_eval, run_regression_eval


def main() -> int:
    p = argparse.ArgumentParser(description="QA eval: sample questions → verify answers")
    p.add_argument("--data-dir", default=str(ROOT / "data"))
    p.add_argument("--as-of", required=True, help="Corpus as-of date (e.g. 2026-06-17)")
    p.add_argument("-n", "--n-cases", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--threshold", type=float, default=0.85)
    p.add_argument("--no-judge", action="store_true", help="Skip LLM answer judge (Layer C)")
    p.add_argument("--min-judge-ratio", type=float, default=0.7)
    p.add_argument("--promote", action="store_true", help="Promote repeated failures to regression_cases.json")
    p.add_argument("--regression-only", action="store_true", help="Run frozen regression_cases.json only")
    p.add_argument("--baseline-out", default=None, help="Copy report JSON to this path (e.g. baseline/)")
    p.add_argument("--openai-model", default=None)
    args = p.parse_args()

    if args.regression_only:
        summary = run_regression_eval(
            data_dir=args.data_dir,
            as_of=args.as_of,
            threshold=args.threshold,
            use_judge=not args.no_judge,
            min_judge_ratio=args.min_judge_ratio,
            openai_model=args.openai_model,
        )
    else:
        summary = run_eval(
            data_dir=args.data_dir,
            as_of=args.as_of,
            n_cases=args.n_cases,
            seed=args.seed,
            threshold=args.threshold,
            use_judge=not args.no_judge,
            min_judge_ratio=args.min_judge_ratio,
            openai_model=args.openai_model,
        )

    if args.baseline_out:
        import json
        import shutil

        out_path = Path(args.baseline_out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        run_report = Path(args.data_dir) / "eval" / args.as_of / summary.run_id / "report.json"
        if run_report.is_file():
            shutil.copy2(run_report, out_path)
        else:
            out_path.write_text(
                json.dumps(summary.model_dump(mode="json"), ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    print(f"\nQA Eval run: {summary.run_id}")
    print(f"  Cases:     {summary.n_cases}")
    print(f"  Passed:    {summary.n_passed} ({summary.overall_pass_rate:.1%})")
    print(f"  Hit@1:     {summary.retrieval_hit_at_1_rate:.1%}")
    print(f"  Hit@3:     {summary.retrieval_hit_at_3_rate:.1%}")
    print(f"  Attachment:{summary.attachment_match_rate:.1%}")
    print(f"  Answer:    {summary.answer_adequacy_rate:.1%}")
    print(f"  Threshold: {summary.threshold:.1%}")
    if summary.failure_counts:
        print(f"  Failures:  {summary.failure_counts}")

    out_dir = Path(args.data_dir) / "eval" / args.as_of / summary.run_id
    print(f"  Report:    {out_dir / 'report.json'}")
    print(f"  Summary:   {Path(args.data_dir) / 'eval' / 'summary.json'}")

    if args.promote:
        n = promote_from_run(Path(args.data_dir), summary.run_id)
        print(f"  Promoted:  {n} regression case(s)")

    return 0 if summary.overall_pass_rate >= summary.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
