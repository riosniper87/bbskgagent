"""Extract searchable keywords from WikiCard content."""
from __future__ import annotations

import re
from pathlib import Path

from store_brief.extract.provenance import keyword_set, title_anchors
from store_brief.llmwiki.card import WikiCard

_MAX_KEYWORDS = 40

_DOMAIN_EXPANSIONS: dict[str, tuple[str, ...]] = {
    "광고": ("콘텐츠", "마케팅", "브랜드"),
    "계정": ("공용", "비즈니스", "단체"),
    "콘텐츠": ("광고", "검수", "마케팅"),
    "마케팅": ("광고", "브랜드", "콘텐츠"),
    "브랜드": ("마케팅", "광고"),
    "플친": ("카카오", "친구", "발송"),
    "sns": ("광고", "콘텐츠"),
}


def _attachment_stem(name: str) -> str:
    stem = Path(name).stem if name else ""
    return re.sub(r"\s+", " ", stem).strip()


def extract_card_keywords(card: WikiCard) -> list[str]:
    """Build keyword list from title, attachment, headline, body."""
    parts = [
        card.post_title,
        card.attachment_name,
        card.headline,
        card.body or "",
    ]
    if card.vlm and card.vlm.description:
        parts.append(card.vlm.description)

    found: set[str] = set()
    for text in parts:
        found |= keyword_set(text)
        for anchor in title_anchors(text):
            found.add(anchor)

    stem = _attachment_stem(card.attachment_name)
    if stem and stem not in ("(게시글 본문)", "Sheet1", "table0"):
        for w in re.findall(r"[가-힣]{2,}", stem):
            found.add(w)

    blob = "\n".join(parts).lower()
    expanded: set[str] = set()
    for kw in list(found):
        low = kw.lower()
        for seed, related in _DOMAIN_EXPANSIONS.items():
            if seed in low or low == seed:
                for r in related:
                    if r in blob:
                        expanded.add(r)

    found |= expanded
    found -= {"", "sheet", "table", "슬라이드", "페이지"}

    ordered = sorted(found, key=lambda x: (-len(x), x))
    return ordered[:_MAX_KEYWORDS]


def enrich_card_keywords(card: WikiCard) -> WikiCard:
    card.keywords = extract_card_keywords(card)
    return card


def enrich_cards_keywords(cards: list[WikiCard]) -> None:
    for card in cards:
        enrich_card_keywords(card)
