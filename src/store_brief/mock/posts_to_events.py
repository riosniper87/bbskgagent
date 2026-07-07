"""Heuristic post -> Event conversion without vLLM (for mock/sample reports)."""
from __future__ import annotations

import hashlib
import re
from datetime import date

from store_brief.extract.schema import ALL_BRANCHES, Event, EventType
from store_brief.temporal.parse import parse_validity_range

_CAT_KEYWORDS: list[tuple[str, list[str]]] = [
    ("대형가전", ["대형가전", "냉장고", "세탁기", "건조기", "에어컨", "원바디"]),
    ("주방", ["주방", "커피머신", "정수기", "음식물", "취사", "레인지", "밥솥"]),
    ("TV·영상", ["TV", "티비", "영상", "OLED"]),
    ("모바일·IT", ["IT", "PC", "노트북", "키보드", "태블릿", "스마트폰"]),
    ("계절가전", ["선풍기", "에어컨", "겨울", "여름", "계절"]),
    ("생활가전", ["생활", "청소기", "공기청정", "생활주방", "NON-POG"]),
    ("KBB", ["KBB", "비데", "욕실"]),
    ("Hobby", ["Hobby", "취미"]),
    ("스마트홈", ["스마트", "ISP", "POG", "연출"]),
    ("케어·헬스", ["케어", "헬스", "안마"]),
]

_DATE_RANGE_RE = re.compile(
    r"(\d{1,2})/(\d{1,2})\s*[~\-–]\s*(\d{1,2})/(\d{1,2})"
)
_ISO_DATE_RE = re.compile(r"(20\d{2})-(\d{2})-(\d{2})")


def _event_id(post_id: str, title: str) -> str:
    return hashlib.sha1(f"{post_id}|{title}".encode()).hexdigest()[:16]


def _infer_categories(text: str) -> list[str]:
    found = [cat for cat, kws in _CAT_KEYWORDS if any(k in text for k in kws)]
    return found or ["기타"]


def _infer_type(text: str, has_end: bool) -> EventType:
    if any(w in text for w in ("정책", "개정", "시행", "변경 안내")):
        return EventType.policy
    if any(w in text for w in ("판촉", "특가", "할인", "행사")) or has_end:
        return EventType.promotion
    if any(w in text for w in ("재고", "소진", "입고", "품절")):
        return EventType.price_stock
    if any(w in text for w in ("이벤트", "시연", "페스티벌")):
        return EventType.event
    return EventType.notice


def _parse_dates(text: str, year: int) -> tuple[date | None, date | None]:
    return parse_validity_range(text, year=year)


def _summary(body: str, title: str, max_len: int = 220) -> str:
    text = body.replace("\n", " ").strip()
    if not text:
        return title
    # skip boilerplate lines
    for chunk in re.split(r"[。\n]|\. ", text):
        chunk = chunk.strip()
        if len(chunk) > 20 and "프롬프트" not in chunk and "【" not in chunk:
            return chunk[:max_len] + ("…" if len(chunk) > max_len else "")
    return (text[:max_len] + "…") if len(text) > max_len else text


def posts_to_events(posts, *, as_of: date) -> list[Event]:
    """Convert board posts into Events using title/body heuristics."""
    events: list[Event] = []
    for post in posts:
        blob = f"{post.title}\n{post.body}"
        cats = _infer_categories(blob)
        vf, vt = _parse_dates(blob, post.posted_date.year)
        etype = _infer_type(blob, has_end=vt is not None)
        summary = _summary(post.body, post.title)

        events.append(Event(
            id=_event_id(post.id, post.title),
            type=etype,
            title=post.title,
            summary=summary,
            theme=cats[0] if cats[0] != "기타" else "운영 공지",
            categories=cats,
            branches=[ALL_BRANCHES],
            valid_from=vf,
            valid_to=vt,
            effective_date=post.posted_date if etype == EventType.policy else None,
            source_post_id=post.id,
            attachment_refs=[a.filename for a in post.attachments],
            raw_excerpt=post.body[:500],
            first_seen=post.posted_date,
            last_updated=post.posted_date,
        ))
    return events
