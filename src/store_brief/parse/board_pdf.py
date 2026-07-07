"""Parse SV board '게시물출력.pdf' exports into structured post fields.

These PDFs are browser printouts with labeled fields (제목, 등록일, 내용, etc.).
Label text may be garbled by PyMuPDF; we use positional heuristics + regex fallbacks.
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

_ISO_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ATTACH_HINT_RE = re.compile(r"※\s*첨부파일\s*[:：]\s*(.+)", re.MULTILINE)
_FOOTER_RE = re.compile(r"^\d+/\d+$|^higw\.himart|^26\.\s*\d")
_PRINT_DATE_RE = re.compile(r"^\d{2}\.\s*\d{1,2}\.\s*\d{1,2}\.")


@dataclass
class BoardPostDraft:
    id: str
    title: str
    body: str
    posted_date: date
    attachment_hints: list[str]
    author: str | None = None


def _raw_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if line and line.replace("\xa0", "").strip():
            lines.append(line.replace("\xa0", " ").strip())
    return lines


def _find_date_idx(lines: list[str]) -> int | None:
    for i, line in enumerate(lines):
        if _ISO_DATE_RE.match(line):
            return i
    return None


def _is_body_end(line: str) -> bool:
    if _FOOTER_RE.match(line) or _PRINT_DATE_RE.match(line):
        return True
    if line in ("인쇄", "닫기", "게시물 출력", "주요공지"):
        return True
    if "higw.himart" in line:
        return True
    return False


def parse_board_pdf(pdf_path: str | Path, *, folder_name: str = "") -> BoardPostDraft:
    import fitz  # PyMuPDF

    doc = fitz.open(str(pdf_path))
    full_text = "\n".join(page.get_text() for page in doc)
    lines = _raw_lines(full_text)

    date_idx = _find_date_idx(lines)
    posted_date = date.today()
    title = folder_name
    author: str | None = None
    body = ""

    if date_idx is not None:
        m = _ISO_DATE_RE.match(lines[date_idx])
        if m:
            posted_date = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        if date_idx >= 4:
            title = lines[date_idx - 4]
        if date_idx >= 2:
            author = lines[date_idx - 2]
        body_start = date_idx + 2
        if body_start < len(lines) and len(lines[body_start]) < 20:
            body_start += 1
        body_lines = []
        for line in lines[body_start:]:
            if _is_body_end(line):
                break
            body_lines.append(line)
        body = "\n".join(body_lines).strip()
    else:
        dm = re.search(r"(20\d{2})-(\d{2})-(\d{2})", full_text)
        if dm:
            posted_date = date(int(dm.group(1)), int(dm.group(2)), int(dm.group(3)))

    if not title or title == folder_name:
        title = folder_name or lines[0] if lines else "제목 없음"

    hints: list[str] = []
    for m in _ATTACH_HINT_RE.finditer(full_text):
        hint = m.group(1).strip()
        if hint and hint not in hints:
            hints.append(hint)

    post_id = hashlib.sha1(f"{title}|{posted_date.isoformat()}".encode()).hexdigest()[:12]

    return BoardPostDraft(
        id=post_id,
        title=title.strip(),
        body=body.strip(),
        posted_date=posted_date,
        attachment_hints=hints,
        author=author,
    )
