"""Brand / maker hints for Q&A answer composition."""
from __future__ import annotations

import re
from dataclasses import dataclass

from store_brief.qa.schemas import RetrievalHit

# 질문에서 인식할 메이커·브랜드 (별칭 → 표준 라벨)
_BRAND_ALIASES: list[tuple[str, str]] = [
    ("삼성전자", "삼성"),
    ("삼성", "삼성"),
    ("엘지", "LG"),
    ("lg", "LG"),
    ("위니아딤채", "위니아"),
    ("위니아", "위니아"),
    ("쿠쿠", "쿠쿠"),
    ("하이얼", "하이얼"),
    ("대우", "대우"),
    ("tcl", "TCL"),
    ("샤프", "샤프"),
    ("미닉스", "미닉스"),
    ("필립스", "필립스"),
    ("다이슨", "다이슨"),
    ("샤크", "샤크"),
    ("드리미", "드리미"),
    ("보스", "BOSE"),
    ("bose", "BOSE"),
    ("애플", "애플"),
    ("apple", "애플"),
    ("마이디어", "마이디어"),
    ("플럭스", "PLUX"),
    ("plux", "PLUX"),
    ("하이마트 pb", "PLUX"),
    ("pb", "PLUX"),
]

_PB_MARKERS = ("plux", "플럭스", "plx-", "하이마트 pb", "[pb]")
_GENERIC_HEADLINES = frozenset({
    "일반", "벽걸이", "값정리", "sheet1", "구독내역조회", "벽걸이형",
})

_PLX_CODE_RE = re.compile(r"\bPLX-", re.I)


@dataclass
class BrandContext:
    requested: list[str]
    guidance: str


def detect_requested_brands(question: str) -> list[str]:
    """Brands explicitly mentioned in the user question (stable order)."""
    q = question.lower()
    found: list[str] = []
    for alias, label in _BRAND_ALIASES:
        if alias in q and label not in found:
            found.append(label)
    return found


def infer_card_brands(hit: RetrievalHit) -> list[str]:
    """Heuristic brand tags for a retrieval card."""
    blob = " ".join([
        hit.post_title,
        hit.headline,
        hit.attachment_name,
        hit.body_excerpt,
        " ".join(hit.product_codes[:12]),
        hit.tables_summary or "",
    ]).lower()

    tags: list[str] = []
    if any(m in blob for m in _PB_MARKERS) or _PLX_CODE_RE.search(blob):
        tags.append("PLUX")
    for alias, label in _BRAND_ALIASES:
        if label == "PLUX":
            continue
        if alias in blob and label not in tags:
            tags.append(label)
    if "lg/" in blob or "lg·" in blob or "lg/" in blob.replace(" ", ""):
        if "LG" not in tags:
            tags.append("LG")
    if not tags:
        tags.append("미분류")
    return tags


def _card_matches_request(tags: list[str], requested: list[str]) -> bool:
    if not requested:
        return True
    req = set(requested)
    card = set(tags) - {"미분류"}
    if not card:
        return False
    # PLUX 질문이면 PLUX 카드만, OEM 질문이면 PLUX 단독 카드 제외
    if req == {"PLUX"}:
        return "PLUX" in card
    if "PLUX" in req:
        return bool(card & req)
    if card == {"PLUX"}:
        return False
    return bool(card & req) or any(
        f"{a}/{b}" in " ".join(tags) or f"{a}·{b}" in " ".join(tags)
        for a in req for b in card
    )


def build_brand_context(question: str, hits: list[RetrievalHit]) -> BrandContext:
    requested = detect_requested_brands(question)
    if not requested:
        return BrandContext(requested=[], guidance="")

    lines = [
        f"[브랜드 필터] 질문에서 요청한 브랜드: {', '.join(requested)}",
        "아래 카드별 [추정 브랜드] 태그를 참고하세요.",
        "",
        "답변 규칙:",
        "- 질문에 특정 브랜드(메이커)가 있으면, 해당 브랜드 판촉·행사·모델만 답하세요.",
        "- PLUX/플럭스/PLX- 상품코드는 롯데하이마트 PB(자사 PB)입니다. "
        "삼성·LG 등 메이커 질문에는 PLUX 단독 카드를 답변 본문에 넣지 마세요.",
        "- 반대로 PLUX·플럭스·PB 질문이면 PLUX/PB 내용만 답하세요.",
        "- LG/삼성 혼합 공지는 질문 브랜드에 해당하는 부분만 발췌하세요.",
        "- 참조 카드에 해당 브랜드 내용이 없으면, "
        "'해당 브랜드 전용 판촉 카드를 찾지 못했습니다'라고 말하고 "
        "혼합 공지에서 관련 한 줄만 언급하세요.",
        "",
        "카드 적합성:",
    ]
    for i, h in enumerate(hits, 1):
        tags = infer_card_brands(h)
        ok = _card_matches_request(tags, requested)
        title = display_title(h)
        lines.append(
            f"  카드{i} [{', '.join(tags)}] "
            f"{'✓ 사용 가능' if ok else '✗ 질문 브랜드와 불일치 — 본문 제외'} — {title}",
        )
    return BrandContext(requested=requested, guidance="\n".join(lines))


def display_title(hit: RetrievalHit) -> str:
    """Prefer post_title when headline is a generic slide label."""
    hl = (hit.headline or "").strip()
    pt = (hit.post_title or "").strip()
    if not pt:
        return hl or "(제목 없음)"
    if not hl or hl in _GENERIC_HEADLINES or len(hl) <= 4:
        return pt
    if hl == pt or hl in pt:
        return pt
    return f"{pt} / {hl}"
