"""Structural quality validation for the knowledge graph.

Catches data problems that silently degrade QA retrieval: cards without
retrievable text, missing damdang routing, missing keywords, dangling
edges, and duplicate slice→card mappings.
"""
from __future__ import annotations

from store_brief.kg.schema import EdgeType, KnowledgeGraph, NodeType

_SAMPLE_LIMIT = 20


def validate_graph(graph: KnowledgeGraph) -> dict:
    """Return a JSON-ready validation report with `ok`, counts and samples."""
    nodes_by_id = graph.node_by_id()
    card_nodes = [n for n in graph.nodes if n.type == NodeType.wiki_card]
    damdang_names = {
        n.props.get("name") or n.label
        for n in graph.nodes
        if n.type == NodeType.damdang
    }

    cards_missing_damdang: list[str] = []
    cards_unknown_damdang: list[str] = []
    cards_no_text: list[str] = []
    cards_missing_keywords: list[str] = []
    for n in card_nodes:
        cid = str(n.props.get("card_id") or n.id)
        damdang = (n.props.get("damdang") or "").strip()
        if not damdang:
            cards_missing_damdang.append(cid)
        elif damdang_names and damdang not in damdang_names:
            cards_unknown_damdang.append(cid)
        headline = (n.props.get("headline") or "").strip()
        body = (n.props.get("body") or "").strip()
        if not headline and not body:
            cards_no_text.append(cid)
        if not n.props.get("keywords"):
            cards_missing_keywords.append(cid)

    dangling_edges: list[str] = []
    for e in graph.edges:
        if e.source not in nodes_by_id or e.target not in nodes_by_id:
            dangling_edges.append(e.id)

    # Card link coverage: every card should be linked to a post, an
    # attachment (or body pseudo-attachment) and a damdang.
    edges_by_type_source: dict[tuple[str, str], int] = {}
    for e in graph.edges:
        key = (e.type.value, e.source)
        edges_by_type_source[key] = edges_by_type_source.get(key, 0) + 1

    cards_no_post_edge: list[str] = []
    cards_no_attachment_edge: list[str] = []
    cards_no_damdang_edge: list[str] = []
    for n in card_nodes:
        cid = str(n.props.get("card_id") or n.id)
        if not edges_by_type_source.get((EdgeType.from_post.value, n.id)):
            cards_no_post_edge.append(cid)
        if not edges_by_type_source.get((EdgeType.cites_attachment.value, n.id)):
            cards_no_attachment_edge.append(cid)
        if not edges_by_type_source.get((EdgeType.relevant_to.value, n.id)):
            cards_no_damdang_edge.append(cid)

    # Duplicate slice→card summaries (same content slice producing >1 card).
    cards_per_slice: dict[str, int] = {}
    for e in graph.edges:
        if e.type == EdgeType.summarized_as:
            cards_per_slice[e.source] = cards_per_slice.get(e.source, 0) + 1
    duplicate_slices = [
        nodes_by_id[sid].props.get("source_ref", sid)
        for sid, count in cards_per_slice.items()
        if count > 1 and sid in nodes_by_id
    ]

    # card_index consistency with actual card nodes.
    card_ids_in_nodes = {
        str(n.props.get("card_id")) for n in card_nodes if n.props.get("card_id")
    }
    index_missing_nodes = sorted(set(graph.card_index) - card_ids_in_nodes)
    nodes_missing_index = sorted(card_ids_in_nodes - set(graph.card_index))

    issues = {
        "cards_missing_damdang": cards_missing_damdang,
        "cards_unknown_damdang": cards_unknown_damdang,
        "cards_no_text": cards_no_text,
        "cards_missing_keywords": cards_missing_keywords,
        "cards_no_post_edge": cards_no_post_edge,
        "cards_no_attachment_edge": cards_no_attachment_edge,
        "cards_no_damdang_edge": cards_no_damdang_edge,
        "dangling_edges": dangling_edges,
        "duplicate_slice_cards": duplicate_slices,
        "card_index_missing_nodes": index_missing_nodes,
        "card_nodes_missing_index": nodes_missing_index,
    }

    # cards_missing_keywords is a soft warning (keywords are enriched at
    # corpus load); everything else marks the graph as not ok.
    hard_keys = [k for k in issues if k != "cards_missing_keywords"]
    ok = all(not issues[k] for k in hard_keys)

    return {
        "ok": ok,
        "as_of": graph.as_of,
        "n_cards": len(card_nodes),
        "n_nodes": len(graph.nodes),
        "n_edges": len(graph.edges),
        "issue_counts": {k: len(v) for k, v in issues.items()},
        "issues": {k: v[:_SAMPLE_LIMIT] for k, v in issues.items()},
    }


def format_validation_summary(report: dict) -> str:
    lines = [
        f"KG validation ({report['as_of']}): "
        f"{'OK' if report['ok'] else 'ISSUES FOUND'} — "
        f"{report['n_cards']} cards, {report['n_nodes']} nodes, {report['n_edges']} edges",
    ]
    for key, count in report["issue_counts"].items():
        if count:
            sample = ", ".join(str(s) for s in report["issues"][key][:3])
            lines.append(f"  {key}: {count} (예: {sample})")
    return "\n".join(lines)
