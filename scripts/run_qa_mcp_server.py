#!/usr/bin/env python3
"""Stdio JSON-RPC MCP-style server for Q&A tools.

  python scripts/run_qa_mcp_server.py --as-of 2026-06-17

Requires OPENAI_API_KEY in environment or .env.
Protocol: newline-delimited JSON-RPC 2.0 (simplified).
Methods: initialize, tools/list, tools/call
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))


def _send(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _err(req_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def main() -> None:
    ap = argparse.ArgumentParser(description="Q&A MCP stdio server")
    ap.add_argument("--as-of", required=True, help="YYYY-MM-DD")
    ap.add_argument("--settings", default=str(_ROOT / "config" / "settings.yaml"))
    args = ap.parse_args()

    from store_brief import config
    from store_brief.llm.client import LLMClient
    from store_brief.llmwiki.grouping import load_rnr_damdang_roster
    from store_brief.qa.corpus import load_corpus
    from store_brief.qa.orchestrator import QAOrchestrator
    from store_brief.qa.schemas import QAAskRequest, QuestionIntent, TimeMode
    from store_brief.qa.tools.answer import compose_answer
    from store_brief.qa.tools.attachments import list_attachments
    from store_brief.qa.tools.intent import parse_question_intent
    from store_brief.qa.tools.registry import tool_schemas
    from store_brief.qa.tools.retrieve import retrieve_wiki_cards
    from store_brief.qa.tools.routing import resolve_damdang_scope
    from store_brief.qa.tools.temporal import resolve_temporal_scope

    settings = config.load_settings(args.settings)
    data_dir = Path(settings.data_dir)
    if not data_dir.is_absolute():
        data_dir = (_ROOT / data_dir).resolve()

    llm = LLMClient.openai(model=settings.openai_model)
    corpus = load_corpus(data_dir, args.as_of)
    roster = [d for d in load_rnr_damdang_roster(str(data_dir / "rnr.txt")) if d != "점장"]
    orch = QAOrchestrator(llm=llm, data_dir=str(data_dir), as_of=args.as_of)

    try:
        default_qd = date.fromisoformat(args.as_of)
    except ValueError:
        default_qd = None

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            _send(_err(None, -32700, "Parse error"))
            continue

        req_id = req.get("id")
        method = req.get("method")
        params = req.get("params") or {}

        if method == "initialize":
            _send({
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "protocolVersion": "2024-11-05",
                    "serverInfo": {"name": "store-brief-qa", "version": "0.1.0"},
                },
            })
            continue

        if method == "tools/list":
            tools = [{"name": s["name"], "description": s["description"], "inputSchema": s["inputSchema"]}
                     for s in tool_schemas()]
            _send({"jsonrpc": "2.0", "id": req_id, "result": {"tools": tools}})
            continue

        if method == "tools/call":
            name = params.get("name")
            arguments = params.get("arguments") or {}
            try:
                if name == "ask":
                    resp = orch.ask(QAAskRequest(
                        question=arguments["question"],
                        as_of=arguments.get("as_of", args.as_of),
                        damdang=arguments.get("damdang"),
                        query_date=date.fromisoformat(arguments["query_date"])
                        if arguments.get("query_date") else None,
                    ))
                    text = json.dumps(resp.model_dump(mode="json"), ensure_ascii=False)
                elif name == "parse_question_intent":
                    intent = parse_question_intent(
                        llm,
                        question=arguments["question"],
                        default_query_date=default_qd,
                        damdang_roster=roster,
                    )
                    text = json.dumps(intent.model_dump(mode="json"), ensure_ascii=False)
                elif name == "resolve_damdang_scope":
                    damdangs = resolve_damdang_scope(
                        damdang_hints=arguments.get("damdang_hints") or [],
                        roster=roster,
                        override=arguments.get("override"),
                    )
                    text = json.dumps({"damdangs": damdangs}, ensure_ascii=False)
                elif name == "resolve_temporal_scope":
                    intent = QuestionIntent.model_validate(arguments.get("intent") or {})
                    scope = resolve_temporal_scope(intent, default_query_date=default_qd)
                    text = json.dumps(scope.model_dump(mode="json"), ensure_ascii=False)
                elif name == "retrieve_wiki_cards":
                    from store_brief.qa.schemas import TemporalScope
                    ts = None
                    if arguments.get("temporal_scope"):
                        ts = TemporalScope.model_validate(arguments["temporal_scope"])
                    hits = retrieve_wiki_cards(
                        corpus,
                        keywords=arguments.get("keywords") or [],
                        damdangs=arguments.get("damdangs") or roster,
                        product_codes=arguments.get("product_codes"),
                        notice_kinds=arguments.get("notice_kinds"),
                        temporal_scope=ts,
                        limit=arguments.get("limit", 8),
                    )
                    text = json.dumps([h.model_dump(mode="json") for h in hits], ensure_ascii=False)
                elif name == "list_attachments":
                    from store_brief.qa.schemas import RetrievalHit
                    hits = [RetrievalHit.model_validate(h) for h in arguments.get("hits") or []]
                    atts = list_attachments(hits)
                    text = json.dumps([a.model_dump(mode="json") for a in atts], ensure_ascii=False)
                elif name == "compose_answer":
                    from store_brief.qa.schemas import RetrievalHit, TemporalScope
                    hits = [RetrievalHit.model_validate(h) for h in arguments.get("hits") or []]
                    ts = TemporalScope.model_validate(arguments["temporal_scope"]) if arguments.get("temporal_scope") else None
                    ans, cites = compose_answer(llm, question=arguments["question"], hits=hits, temporal_scope=ts)
                    text = json.dumps({"answer": ans, "citations": [c.model_dump() for c in cites]}, ensure_ascii=False)
                else:
                    _send(_err(req_id, -32601, f"Unknown tool: {name}"))
                    continue
                _send({
                    "jsonrpc": "2.0",
                    "id": req_id,
                    "result": {"content": [{"type": "text", "text": text}]},
                })
            except Exception as exc:
                _send(_err(req_id, -32000, str(exc)))
            continue

        _send(_err(req_id, -32601, f"Method not found: {method}"))


if __name__ == "__main__":
    main()
