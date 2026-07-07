"""Parse question intent via LLM structured output."""
from __future__ import annotations

import re
from datetime import date

from store_brief.llm.client import LLMClient
from store_brief.qa.schemas import QuestionIntent, TimeMode

_SYSTEM = """당신은 매장 공지/판촉 Q&A 시스템의 질문 분석기입니다.
반드시 아래 형태의 JSON 객체 하나만 출력하세요 (배열/문자열 단독 금지).

{
  "keywords": ["키워드1", "키워드2"],
  "damdang_hints": [],
  "product_codes": [],
  "notice_kinds": ["공지"],
  "time_mode": "active_on",
  "query_date": "2026-06-15",
  "date_from": null,
  "date_to": null,
  "refine_query": null
}

규칙:
- damdang_hints: 질문에 담당/품목이 명확할 때만 채우세요. 불확실하면 빈 배열 []. 추측 금지.
- 마케팅/광고/계정/브랜드/SNS/운영 정책 질문은 damdang_hints를 비우세요.
- keywords: 검색에 쓸 핵심 명사 2~6개

time_mode는 다음 중 하나의 문자열만: active_on, posted_between, observable_on, version_diff, none
- 판촉/행사/적용기간 질문 -> active_on
- 지난달 공지 -> posted_between
- 개정/변경 비교 -> version_diff
"""

_PRD_RE = re.compile(r"\b[A-Z]{2,4}-[A-Z0-9]{4,}\b")

_MARKETING_TERMS = (
    "광고", "콘텐츠", "계정", "브랜드", "마케팅", "sns", "플친", "카카오", "검수",
)

_INVENTORY_TERMS = (
    "진열소진", "소진현황", "재고확인", "재고현황", "지사지점재고확인",
)

_PRODUCT_DAMDANGS = (
    "대형가전1", "대형가전2", "생활주방", "생활리빙", "IT", "KBB", "주방",
    "스마트가전", "스마트폰", "모바일", "PC솔루션", "Hobby", "애플",
)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if v is not None and str(v).strip()]
    s = str(value).strip()
    if not s:
        return []
    if "," in s:
        return [p.strip() for p in s.split(",") if p.strip()]
    return [s]


def _parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    s = str(value).strip()
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        return None


def _normalize_time_mode(value) -> str:
    if isinstance(value, TimeMode):
        return value.value
    if isinstance(value, str) and value in {m.value for m in TimeMode}:
        return value
    if isinstance(value, dict):
        for key in ("time_mode", "mode", "active_on"):
            if isinstance(value.get(key), str):
                return _normalize_time_mode(value[key])
        if value.get("date_from") or value.get("date_to"):
            return TimeMode.active_on.value
    return TimeMode.none.value


def _is_marketing_question(question: str) -> bool:
    q = question.lower()
    return any(t in q for t in _MARKETING_TERMS)


def normalize_intent_dict(raw: dict, *, question: str = "") -> dict:
    if not isinstance(raw, dict):
        raw = {}

    keywords = _as_list(raw.get("keywords"))
    if not keywords and question:
        keywords = [w for w in re.split(r"\s+", question) if len(w) >= 2][:8]

    damdang_hints = _as_list(raw.get("damdang_hints"))

    if _is_marketing_question(question):
        damdang_hints = [
            h for h in damdang_hints
            if h in question or h == "지원" or h == "케어서비스"
        ]
        if "지원" not in damdang_hints and "지원" in question:
            damdang_hints.append("지원")

    for hint in ("대형가전1", "대형가전2", "생활주방", "생활리빙", "IT", "KBB", "주방", "스마트가전", "케어서비스", "지원"):
        if hint in question and hint not in damdang_hints:
            damdang_hints.append(hint)

    if _is_marketing_question(question):
        damdang_hints = [h for h in damdang_hints if h not in _PRODUCT_DAMDANGS or h in question]

    if any(w in question for w in ("서비스", "SCM", "조립 서비스", "조립서비스", "설치")):
        if "케어서비스" not in damdang_hints:
            damdang_hints.append("케어서비스")
    if any(w in question for w in ("선풍기", "냉풍기", "계절가전")):
        for d in ("생활주방", "생활리빙"):
            if d not in damdang_hints:
                damdang_hints.append(d)
    if any(w in question for w in ("오클린", "구강", "전동칫솔", "칫솔")):
        if "생활리빙" not in damdang_hints:
            damdang_hints.append("생활리빙")
    if any(w in question for w in ("노트북", "조립pc", "조립 pc", "조립PC")):
        for d in ("PC솔루션", "IT"):
            if d not in damdang_hints:
                damdang_hints.append(d)

    product_codes = _as_list(raw.get("product_codes"))
    product_codes.extend(_PRD_RE.findall(question.upper()))

    notice_kinds = _as_list(raw.get("notice_kinds"))
    if not notice_kinds and any(w in question for w in ("판촉", "행사", "할인")):
        notice_kinds = ["판촉"]
    if not notice_kinds and any(
        w in question for w in ("서비스", "조립", "설치", "정책", "시행", "코드 안내", "유의사항")
    ):
        notice_kinds = ["정책", "공지"]
    if not notice_kinds and _is_marketing_question(question):
        notice_kinds = ["공지", "정책"]
    if any(w in question for w in _INVENTORY_TERMS):
        # 진열소진/재고 엑셀은 notice_kind=판촉 — 공지 필터만 쓰면 누락됨
        notice_kinds = []

    time_mode = _normalize_time_mode(raw.get("time_mode"))
    if time_mode == TimeMode.none.value and any(
        w in question for w in ("판촉", "행사", "중순", "초순", "말")
    ):
        time_mode = TimeMode.active_on.value

    return {
        "keywords": keywords,
        "damdang_hints": damdang_hints,
        "product_codes": list(dict.fromkeys(product_codes)),
        "notice_kinds": notice_kinds,
        "time_mode": time_mode,
        "query_date": _parse_date(raw.get("query_date")),
        "date_from": _parse_date(raw.get("date_from")),
        "date_to": _parse_date(raw.get("date_to")),
        "refine_query": raw.get("refine_query"),
    }


def parse_question_intent(
    llm: LLMClient,
    *,
    question: str,
    default_query_date: date | None = None,
    damdang_roster: list[str] | None = None,
) -> QuestionIntent:
    roster = ", ".join(damdang_roster or [])
    prompt = f"""질문: {question}

기준일(as_of): {default_query_date.isoformat() if default_query_date else "없음"}
담당 목록: {roster}

위 질문을 분석해 JSON 객체 하나만 출력하세요."""

    try:
        raw = llm.complete_json(prompt, system=_SYSTEM)
        if isinstance(raw, dict) and "data" in raw and len(raw) == 1:
            raw = raw["data"]
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        raw = {}

    normalized = normalize_intent_dict(raw, question=question)
    intent = QuestionIntent.model_validate(normalized)

    if intent.query_date is None and default_query_date:
        if intent.time_mode in (TimeMode.active_on, TimeMode.observable_on):
            intent.query_date = default_query_date
        elif intent.time_mode == TimeMode.posted_between and intent.date_to is None:
            intent.date_to = default_query_date

    if intent.time_mode == TimeMode.active_on and intent.query_date is None and default_query_date:
        intent.query_date = default_query_date

    return intent
