"""Serialize knowledge graph for interactive visualization (vis-network)."""
from __future__ import annotations

from store_brief.kg.schema import EdgeType, KnowledgeGraph, NodeType

_NODE_COLORS: dict[str, str] = {
    NodeType.post.value: "#5b9bd5",
    NodeType.attachment.value: "#9b7ede",
    NodeType.content_slice.value: "#8a8a8a",
    NodeType.wiki_card.value: "#e8b339",
    NodeType.product.value: "#5cb87a",
    NodeType.damdang.value: "#e06c75",
}

_SPINE_EDGES = {
    EdgeType.has_attachment,
    EdgeType.has_slice,
    EdgeType.summarized_as,
    EdgeType.from_post,
    EdgeType.cites_attachment,
    EdgeType.relevant_to,
}

_CATALOG_EDGES = {
    EdgeType.mentions,
    EdgeType.routed_to,
}


def _truncate(s: str, n: int = 48) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"


def _node_title(node) -> str:
    lines = [f"[{node.type.value}] {node.label}"]
    props = node.props or {}
    if node.type == NodeType.wiki_card:
        prov = props.get("provenance") or {}
        if prov.get("attachment_name"):
            lines.append(f"첨부: {prov['attachment_name']}")
        codes = props.get("product_codes") or []
        if codes:
            lines.append(f"상품: {', '.join(codes[:6])}")
    elif node.type == NodeType.product:
        if props.get("prd_nm"):
            lines.append(str(props["prd_nm"]))
        if props.get("damdang"):
            lines.append(f"담당: {', '.join(props['damdang'])}")
    elif node.type == NodeType.post:
        if props.get("posted_date"):
            lines.append(str(props["posted_date"]))
    return "\n".join(lines)


def graph_for_viz(
    graph: KnowledgeGraph,
    *,
    mode: str = "spine",
    damdang: str | None = None,
    include_products: bool = False,
    include_co_occurs: bool = False,
) -> dict:
    """Build vis-network payload: { nodes, edges, meta }."""
    mode = (mode or "spine").lower()
    allowed_types: set[NodeType] | None = None
    allowed_edges: set[EdgeType] | None = None

    if mode == "full":
        allowed_edges = set(EdgeType)
        if not include_co_occurs:
            allowed_edges.discard(EdgeType.co_occurs)
        if not include_products:
            allowed_types = {
                NodeType.post,
                NodeType.attachment,
                NodeType.content_slice,
                NodeType.wiki_card,
                NodeType.damdang,
            }
    elif mode == "cards":
        allowed_types = {
            NodeType.wiki_card,
            NodeType.post,
            NodeType.attachment,
            NodeType.damdang,
        }
        if include_products:
            allowed_types.add(NodeType.product)
        allowed_edges = {
            EdgeType.from_post,
            EdgeType.cites_attachment,
            EdgeType.relevant_to,
            EdgeType.mentions,
            EdgeType.routed_to,
        }
    else:  # spine
        allowed_types = {
            NodeType.post,
            NodeType.attachment,
            NodeType.content_slice,
            NodeType.wiki_card,
            NodeType.damdang,
        }
        allowed_edges = set(_SPINE_EDGES)

    if include_products and allowed_types is not None:
        allowed_types.add(NodeType.product)
        allowed_edges = (allowed_edges or set()) | _CATALOG_EDGES

    node_ids: set[str] = set()
    if damdang:
        d_nid = f"damdang:{damdang}"
        seed: set[str] = set()
        for n in graph.nodes:
            if n.type == NodeType.damdang and n.props.get("name") == damdang:
                seed.add(n.id)
            if n.type == NodeType.wiki_card and n.props.get("damdang") == damdang:
                seed.add(n.id)
        if d_nid in {n.id for n in graph.nodes}:
            seed.add(d_nid)
        # Expand 2 hops from seed
        frontier = set(seed)
        for _ in range(3):
            nxt: set[str] = set()
            for e in graph.edges:
                if e.source in frontier:
                    nxt.add(e.target)
                if e.target in frontier:
                    nxt.add(e.source)
            frontier |= nxt
        node_ids = frontier

    vis_nodes: list[dict] = []
    vis_edges: list[dict] = []

    nodes_by_id = graph.node_by_id()
    for n in graph.nodes:
        if allowed_types and n.type not in allowed_types:
            continue
        if damdang and n.id not in node_ids:
            continue
        size = 12
        if n.type == NodeType.wiki_card:
            size = 22
        elif n.type == NodeType.post:
            size = 18
        elif n.type == NodeType.damdang:
            size = 16
        vis_nodes.append(
            {
                "id": n.id,
                "label": _truncate(n.label, 36),
                "group": n.type.value,
                "title": _node_title(n),
                "color": _NODE_COLORS.get(n.type.value, "#aaa"),
                "size": size,
                "font": {"size": n.type == NodeType.wiki_card and 13 or 11},
            },
        )

    included = {n["id"] for n in vis_nodes}
    for e in graph.edges:
        if allowed_edges and e.type not in allowed_edges:
            continue
        if e.source not in included or e.target not in included:
            continue
        vis_edges.append(
            {
                "id": e.id,
                "from": e.source,
                "to": e.target,
                "title": e.type.value,
                "arrows": "to",
                "color": {"opacity": 0.35},
                "width": 1 if e.type == EdgeType.co_occurs else 1.5,
                "dashes": e.type == EdgeType.co_occurs,
            },
        )

    return {
        "nodes": vis_nodes,
        "edges": vis_edges,
        "meta": {
            "as_of": graph.as_of,
            "mode": mode,
            "damdang": damdang,
            "node_count": len(vis_nodes),
            "edge_count": len(vis_edges),
            "groups": list(_NODE_COLORS.keys()),
        },
    }
