"""WikiCards from board post bodies (service/policy notices without attachment codes)."""
from __future__ import annotations

import re
from datetime import date

from store_brief.hisis.prd_codes import extract_prd_codes
from store_brief.ingest.board import Post
from store_brief.llmwiki.card import WikiCard
from store_brief.llmwiki.grouping import (
    FALLBACK_KEY,
    MANAGER_KEY,
    product_codes_for_damdang,
    product_damdang_for_codes,
)
from store_brief.temporal.meta import extract_temporal_meta

_MIN_BODY_LEN = 80
_BOILERPLATE = ("프롬프트", "【")
_MAX_BODY = 1_200

# (keyword in title/body, roster 담당 names)
_KEYWORD_DAMDANG: list[tuple[str, list[str]]] = [
    ("조립서비스", ["케어서비스"]),
    ("조립 서비스", ["케어서비스"]),
    ("scm서비스", ["케어서비스"]),
    ("scm", ["케어서비스"]),
    ("케어서비스", ["케어서비스"]),
    ("안심케어", ["케어서비스"]),
    ("입주청소", ["케어서비스"]),
    ("매트리스청소", ["케어서비스"]),
    ("선풍기", ["생활주방", "생활리빙"]),
    ("오클린", ["생활리빙"]),
    ("구강용품", ["생활리빙"]),
    ("구강", ["생활리빙"]),
    ("전동칫솔", ["생활리빙"]),
    ("냉풍기", ["생활주방", "생활리빙"]),
    ("계절가전", ["생활주방", "생활리빙"]),
    ("조립pc", ["IT", "PC솔루션"]),
    ("조립 pc", ["IT", "PC솔루션"]),
    ("노트북", ["IT", "PC솔루션"]),
    ("광고", [FALLBACK_KEY]),
    ("콘텐츠", [FALLBACK_KEY]),
    ("isp", [FALLBACK_KEY]),
    ("체크리스트", [FALLBACK_KEY]),
    ("냉장고", ["대형가전1", "대형가전2"]),
    ("에어컨", ["대형가전1", "대형가전2"]),
]

_TITLE_DAMDANG_RE = re.compile(
    r"\[(대형가전1|대형가전2|생활리빙|생활주방|스마트가전|스마트폰|"
    r"PC솔루션|IT|KBB|주방|Hobby|애플|케어서비스|지원)\]",
    re.I,
)


def _usable_body(body: str) -> bool:
    text = (body or "").strip()
    if len(text) < _MIN_BODY_LEN:
        return False
    if any(b in text for b in _BOILERPLATE):
        return False
    return True


def infer_damdangs_from_text(text: str, roster: set[str]) -> list[str]:
    """Keyword/heuristic 담당 when HISIS product routing is unavailable."""
    blob = text.lower()
    out: list[str] = []
    for kw, damdangs in _KEYWORD_DAMDANG:
        if kw.lower() in blob:
            for d in damdangs:
                if d in roster and d not in out:
                    out.append(d)
    for m in _TITLE_DAMDANG_RE.finditer(text):
        d = m.group(1)
        if d in roster and d not in out:
            out.append(d)
    return out


def collect_post_body_cards(
    posts: dict[str, Post],
    *,
    lookup: dict[str, tuple[str, ...]],
    roster: set[str],
    covered_post_ids: set[str] | None = None,
) -> list[WikiCard]:
    """One WikiCard per post body when content is substantive."""
    covered = covered_post_ids or set()
    cards: list[WikiCard] = []

    for post_id, post in posts.items():
        if post_id in covered:
            continue
        body = (post.body or "").strip()
        if not _usable_body(body):
            continue

        if len(body) > _MAX_BODY:
            body = body[:_MAX_BODY] + "\n…(생략)"

        blob = f"{post.title}\n{body}"
        codes = extract_prd_codes(blob)
        damdangs = _filter_roster(product_damdang_for_codes(codes, lookup), roster)
        if not damdangs:
            damdangs = infer_damdangs_from_text(blob, roster)
        if not damdangs:
            continue

        source_ref = f"{post_id}#body"
        headline = post.title[:120]
        card_temporal = extract_temporal_meta(
            text=blob,
            posted_date=post.posted_date,
            title=headline,
            filename="",
            damdang=damdangs[0],
        )

        for damdang in damdangs:
            codes_for_d = product_codes_for_damdang(codes, damdang, lookup) if codes else list(codes)
            cards.append(
                WikiCard(
                    damdang=damdang,
                    post_id=post_id,
                    post_title=post.title,
                    posted_date=post.posted_date,
                    source_ref=source_ref,
                    attachment_name="(게시글 본문)",
                    product_codes=codes_for_d or list(codes),
                    headline=headline,
                    body=body,
                    temporal=card_temporal,
                ),
            )
    return cards


def _filter_roster(damdangs: list[str], roster: set[str]) -> list[str]:
    out: list[str] = []
    for d in damdangs:
        if d in roster and d != MANAGER_KEY and d not in out:
            out.append(d)
    return out
