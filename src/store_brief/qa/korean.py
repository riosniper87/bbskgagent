"""Deterministic Korean query normalization: particle stripping + stopwords.

Used for LLM-free intent fallback, retrieval scoring variants, and BM25
tokenization. Stripping never replaces a token — callers get the original
plus a stripped variant, so nouns ending in josa-lookalike syllables are safe.
"""
from __future__ import annotations

import re

# Longest-first so multi-syllable particles win over single-syllable ones.
_JOSA_SUFFIXES: tuple[str, ...] = (
    "에서는", "에서도", "으로는", "으로도", "까지는", "까지도", "부터는",
    "에서", "에게", "께서", "부터", "까지", "으로", "이나", "이랑", "이며",
    "조차", "처럼", "마다", "밖에", "보다", "하고", "에는", "에도", "로는",
    "와의", "과의", "이라", "인지",
    "은", "는", "이", "가", "을", "를", "의", "에", "도", "만", "로",
    "와", "과", "랑", "나", "요",
)

# Question words / filler tokens that dilute BM25 when the LLM parse fails
# and the raw question is split into keywords.
_QUESTION_STOPWORDS: frozenset[str] = frozenset({
    "언제", "언제야", "언제까지", "언제부터", "어디", "어디서", "어디에",
    "어떻게", "어떡해", "무엇", "무엇을", "뭐", "뭐야", "뭔가요", "뭐예요",
    "뭐에요", "무슨", "어떤", "어느", "왜", "누가", "누구", "몇",
    "알려줘", "알려줘요", "알려주세요", "알려주실", "해주세요", "해줘",
    "주세요", "궁금합니다", "궁금해요", "궁금", "설명해줘", "설명",
    "있나요", "있어요", "있는지", "있습니까", "인가요", "인가", "일까요",
    "하나요", "합니까", "되나요", "됐나요", "됩니까", "되는지",
    "관련", "관련해서", "관련된", "대해", "대해서", "대한", "내용",
    "정보", "문의", "질문", "확인", "부탁", "좀", "그리고", "혹시",
    "어떻게되나요", "얼마", "얼마나", "얼마야", "얼마인가요",
})

_TOKEN_RE = re.compile(r"[\w가-힣]+", re.UNICODE)
_HANGUL_RE = re.compile(r"[가-힣]")

_MIN_STEM_LEN = 2


def strip_josa(token: str) -> str:
    """Return token with a trailing josa removed, or the token unchanged.

    Only strips when the remaining stem keeps at least _MIN_STEM_LEN chars,
    and only for Hangul tokens.
    """
    if not token or not _HANGUL_RE.search(token):
        return token
    for suffix in _JOSA_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= _MIN_STEM_LEN:
            return token[: -len(suffix)]
    return token


def keyword_variants(keyword: str) -> list[str]:
    """Return [keyword] or [keyword, stripped] when stripping changes it."""
    k = (keyword or "").strip()
    if not k:
        return []
    stripped = strip_josa(k)
    if stripped != k:
        return [k, stripped]
    return [k]


def expand_keywords(keywords: list[str]) -> list[str]:
    """Expand keywords with particle-stripped variants, order-preserving."""
    out: list[str] = []
    seen: set[str] = set()
    for kw in keywords:
        for v in keyword_variants(kw):
            lv = v.lower()
            if lv not in seen:
                seen.add(lv)
                out.append(v)
    return out


def is_question_stopword(token: str) -> bool:
    t = token.strip().lower()
    return t in _QUESTION_STOPWORDS or strip_josa(t) in _QUESTION_STOPWORDS


def extract_question_keywords(question: str, *, limit: int = 8) -> list[str]:
    """Deterministic keyword extraction for when LLM intent parsing fails.

    Tokenizes, drops question stopwords and 1-char tokens, strips particles
    (keeping the stem), dedupes preserving order.
    """
    out: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(question or ""):
        if len(token) < 2:
            continue
        if is_question_stopword(token):
            continue
        stem = strip_josa(token)
        if len(stem) < 2 or is_question_stopword(stem):
            continue
        key = stem.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(stem)
        if len(out) >= limit:
            break
    return out
