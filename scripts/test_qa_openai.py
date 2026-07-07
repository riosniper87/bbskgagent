#!/usr/bin/env python3
"""Smoke test Q&A with OpenAI (requires OPENAI_API_KEY)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--as-of", required=True)
    ap.add_argument("--settings", default=str(_ROOT / "config" / "settings.yaml"))
    ap.add_argument("question", nargs="+")
    args = ap.parse_args()

    from store_brief import config
    from store_brief.llm.client import LLMClient
    from store_brief.qa.orchestrator import QAOrchestrator
    from store_brief.qa.schemas import QAAskRequest

    settings = config.load_settings(args.settings)
    data_dir = Path(settings.data_dir)
    if not data_dir.is_absolute():
        data_dir = (_ROOT / data_dir).resolve()

    llm = LLMClient.openai(model=settings.openai_model)
    orch = QAOrchestrator(llm=llm, data_dir=str(data_dir), as_of=args.as_of)
    resp = orch.ask(QAAskRequest(question=" ".join(args.question)))
    print(resp.answer)
    print("\n--- traces ---")
    for t in resp.traces:
        print(f"{t.tool} ({t.ms}ms)")


if __name__ == "__main__":
    main()
