"""Deterministic date extraction from Korean notice/promotion text."""
from __future__ import annotations

import re
from datetime import date

# 6/1~6/30 or 6/5~8
_MD_RANGE_RE = re.compile(
    r"(\d{1,2})/(\d{1,2})\s*[~\-–]\s*(\d{1,2})/(\d{1,2})"
)
# 2026.06.01~2026.06.30 or 2026-06-01 ~ 2026-06-30
_ISO_RANGE_RE = re.compile(
    r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})\s*[~\-–]\s*"
    r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})"
)
_ISO_DATE_RE = re.compile(r"(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})")
# 6월1일부 변경, 6월 12일부터
_KR_EFFECTIVE_RE = re.compile(
    r"(\d{1,2})\s*월\s*(\d{1,2})\s*일(?:부터|부|부터\s*적용|부\s*변경|부터\s*시행)"
)
_KR_MONTH_DAY_RE = re.compile(r"(\d{1,2})\s*월\s*(\d{1,2})\s*일")


def _safe_date(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_validity_range(text: str, *, year: int) -> tuple[date | None, date | None]:
    """Best-effort promotion/event window from body text."""
    m = _ISO_RANGE_RE.search(text)
    if m:
        vf = _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        vt = _safe_date(int(m.group(4)), int(m.group(5)), int(m.group(6)))
        if vf and vt:
            return vf, vt

    m = _MD_RANGE_RE.search(text)
    if m:
        m1, d1, m2, d2 = (int(m.group(i)) for i in range(1, 5))
        vf = _safe_date(year, m1, d1)
        vt = _safe_date(year, m2, d2)
        if vf and vt:
            return vf, vt

    # 6/5~8 → same month (June 5–8)
    short = re.search(r"(\d{1,2})/(\d{1,2})\s*[~\-–]\s*(\d{1,2})(?!\d|/)", text)
    if short:
        mo, d1, d2 = int(short.group(1)), int(short.group(2)), int(short.group(3))
        vf = _safe_date(year, mo, d1)
        vt = _safe_date(year, mo, d2)
        if vf and vt:
            return vf, vt

    iso = _ISO_DATE_RE.search(text)
    if iso:
        d = _safe_date(int(iso.group(1)), int(iso.group(2)), int(iso.group(3)))
        return d, None

    return None, None


def parse_all_validity_ranges(text: str, *, year: int) -> list[tuple[date, date | None]]:
    """All date windows in a cell or line (e.g. ``6/5~8, 6/12~15``)."""
    text = (text or "").strip()
    if not text:
        return []

    windows: list[tuple[date, date | None]] = []
    seen: set[tuple[date, date | None]] = set()
    for part in re.split(r"[,;]\s*", text):
        part = part.strip()
        if not part:
            continue
        vf, vt = parse_validity_range(part, year=year)
        if vf is None:
            continue
        key = (vf, vt)
        if key not in seen:
            seen.add(key)
            windows.append(key)

    if not windows:
        vf, vt = parse_validity_range(text, year=year)
        if vf:
            windows.append((vf, vt))
    return windows


def parse_effective_date(text: str, *, year: int) -> date | None:
    """Policy/change effective date (시행일·적용일)."""
    m = _KR_EFFECTIVE_RE.search(text)
    if m:
        return _safe_date(year, int(m.group(1)), int(m.group(2)))

    for pat in (
        r"시행(?:일)?\s*[:：]?\s*(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})",
        r"적용(?:일)?\s*[:：]?\s*(20\d{2})[.\-/](\d{1,2})[.\-/](\d{1,2})",
    ):
        m = re.search(pat, text)
        if m:
            return _safe_date(int(m.group(1)), int(m.group(2)), int(m.group(3)))

    m = _KR_MONTH_DAY_RE.search(text)
    if m and any(k in text for k in ("시행", "적용", "변경", "개정")):
        return _safe_date(year, int(m.group(1)), int(m.group(2)))

    return None
