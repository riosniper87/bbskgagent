"""Build persistent search index from WikiCards."""
from __future__ import annotations

import logging
from pathlib import Path

from store_brief.index.search import CardSearchIndex, SearchIndexMeta, default_index_path
from store_brief.llmwiki.card import WikiCard

log = logging.getLogger(__name__)


def card_search_text(card: WikiCard) -> str:
    parts = [
        card.post_title,
        card.headline,
        card.body or "",
        card.attachment_name or "",
        " ".join(card.keywords or []),
        " ".join(card.product_codes or []),
    ]
    return " ".join(p for p in parts if p).strip()


def build_search_index(
    cards: list[WikiCard],
    out_dir: str | Path,
    *,
    as_of: str,
) -> SearchIndexMeta:
    """Build and persist BM25 index for all WikiCards."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "search_index.pkl"

    card_ids: list[str] = []
    documents: list[str] = []
    for card in cards:
        text = card_search_text(card)
        if not text.strip():
            continue
        card_ids.append(card.id)
        documents.append(text)

    index = CardSearchIndex.from_documents(card_ids, documents, as_of=as_of)
    index.save(out_path)
    meta = SearchIndexMeta(
        as_of=as_of,
        card_count=len(card_ids),
        built_at=index.built_at,
        path=str(out_path),
    )
    log.info(
        "search index: %d cards -> %s",
        meta.card_count,
        out_path,
    )
    return meta


def build_search_index_for_as_of(
    cards: list[WikiCard],
    data_dir: str | Path,
    as_of: str,
) -> SearchIndexMeta:
    out_dir = default_index_path(data_dir, as_of).parent
    return build_search_index(cards, out_dir, as_of=as_of)
