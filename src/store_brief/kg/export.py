"""Export knowledge graph to disk."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from store_brief.kg.schema import EdgeType, KnowledgeGraph, NodeType


def export_graph(
    graph: KnowledgeGraph,
    out_dir: str | Path,
    as_of: date,
) -> dict[str, Path]:
    out = Path(out_dir) / as_of.isoformat()
    out.mkdir(parents=True, exist_ok=True)

    graph_path = out / "graph.json"
    graph_path.write_text(
        json.dumps(graph.model_dump(mode="json"), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    stats = graph.stats()
    stats_path = out / "stats.json"
    stats_path.write_text(json.dumps(stats, ensure_ascii=False, indent=2), encoding="utf-8")

    by_damdang_dir = out / "by_damdang"
    by_damdang_dir.mkdir(exist_ok=True)
    for old in by_damdang_dir.glob("*.json"):
        old.unlink()

    nodes_by_id = graph.node_by_id()
    cards_by_damdang: dict[str, list[str]] = {}
    for card_id, damdang in graph.card_index.items():
        cards_by_damdang.setdefault(damdang, []).append(card_id)

    for damdang, card_ids in sorted(cards_by_damdang.items()):
        card_node_ids = {f"card:{cid}" for cid in card_ids}
        related: set[str] = set(card_node_ids)
        for e in graph.edges:
            if e.source in card_node_ids or e.target in card_node_ids:
                related.add(e.source)
                related.add(e.target)

        sub_nodes = [nodes_by_id[nid] for nid in related if nid in nodes_by_id]
        sub_edges = [
            e for e in graph.edges if e.source in related and e.target in related
        ]
        payload = {
            "damdang": damdang,
            "card_count": len(card_ids),
            "card_ids": card_ids,
            "nodes": [n.model_dump(mode="json") for n in sub_nodes],
            "edges": [e.model_dump(mode="json") for e in sub_edges],
        }
        safe_name = damdang.replace("/", "_")
        (by_damdang_dir / f"{safe_name}.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    return {
        "graph": graph_path,
        "stats": stats_path,
        "by_damdang_dir": by_damdang_dir,
    }


def cards_for_post(graph: KnowledgeGraph, post_id: str) -> list[dict]:
    """Cards linked to a post with provenance (for API)."""
    post_nid = f"post:{post_id}"
    out: list[dict] = []
    nodes = graph.node_by_id()
    for e in graph.edges:
        if e.type == EdgeType.from_post and e.target == post_nid:
            card = nodes.get(e.source)
            if card and card.type == NodeType.wiki_card:
                out.append(card.props)
    return out


def cards_by_product(graph: KnowledgeGraph, prd_cd: str) -> list[dict]:
    prd_nid = f"prd:{prd_cd.strip().upper()}"
    nodes = graph.node_by_id()
    out: list[dict] = []
    for e in graph.edges:
        if e.type == EdgeType.mentions and e.target == prd_nid:
            card = nodes.get(e.source)
            if card:
                out.append(card.props)
    return out
