"""Tool registry — schemas for MCP and orchestrator."""
from __future__ import annotations

from typing import Any, Callable

TOOL_HANDLERS: dict[str, Callable[..., Any]] = {}


def register_tool(name: str):
    def deco(fn: Callable[..., Any]):
        TOOL_HANDLERS[name] = fn
        return fn
    return deco


def tool_schemas() -> list[dict[str, Any]]:
    from store_brief.qa.tools import __init__ as _  # noqa: F401

    return [
        {
            "name": "parse_question_intent",
            "description": "Parse user question into damdang hints, product codes, notice kinds, and temporal mode.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "default_query_date": {"type": "string"},
                },
                "required": ["question"],
            },
        },
        {
            "name": "resolve_damdang_scope",
            "description": "Resolve which damdang buckets to search.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "damdang_hints": {"type": "array", "items": {"type": "string"}},
                    "override": {"type": "string"},
                },
            },
        },
        {
            "name": "resolve_temporal_scope",
            "description": "Map temporal intent to filter parameters.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "intent": {"type": "object"},
                    "default_query_date": {"type": "string"},
                },
            },
        },
        {
            "name": "retrieve_wiki_cards",
            "description": "Retrieve top wiki cards matching scope and keywords.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "damdangs": {"type": "array", "items": {"type": "string"}},
                    "product_codes": {"type": "array", "items": {"type": "string"}},
                    "notice_kinds": {"type": "array", "items": {"type": "string"}},
                    "temporal_scope": {"type": "object"},
                    "limit": {"type": "integer"},
                },
            },
        },
        {
            "name": "list_attachments",
            "description": "List deduplicated attachments from retrieval hits.",
            "inputSchema": {
                "type": "object",
                "properties": {"hits": {"type": "array"}},
            },
        },
        {
            "name": "compose_answer",
            "description": "Generate grounded Korean answer from hits.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "hits": {"type": "array"},
                    "temporal_scope": {"type": "object"},
                },
                "required": ["question"],
            },
        },
        {
            "name": "ask",
            "description": "Full Q&A pipeline (intent → retrieve → answer).",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "as_of": {"type": "string"},
                    "damdang": {"type": "string"},
                    "query_date": {"type": "string"},
                },
                "required": ["question", "as_of"],
            },
        },
    ]
