"""Load WikiCard corpus + KG provenance for Q&A."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from store_brief.index.search import CardSearchIndex, default_index_path
from store_brief.kg.build import card_from_dict, load_cards_from_llmwiki
from store_brief.kg.load import default_graph_path, load_knowledge_graph
from store_brief.kg.schema import NodeType
from store_brief.llmwiki.card import WikiCard
from store_brief.llmwiki.keywords import enrich_card_keywords

log = logging.getLogger(__name__)


@dataclass
class QACorpus:
    as_of: str
    cards: list[WikiCard] = field(default_factory=list)
    provenance_by_card: dict[str, dict] = field(default_factory=dict)
    search_index: CardSearchIndex | None = None
    search_index_path: str | None = None


def load_corpus(data_dir: str | Path, as_of: str) -> QACorpus:
    data_dir = Path(data_dir)
    llmwiki_path = data_dir / "llmwiki" / as_of / "llmwiki.json"
    if not llmwiki_path.is_file():
        raise FileNotFoundError(f"llmwiki not found: {llmwiki_path}")

    cards = [card_from_dict(c) for c in load_cards_from_llmwiki(llmwiki_path)]
    for card in cards:
        if not card.keywords:
            enrich_card_keywords(card)
    prov: dict[str, dict] = {}

    gp = default_graph_path(data_dir, as_of)
    if gp.is_file():
        graph = load_knowledge_graph(gp)
        for n in graph.node_by_id().values():
            if n.type != NodeType.wiki_card:
                continue
            cid = n.props.get("card_id")
            if cid and n.props.get("provenance"):
                prov[cid] = n.props["provenance"]

    search_index: CardSearchIndex | None = None
    index_path = default_index_path(data_dir, as_of)
    if index_path.is_file():
        try:
            search_index = CardSearchIndex.load(index_path)
            log.info("loaded search index: %d cards from %s", search_index.card_count, index_path)
        except Exception as exc:
            log.warning("failed to load search index %s: %s", index_path, exc)
    else:
        log.warning("search index missing at %s — per-query BM25 fallback", index_path)

    return QACorpus(
        as_of=as_of,
        cards=cards,
        provenance_by_card=prov,
        search_index=search_index,
        search_index_path=str(index_path) if index_path.is_file() else None,
    )
