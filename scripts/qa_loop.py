#!/usr/bin/env python3
"""One-shot QA loop: optional rebuild → eval → report → canvas."""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from store_brief.qa.eval.promote import promote_from_run
from store_brief.qa.eval.runner import run_eval


def _run_script(name: str, args: list[str]) -> None:
    script = ROOT / "scripts" / name
    cmd = [sys.executable, str(script), *args]
    print(f"\n>> {' '.join(cmd)}")
    subprocess.run(cmd, cwd=str(ROOT), check=True)


def main() -> int:
    p = argparse.ArgumentParser(
        description="QA loop: rebuild (optional) + eval + summary/canvas",
    )
    p.add_argument("--data-dir", default=str(ROOT / "data"))
    p.add_argument("--as-of", required=True)
    p.add_argument("-n", "--n-cases", type=int, default=10)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--threshold", type=float, default=0.85)
    p.add_argument("--no-judge", action="store_true")
    p.add_argument("--min-judge-ratio", type=float, default=0.7)
    p.add_argument("--promote", action="store_true")
    p.add_argument("--openai-model", default=None)
    p.add_argument("--rebuild-llmwiki", action="store_true")
    p.add_argument("--rebuild-kg", action="store_true")
    p.add_argument("--rebuild-only", action="store_true", help="Rebuild only; skip eval")
    p.add_argument("--cache-only", action="store_true", help="Pass --cache-only to llmwiki build")
    args = p.parse_args()

    if args.rebuild_llmwiki:
        wiki_args = ["--as-of", args.as_of]
        if args.cache_only:
            wiki_args.append("--cache-only")
        _run_script("build_llmwiki_from_parsed.py", wiki_args)

    if args.rebuild_kg:
        _run_script("build_knowledge_graph.py", ["--as-of", args.as_of])

    if args.rebuild_only:
        print("\nRebuild complete (eval skipped).")
        return 0

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

    print(f"\nQA Loop complete: {summary.run_id}")
    print(f"  Passed: {summary.n_passed}/{summary.n_cases} ({summary.overall_pass_rate:.1%})")
    print(f"  Hit@1:  {summary.retrieval_hit_at_1_rate:.1%}")
    print(f"  Attach: {summary.attachment_match_rate:.1%}")
    print(f"  Answer: {summary.answer_adequacy_rate:.1%}")

    out_dir = Path(args.data_dir) / "eval" / args.as_of / summary.run_id
    print(f"  Report: {out_dir / 'report.json'}")
    print(f"  Summary: {Path(args.data_dir) / 'eval' / 'summary.json'}")

    if args.promote:
        n = promote_from_run(Path(args.data_dir), summary.run_id)
        print(f"  Promoted: {n} regression case(s)")

    return 0 if summary.overall_pass_rate >= summary.threshold else 1


if __name__ == "__main__":
    raise SystemExit(main())
