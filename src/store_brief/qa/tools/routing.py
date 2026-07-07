"""Resolve damdang scope from intent + roster."""
from __future__ import annotations

_DAMDANG_ALIASES: dict[str, list[str]] = {
    "대형가전": ["대형가전1", "대형가전2"],
    "대형": ["대형가전1", "대형가전2"],
    "생활가전": ["생활주방", "생활리빙", "주방"],
    "계절가전": ["생활주방", "생활리빙"],
    "선풍기": ["생활주방", "생활리빙"],
    "구강": ["생활리빙"],
    "오클린": ["생활리빙"],
    "칫솔": ["생활리빙"],
    "서비스": ["케어서비스"],
    "scm": ["케어서비스"],
    "케어": ["케어서비스"],
    "브랜드마케팅": ["공통"],
    "브랜드 마케팅": ["공통"],
    "지점관리": ["공통"],
}

_PRODUCT_SIGNALS = (
    "냉장고", "김치냉장고", "세탁기", "건조기", "에어컨", "tv", "티비",
    "선풍기", "제습기", "정수기", "오클린", "칫솔", "노트북", "pc",
    "조립pc", "모니터", "세트", "plux", "plx-", "삼성", "lg",
)

_MARKETING_SIGNALS = (
    "광고", "콘텐츠", "계정", "브랜드", "마케팅", "sns", "플친",
    "카카오", "검수", "연출", "pop",
)

_ROSTER_PRODUCT_DAMDANGS = frozenset({
    "대형가전1", "대형가전2", "생활주방", "생활리빙", "IT", "KBB",
    "주방", "스마트가전", "스마트폰", "모바일", "PC솔루션", "Hobby", "애플",
})


def infer_damdang_confidence(
    *,
    question: str,
    damdang_hints: list[str],
    product_codes: list[str],
    roster: list[str],
    anchor_post_id: str | None = None,
    damdang_override: str | None = None,
) -> str:
    """Return high | medium | low for how aggressively to narrow damdang pool."""
    if damdang_override and damdang_override.strip():
        return "high"
    if anchor_post_id:
        return "high"
    if product_codes:
        return "high"

    q = question.lower()
    roster_set = set(roster)
    literal = [h for h in damdang_hints if h in roster_set and h in question]
    if literal:
        return "high"

    if any(sig in q for sig in ("노트북", "조립pc", "조립 pc")):
        if any(h in ("PC솔루션", "IT") for h in damdang_hints):
            return "high"

    if any(sig in q for sig in _PRODUCT_SIGNALS):
        if damdang_hints:
            return "medium"

    if any(sig in q for sig in _MARKETING_SIGNALS):
        return "low"

    if damdang_hints and not literal:
        return "low"

    return "low"


def _expand_hint(hint: str, roster_set: set[str], out: list[str]) -> None:
    h = hint.strip()
    if not h:
        return
    if h in roster_set and h not in out:
        out.append(h)
        return
    for key, expanded in _DAMDANG_ALIASES.items():
        if key in h or h in key:
            for d in expanded:
                if d in roster_set and d not in out:
                    out.append(d)


def resolve_damdang_scope(
    *,
    damdang_hints: list[str],
    roster: list[str],
    override: str | None = None,
    confidence: str = "low",
    question: str = "",
) -> list[str]:
    if override and override.strip():
        o = override.strip()
        if o in roster:
            return [o]
        return [o]

    roster_set = set(roster)
    out: list[str] = []
    for hint in damdang_hints:
        _expand_hint(hint, roster_set, out)

    # Low confidence: LLM guessed damdang without product/anchor signals — search all
    if confidence == "low" and not override:
        q_marketing = any(s in question for s in _MARKETING_SIGNALS)
        literal_roster = any(h in question for h in damdang_hints if h in roster_set)
        if damdang_hints and not literal_roster:
            if q_marketing or not any(sig in question.lower() for sig in _PRODUCT_SIGNALS):
                return list(roster)

    if not out:
        return list(roster)
    return out


def pool_was_narrowed(damdangs: list[str], roster: list[str]) -> bool:
    return 0 < len(damdangs) < len(roster)
