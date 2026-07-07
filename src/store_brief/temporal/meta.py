"""Temporal metadata for WikiCard — time-based search, not just 'latest'."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import TYPE_CHECKING

from store_brief.temporal.parse import parse_effective_date, parse_validity_range
from store_brief.temporal.tables import apply_table_windows, windows_from_tables

if TYPE_CHECKING:
    from store_brief.extract.schema import ExtractedTable


class NoticeKind(str, Enum):
    promotion = "판촉"
    policy = "정책"
    notice = "공지"
    price_stock = "재고·가격"
    event = "이벤트"
    unknown = "기타"


@dataclass
class TemporalMeta:
    """Structured time fields for deterministic filtering and version chains."""

    notice_kind: NoticeKind = NoticeKind.unknown
    valid_from: date | None = None
    valid_to: date | None = None
    effective_date: date | None = None
    topic_key: str | None = None
    version_of: str | None = None
    event_windows: list[tuple[date, date | None]] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "notice_kind": self.notice_kind.value,
            "valid_from": self.valid_from.isoformat() if self.valid_from else None,
            "valid_to": self.valid_to.isoformat() if self.valid_to else None,
            "effective_date": self.effective_date.isoformat() if self.effective_date else None,
            "topic_key": self.topic_key,
            "version_of": self.version_of,
            "event_windows": [
                {
                    "from": a.isoformat(),
                    "to": b.isoformat() if b else None,
                }
                for a, b in self.event_windows
            ],
        }

    @classmethod
    def from_dict(cls, data: dict | None) -> TemporalMeta:
        if not data:
            return cls()
        kind_raw = data.get("notice_kind") or NoticeKind.unknown.value
        try:
            kind = NoticeKind(kind_raw)
        except ValueError:
            kind = NoticeKind.unknown

        def _d(key: str) -> date | None:
            v = data.get(key)
            if not v:
                return None
            return date.fromisoformat(v) if isinstance(v, str) else v

        def _windows(raw: list | None) -> list[tuple[date, date | None]]:
            out: list[tuple[date, date | None]] = []
            for w in raw or []:
                if not isinstance(w, dict):
                    continue
                a = w.get("from")
                b = w.get("to")
                if not a:
                    continue
                out.append((
                    date.fromisoformat(a) if isinstance(a, str) else a,
                    date.fromisoformat(b) if isinstance(b, str) and b else None,
                ))
            return out

        return cls(
            notice_kind=kind,
            valid_from=_d("valid_from"),
            valid_to=_d("valid_to"),
            effective_date=_d("effective_date"),
            topic_key=data.get("topic_key"),
            version_of=data.get("version_of"),
            event_windows=_windows(data.get("event_windows")),
        )


def _infer_kind(text: str, *, has_end: bool) -> NoticeKind:
    if any(w in text for w in ("정책", "개정", "시행", "변경 안내", "변경의 건", "변경", "서비스 안내", "조립 서비스")):
        return NoticeKind.policy
    if any(w in text for w in ("판촉", "특가", "할인", "행사", "중점 행사")) or has_end:
        return NoticeKind.promotion
    if any(w in text for w in ("재고", "소진", "입고", "품절")):
        return NoticeKind.price_stock
    if any(w in text for w in ("이벤트", "시연", "페스티벌")):
        return NoticeKind.event
    if any(w in text for w in ("공지", "안내", "교육")):
        return NoticeKind.notice
    return NoticeKind.unknown


def _normalize_attachment_stem(filename: str) -> str:
    stem = re.sub(r"\.[^.]+$", "", filename or "")
    stem = re.sub(r"[_\s]*(v\d+|ver\d+)$", "", stem, flags=re.I)
    stem = re.sub(r"\d{6,8}", "", stem)
    return stem.strip("_ ").lower()


def topic_key_for_card(
    *,
    damdang: str,
    attachment_name: str,
    headline: str,
    notice_kind: NoticeKind,
) -> str | None:
    """Stable key to link policy/update chains across posts."""
    if notice_kind not in (NoticeKind.policy, NoticeKind.notice, NoticeKind.promotion):
        return None
    stem = _normalize_attachment_stem(attachment_name)
    if not stem and headline:
        stem = headline[:80].lower()
    if not stem:
        return None
    raw = f"{damdang}|{notice_kind.value}|{stem}"
    return hashlib.sha1(raw.encode()).hexdigest()[:16]


def extract_temporal_meta(
    *,
    text: str,
    posted_date: date,
    title: str = "",
    filename: str = "",
    damdang: str = "",
    tables: list[ExtractedTable] | None = None,
) -> TemporalMeta:
    blob = "\n".join(p for p in (title, filename, text) if p)
    year = posted_date.year
    vf, vt = parse_validity_range(blob, year=year)
    eff = parse_effective_date(blob, year=year)
    kind = _infer_kind(blob, has_end=vt is not None)

    if kind == NoticeKind.policy and eff is None:
        eff = posted_date
    if kind == NoticeKind.promotion and vf is None and vt is not None:
        vf = posted_date

    topic = topic_key_for_card(
        damdang=damdang,
        attachment_name=filename,
        headline=title,
        notice_kind=kind,
    )
    meta = TemporalMeta(
        notice_kind=kind,
        valid_from=vf,
        valid_to=vt,
        effective_date=eff,
        topic_key=topic,
    )
    if tables:
        table_windows = windows_from_tables(tables, year=year)
        apply_table_windows(meta, table_windows)
    return meta


def link_card_versions(cards: list) -> None:
    """Set version_of on newer cards that supersede an older card with the same topic_key."""
    by_topic: dict[str, list] = {}
    for card in cards:
        tm = getattr(card, "temporal", None) or TemporalMeta.from_dict(
            getattr(card, "temporal", None)
        )
        if not tm.topic_key:
            continue
        by_topic.setdefault(tm.topic_key, []).append(card)

    for group in by_topic.values():
        if len(group) < 2:
            continue
        group.sort(
            key=lambda c: (
                _card_sort_date(c) or date.min,
                getattr(c, "posted_date", date.min),
            ),
        )
        for prev, cur in zip(group, group[1:]):
            cur_tm = cur.temporal
            prev_tm = prev.temporal
            if cur_tm.version_of:
                continue
            cur_tm.version_of = prev.id


def _card_sort_date(card) -> date | None:
    tm = card.temporal
    return tm.effective_date or tm.valid_from or getattr(card, "posted_date", None)
