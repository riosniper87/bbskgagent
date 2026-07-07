#!/usr/bin/env python3
"""Build knowledge graph from llmwiki WikiCards + parsed/raw provenance.

  python scripts/build_knowledge_graph.py --as-of 2026-06-17

Requires llmwiki.json from build_llmwiki_from_parsed.py first.

Output:
  data/kg/{as_of}/graph.json
  data/kg/{as_of}/stats.json
  data/kg/{as_of}/by_damdang/*.json
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config
from store_brief.kg.build import build_knowledge_graph
from store_brief.kg.export import export_graph
from store_brief.kg.validate import format_validation_summary, validate_graph

log = logging.getLogger(__name__)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    ap = argparse.ArgumentParser(description="Build knowledge graph from llmwiki")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--settings", default="config/settings.yaml")
    ap.add_argument("--llmwiki", default=None, help="Path to llmwiki.json (default: data/llmwiki/{as_of}/)")
    ap.add_argument("--cache", default="data/cache/hisis_prd_damdang.json")
    ap.add_argument("--rnr", default="data/rnr.txt")
    args = ap.parse_args()

    as_of = date.fromisoformat(args.as_of)
    settings = config.load_settings(args.settings)
    data_dir = settings.data_dir

    llmwiki_path = Path(args.llmwiki) if args.llmwiki else Path(data_dir) / "llmwiki" / as_of.isoformat() / "llmwiki.json"
    if not llmwiki_path.is_file():
        print(f"llmwiki not found: {llmwiki_path}", file=sys.stderr)
        print("Run: python scripts/build_llmwiki_from_parsed.py --as-of", as_of.isoformat())
        sys.exit(1)

    graph = build_knowledge_graph(
        as_of,
        data_dir=data_dir,
        llmwiki_path=llmwiki_path,
        cache_path=args.cache,
        rnr_path=args.rnr,
    )
    paths = export_graph(graph, Path(data_dir) / "kg", as_of)
    stats = graph.stats()

    report = validate_graph(graph)
    validation_path = Path(paths["graph"]).parent / "validation.json"
    validation_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
    )

    print(f"\nKnowledge graph built: {stats['cards']} card(s)")
    print(f"  nodes: {stats['nodes']}  edges: {stats['edges']}")
    print(f"  Graph:  {paths['graph']}")
    print(f"  Stats:  {paths['stats']}")
    print(f"  By담당: {paths['by_damdang_dir']}/")
    print(f"  Validation: {validation_path}")
    print()
    print(format_validation_summary(report))
    if not report["ok"]:
        print("\n⚠ KG 구조 문제가 발견되었습니다 — validation.json을 확인하세요.")


if __name__ == "__main__":
    main()
