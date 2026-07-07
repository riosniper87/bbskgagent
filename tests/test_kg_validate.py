"""Tests for knowledge-graph structural validation."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.kg.schema import (
    EdgeType,
    GraphEdge,
    GraphNode,
    KnowledgeGraph,
    NodeType,
)
from store_brief.kg.validate import format_validation_summary, validate_graph


def _good_graph() -> KnowledgeGraph:
    nodes = [
        GraphNode(id="post:p1", type=NodeType.post, label="공지"),
        GraphNode(id="att:a1", type=NodeType.attachment, label="promo.xlsx"),
        GraphNode(id="slice:s1", type=NodeType.content_slice, label="s1",
                  props={"source_ref": "p1#s1"}),
        GraphNode(
            id="card:c1", type=NodeType.wiki_card, label="냉장고 판촉",
            props={
                "card_id": "c1", "damdang": "대형가전1",
                "headline": "냉장고 판촉", "body": "본문",
                "keywords": ["냉장고"],
            },
        ),
        GraphNode(id="damdang:대형가전1", type=NodeType.damdang, label="대형가전1",
                  props={"name": "대형가전1"}),
    ]
    edges = [
        GraphEdge(id="e1", type=EdgeType.has_attachment, source="post:p1", target="att:a1"),
        GraphEdge(id="e2", type=EdgeType.has_slice, source="att:a1", target="slice:s1"),
        GraphEdge(id="e3", type=EdgeType.summarized_as, source="slice:s1", target="card:c1"),
        GraphEdge(id="e4", type=EdgeType.from_post, source="card:c1", target="post:p1"),
        GraphEdge(id="e5", type=EdgeType.cites_attachment, source="card:c1", target="att:a1"),
        GraphEdge(id="e6", type=EdgeType.relevant_to, source="card:c1", target="damdang:대형가전1"),
    ]
    return KnowledgeGraph(
        as_of="2026-06-17", nodes=nodes, edges=edges, card_index={"c1": "대형가전1"},
    )


def test_validate_good_graph_ok():
    report = validate_graph(_good_graph())
    assert report["ok"] is True
    assert report["n_cards"] == 1
    assert all(c == 0 for c in report["issue_counts"].values())
    assert "OK" in format_validation_summary(report)


def test_validate_detects_issues():
    g = _good_graph()
    # Card with no damdang, no text, no keywords, no edges at all.
    g.nodes.append(
        GraphNode(
            id="card:c2", type=NodeType.wiki_card, label="",
            props={"card_id": "c2", "damdang": "", "headline": "", "body": ""},
        ),
    )
    # Dangling edge to a missing node.
    g.edges.append(
        GraphEdge(id="e-dangle", type=EdgeType.mentions, source="card:c1", target="product:GHOST"),
    )
    # Duplicate slice→card summary.
    g.edges.append(
        GraphEdge(id="e-dup", type=EdgeType.summarized_as, source="slice:s1", target="card:c2"),
    )
    # card_index references a card that has no node.
    g.card_index["ghost"] = "IT"

    report = validate_graph(g)
    assert report["ok"] is False
    counts = report["issue_counts"]
    assert counts["cards_missing_damdang"] == 1
    assert counts["cards_no_text"] == 1
    assert counts["cards_missing_keywords"] == 1
    assert counts["cards_no_post_edge"] == 1
    assert counts["cards_no_attachment_edge"] == 1
    assert counts["cards_no_damdang_edge"] == 1
    assert counts["dangling_edges"] == 1
    assert counts["duplicate_slice_cards"] == 1
    assert "ghost" in report["issues"]["card_index_missing_nodes"]
    assert "c2" in report["issues"]["card_nodes_missing_index"]
    assert "ISSUES FOUND" in format_validation_summary(report)


def test_validate_unknown_damdang_flagged():
    g = _good_graph()
    for n in g.nodes:
        if n.id == "card:c1":
            n.props["damdang"] = "없는담당"
    report = validate_graph(g)
    assert report["issue_counts"]["cards_unknown_damdang"] == 1
    assert report["ok"] is False


def test_missing_keywords_alone_is_soft_warning():
    g = _good_graph()
    for n in g.nodes:
        if n.id == "card:c1":
            n.props["keywords"] = []
    report = validate_graph(g)
    assert report["issue_counts"]["cards_missing_keywords"] == 1
    assert report["ok"] is True
