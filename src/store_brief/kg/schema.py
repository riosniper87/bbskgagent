"""Knowledge graph schema — WikiCard spine + catalog nodes."""
from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class NodeType(str, Enum):
    post = "Post"
    attachment = "Attachment"
    content_slice = "ContentSlice"
    wiki_card = "WikiCard"
    product = "Product"
    damdang = "Damdang"
    keyword = "Keyword"


class EdgeType(str, Enum):
    has_attachment = "has_attachment"
    has_slice = "has_slice"
    summarized_as = "summarized_as"
    from_post = "from_post"
    cites_attachment = "cites_attachment"
    mentions = "mentions"
    routed_to = "routed_to"
    relevant_to = "relevant_to"
    co_occurs = "co_occurs"
    tagged_with = "tagged_with"
    keyword_in_post = "keyword_in_post"


class CardProvenance(BaseModel):
    post_id: str
    post_title: str
    posted_date: str
    attachment_id: str
    attachment_name: str
    attachment_path: str | None = None
    attachment_kind: str | None = None
    source_ref: str
    slice_id: str
    viewer_url: str | None = None


class GraphNode(BaseModel):
    id: str
    type: NodeType
    label: str
    props: dict[str, Any] = Field(default_factory=dict)


class GraphEdge(BaseModel):
    id: str
    type: EdgeType
    source: str
    target: str
    props: dict[str, Any] = Field(default_factory=dict)


class KnowledgeGraph(BaseModel):
    as_of: str
    grouping: str = "wiki_card_spine"
    nodes: list[GraphNode] = Field(default_factory=list)
    edges: list[GraphEdge] = Field(default_factory=list)
    card_index: dict[str, str] = Field(default_factory=dict)  # card_id -> damdang

    def node_by_id(self) -> dict[str, GraphNode]:
        return {n.id: n for n in self.nodes}

    def edges_from(self, node_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.source == node_id]

    def edges_to(self, node_id: str) -> list[GraphEdge]:
        return [e for e in self.edges if e.target == node_id]

    def stats(self) -> dict[str, int]:
        node_counts: dict[str, int] = {}
        edge_counts: dict[str, int] = {}
        for n in self.nodes:
            key = n.type.value
            node_counts[key] = node_counts.get(key, 0) + 1
        for e in self.edges:
            key = e.type.value
            edge_counts[key] = edge_counts.get(key, 0) + 1
        return {
            "nodes": len(self.nodes),
            "edges": len(self.edges),
            "cards": node_counts.get(NodeType.wiki_card.value, 0),
            **{f"node_{k}": v for k, v in sorted(node_counts.items())},
            **{f"edge_{k}": v for k, v in sorted(edge_counts.items())},
        }
