"""Tests for knowledge graph build."""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.kg.build import build_knowledge_graph, load_cards_from_llmwiki
from store_brief.kg.export import cards_by_product, cards_for_post, export_graph
from store_brief.kg.load import load_knowledge_graph
from store_brief.kg.schema import EdgeType, NodeType
from store_brief.kg.provenance import slice_node_id

ROOT = Path(__file__).resolve().parents[1]
LLMWIKI = ROOT / "data" / "llmwiki" / "2026-06-17" / "llmwiki.json"


@pytest.fixture(scope="module")
def graph():
    if not LLMWIKI.is_file():
        pytest.skip("llmwiki.json not built")
    return build_knowledge_graph(
        date(2026, 6, 17),
        data_dir=str(ROOT / "data"),
        llmwiki_path=LLMWIKI,
        cache_path=str(ROOT / "data" / "cache" / "hisis_prd_damdang.json"),
        rnr_path=str(ROOT / "data" / "rnr.txt"),
    )


def test_load_cards_from_llmwiki():
    if not LLMWIKI.is_file():
        pytest.skip("llmwiki.json not built")
    cards = load_cards_from_llmwiki(LLMWIKI)
    assert len(cards) >= 1
    assert "post_id" in cards[0]
    assert "source_ref" in cards[0]


def test_graph_has_cards(graph):
    stats = graph.stats()
    assert stats["cards"] >= 1
    assert stats["node_WikiCard"] == stats["cards"]


def test_card_provenance_chain(graph):
    nodes = graph.node_by_id()
    card_nodes = [n for n in graph.nodes if n.type == NodeType.wiki_card]
    assert card_nodes
    card = card_nodes[0]
    prov = card.props.get("provenance") or {}
    assert prov.get("post_id")
    assert prov.get("attachment_name")
    assert prov.get("source_ref")

    post_nid = f"post:{prov['post_id']}"
    slice_nid = prov.get("slice_id") or slice_node_id(prov["source_ref"])

    edge_types = {(e.type, e.source, e.target) for e in graph.edges}
    assert (EdgeType.from_post, card.id, post_nid) in edge_types
    assert any(
        e.type == EdgeType.summarized_as and e.target == card.id
        for e in graph.edges
    )
    assert any(
        e.type == EdgeType.cites_attachment and e.source == card.id
        for e in graph.edges
    )


def test_product_routed_to_damdang(graph):
    product_nodes = [n for n in graph.nodes if n.type == NodeType.product]
    if not product_nodes:
        pytest.skip("no product nodes")
    prd = product_nodes[0]
    routed = [
        e for e in graph.edges
        if e.type == EdgeType.routed_to and e.source == prd.id
    ]
    assert routed
    damdang_names = {
        graph.node_by_id()[e.target].props.get("name") for e in routed
    }
    assert prd.props.get("damdang") or damdang_names


def test_no_orphan_cards(graph):
    for e in graph.edges:
        if e.type == EdgeType.summarized_as:
            assert e.target in graph.node_by_id()
            assert e.source in graph.node_by_id()


def test_export_roundtrip(graph, tmp_path):
    paths = export_graph(graph, tmp_path / "kg", date(2026, 6, 17))
    assert paths["graph"].is_file()
    loaded = load_knowledge_graph(paths["graph"])
    assert loaded.stats()["cards"] == graph.stats()["cards"]


def test_cards_for_post_and_product(graph):
    card_nodes = [n for n in graph.nodes if n.type == NodeType.wiki_card]
    prov = card_nodes[0].props["provenance"]
    post_cards = cards_for_post(graph, prov["post_id"])
    assert post_cards
    codes = card_nodes[0].props.get("product_codes") or []
    if codes:
        found = cards_by_product(graph, codes[0])
        assert found


def test_graph_for_viz_spine_mode(graph):
    from store_brief.kg.viz import graph_for_viz

    payload = graph_for_viz(graph, mode="spine")
    assert payload["meta"]["node_count"] >= 1
    assert payload["meta"]["edge_count"] >= 1
    groups = {n["group"] for n in payload["nodes"]}
    assert "WikiCard" in groups
    assert "Product" not in groups


def test_graph_for_viz_damdang_filter(graph):
    from store_brief.kg.viz import graph_for_viz

    card_nodes = [n for n in graph.nodes if n.type == NodeType.wiki_card]
    if not card_nodes:
        pytest.skip("no cards")
    damdang = card_nodes[0].props["damdang"]
    payload = graph_for_viz(graph, mode="spine", damdang=damdang)
    assert payload["meta"]["damdang"] == damdang
    assert payload["meta"]["node_count"] >= 1
