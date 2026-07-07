"""Build knowledge graph from llmwiki.json + raw/parsed provenance."""
from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from store_brief.ingest import board
from store_brief.kg.enrich import load_hisis_cache, product_props, roster_damdangs
from store_brief.kg.provenance import (
    attachment_node_id,
    body_excerpt,
    build_card_provenance,
    damdang_node_id,
    find_attachment,
    keyword_node_id,
    post_node_id,
    product_node_id,
    slice_node_id,
)
from store_brief.kg.schema import EdgeType, GraphEdge, GraphNode, KnowledgeGraph, NodeType
from store_brief.llmwiki.card import WikiCard
from store_brief.llmwiki.keywords import enrich_card_keywords
from store_brief.temporal.meta import TemporalMeta


def _edge_id(edge_type: EdgeType, source: str, target: str) -> str:
    raw = f"{edge_type.value}|{source}|{target}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def load_cards_from_llmwiki(path: str | Path) -> list[dict]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    cards: list[dict] = []
    for block in data.get("damdang", {}).values():
        for card in block.get("cards") or []:
            cards.append(card)
    return cards


def card_from_dict(data: dict) -> WikiCard:
    from datetime import date as date_cls

    vlm = None
    if data.get("vlm"):
        from store_brief.extract.schema import ImageNote

        vlm = ImageNote(**data["vlm"])
    tables = []
    if data.get("tables"):
        from store_brief.extract.schema import ExtractedTable

        tables = [ExtractedTable(**t) for t in data["tables"]]
    posted = data["posted_date"]
    if isinstance(posted, str):
        posted = date_cls.fromisoformat(posted)
    return WikiCard(
        damdang=data["damdang"],
        post_id=data["post_id"],
        post_title=data["post_title"],
        posted_date=posted,
        source_ref=data["source_ref"],
        attachment_name=data["attachment_name"],
        product_codes=list(data.get("product_codes") or []),
        keywords=list(data.get("keywords") or []),
        headline=data.get("headline") or "",
        body=data.get("body") or "",
        vlm=vlm,
        tables=tables,
        temporal=TemporalMeta.from_dict(data.get("temporal")),
    )


class GraphBuilder:
    def __init__(self) -> None:
        self._nodes: dict[str, GraphNode] = {}
        self._edges: dict[str, GraphEdge] = {}
        self._card_index: dict[str, str] = {}

    def _add_node(self, node: GraphNode) -> None:
        if node.id not in self._nodes:
            self._nodes[node.id] = node
        else:
            existing = self._nodes[node.id]
            merged = {**existing.props, **node.props}
            self._nodes[node.id] = existing.model_copy(update={"props": merged})

    def _add_edge(self, edge: GraphEdge) -> None:
        self._edges[edge.id] = edge

    def ensure_post(self, post) -> str:
        nid = post_node_id(post.id)
        self._add_node(
            GraphNode(
                id=nid,
                type=NodeType.post,
                label=post.title[:120],
                props={
                    "post_id": post.id,
                    "title": post.title,
                    "posted_date": post.posted_date.isoformat(),
                    "body_excerpt": body_excerpt(post.body),
                },
            ),
        )
        return nid

    def ensure_attachment(self, post, attachment) -> str:
        nid = attachment_node_id(attachment.id)
        self._add_node(
            GraphNode(
                id=nid,
                type=NodeType.attachment,
                label=attachment.filename,
                props={
                    "attachment_id": attachment.id,
                    "filename": attachment.filename,
                    "kind": attachment.kind,
                    "path": attachment.path,
                    "post_id": post.id,
                },
            ),
        )
        post_nid = self.ensure_post(post)
        self._add_edge(
            GraphEdge(
                id=_edge_id(EdgeType.has_attachment, post_nid, nid),
                type=EdgeType.has_attachment,
                source=post_nid,
                target=nid,
            ),
        )
        return nid

    def ensure_slice(self, source_ref: str, attachment_nid: str) -> str:
        nid = slice_node_id(source_ref)
        self._add_node(
            GraphNode(
                id=nid,
                type=NodeType.content_slice,
                label=source_ref.split("#")[-1] if "#" in source_ref else source_ref,
                props={"source_ref": source_ref},
            ),
        )
        self._add_edge(
            GraphEdge(
                id=_edge_id(EdgeType.has_slice, attachment_nid, nid),
                type=EdgeType.has_slice,
                source=attachment_nid,
                target=nid,
            ),
        )
        return nid

    def ensure_product(self, prd_cd: str, cache: dict) -> str:
        nid = product_node_id(prd_cd)
        props = product_props(prd_cd, cache)
        self._add_node(
            GraphNode(
                id=nid,
                type=NodeType.product,
                label=prd_cd,
                props=props,
            ),
        )
        for d in props.get("damdang") or []:
            d_nid = self.ensure_damdang(d)
            self._add_edge(
                GraphEdge(
                    id=_edge_id(EdgeType.routed_to, nid, d_nid),
                    type=EdgeType.routed_to,
                    source=nid,
                    target=d_nid,
                ),
            )
        return nid

    def ensure_damdang(self, name: str) -> str:
        nid = damdang_node_id(name)
        if nid not in self._nodes:
            self._add_node(
                GraphNode(
                    id=nid,
                    type=NodeType.damdang,
                    label=name,
                    props={"name": name},
                ),
            )
        return nid

    def ensure_keyword(self, keyword: str) -> str:
        kw = keyword.strip()
        if not kw:
            return ""
        nid = keyword_node_id(kw)
        if nid not in self._nodes:
            self._add_node(
                GraphNode(
                    id=nid,
                    type=NodeType.keyword,
                    label=kw,
                    props={"keyword": kw},
                ),
            )
        return nid

    def add_card(
        self,
        card: WikiCard,
        post,
        cache: dict,
        provenance,
    ) -> None:
        card_nid = f"card:{card.id}"
        att = find_attachment(post, card.attachment_name, card.source_ref)
        post_nid = self.ensure_post(post)
        if att:
            att_nid = self.ensure_attachment(post, att)
        else:
            att_nid = attachment_node_id(
                provenance.attachment_id,
            )
            self._add_node(
                GraphNode(
                    id=att_nid,
                    type=NodeType.attachment,
                    label=card.attachment_name,
                    props={
                        "attachment_id": provenance.attachment_id,
                        "filename": card.attachment_name,
                        "path": provenance.attachment_path,
                        "kind": provenance.attachment_kind,
                        "post_id": post.id,
                    },
                ),
            )
            self._add_edge(
                GraphEdge(
                    id=_edge_id(EdgeType.has_attachment, post_nid, att_nid),
                    type=EdgeType.has_attachment,
                    source=post_nid,
                    target=att_nid,
                ),
            )

        slice_nid = self.ensure_slice(card.source_ref, att_nid)
        if not card.keywords:
            enrich_card_keywords(card)
        text_for_retrieval = f"{card.headline}\n{card.body}".strip()
        self._add_node(
            GraphNode(
                id=card_nid,
                type=NodeType.wiki_card,
                label=card.headline[:120] or card.post_title[:120],
                props={
                    "card_id": card.id,
                    "damdang": card.damdang,
                    "headline": card.headline,
                    "body": card.body,
                    "text_for_retrieval": text_for_retrieval[:4000],
                    "product_codes": card.product_codes,
                    "keywords": card.keywords,
                    "damdang_filter": [card.damdang],
                    "posted_date": card.posted_date.isoformat(),
                    "temporal": card.temporal.to_dict(),
                    "provenance": provenance.model_dump(),
                },
            ),
        )
        self._card_index[card.id] = card.damdang

        self._add_edge(
            GraphEdge(
                id=_edge_id(EdgeType.summarized_as, slice_nid, card_nid),
                type=EdgeType.summarized_as,
                source=slice_nid,
                target=card_nid,
            ),
        )
        self._add_edge(
            GraphEdge(
                id=_edge_id(EdgeType.from_post, card_nid, post_nid),
                type=EdgeType.from_post,
                source=card_nid,
                target=post_nid,
            ),
        )
        self._add_edge(
            GraphEdge(
                id=_edge_id(EdgeType.cites_attachment, card_nid, att_nid),
                type=EdgeType.cites_attachment,
                source=card_nid,
                target=att_nid,
            ),
        )
        d_nid = self.ensure_damdang(card.damdang)
        self._add_edge(
            GraphEdge(
                id=_edge_id(EdgeType.relevant_to, card_nid, d_nid),
                type=EdgeType.relevant_to,
                source=card_nid,
                target=d_nid,
            ),
        )

        post_kw_seen: set[str] = set()
        for kw in card.keywords:
            kw_nid = self.ensure_keyword(kw)
            if not kw_nid:
                continue
            self._add_edge(
                GraphEdge(
                    id=_edge_id(EdgeType.tagged_with, card_nid, kw_nid),
                    type=EdgeType.tagged_with,
                    source=card_nid,
                    target=kw_nid,
                ),
            )
            if kw not in post_kw_seen:
                post_kw_seen.add(kw)
                self._add_edge(
                    GraphEdge(
                        id=_edge_id(EdgeType.keyword_in_post, post_nid, kw_nid),
                        type=EdgeType.keyword_in_post,
                        source=post_nid,
                        target=kw_nid,
                    ),
                )

        product_nids: list[str] = []
        for code in card.product_codes:
            p_nid = self.ensure_product(code, cache)
            product_nids.append(p_nid)
            self._add_edge(
                GraphEdge(
                    id=_edge_id(EdgeType.mentions, card_nid, p_nid),
                    type=EdgeType.mentions,
                    source=card_nid,
                    target=p_nid,
                ),
            )

        for i, a in enumerate(product_nids):
            for b in product_nids[i + 1 :]:
                self._add_edge(
                    GraphEdge(
                        id=_edge_id(EdgeType.co_occurs, a, b),
                        type=EdgeType.co_occurs,
                        source=a,
                        target=b,
                    ),
                )

    def build(self, as_of: str) -> KnowledgeGraph:
        return KnowledgeGraph(
            as_of=as_of,
            nodes=list(self._nodes.values()),
            edges=list(self._edges.values()),
            card_index=dict(self._card_index),
        )


def build_knowledge_graph(
    as_of: date,
    *,
    data_dir: str,
    llmwiki_path: str | Path,
    cache_path: str = "data/cache/hisis_prd_damdang.json",
    rnr_path: str = "data/rnr.txt",
) -> KnowledgeGraph:
    posts = {p.id: p for p in board.load_posts_backfill(str(Path(data_dir) / "raw"), as_of)}
    cache_file = Path(cache_path)
    if not cache_file.is_file():
        cache_file = Path(__file__).resolve().parents[3] / cache_path
    cache = load_hisis_cache(cache_file)

    builder = GraphBuilder()
    for name in roster_damdangs(rnr_path):
        builder.ensure_damdang(name)

    for raw in load_cards_from_llmwiki(llmwiki_path):
        card = card_from_dict(raw)
        post = posts.get(card.post_id)
        if post is None:
            continue
        att = find_attachment(post, card.attachment_name, card.source_ref)
        prov = build_card_provenance(
            post=post,
            attachment=att,
            attachment_name=card.attachment_name,
            source_ref=card.source_ref,
            post_title=card.post_title,
        )
        builder.add_card(card, post, cache, prov)

    return builder.build(as_of.isoformat())
