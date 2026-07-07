"""Extract HISIS product codes (PRD_CD) from free text."""
from __future__ import annotations

import re

# Examples: PLX-MCK02PDB, CBT-LFF32W, BD-N310P, HRF-SN470SM, SM-S942NLBEKOO
PRD_CODE_RE = re.compile(
    r"\b[A-Z][A-Z0-9]{1,4}-[A-Z0-9][A-Z0-9.-]{2,}\b",
)
# 부가서비스/설치 코드: INS-FAN(STAND), CT-OPTION-MOLD
SERVICE_CODE_RE = re.compile(
    r"\b[A-Z]{2,4}-[A-Z][A-Z0-9]*\([A-Z]+\)|"
    r"\b[A-Z]{2,4}-[A-Z][A-Z0-9]{2,}\b",
)
_MODEL_SKU_RE = re.compile(
    r"\b(?:\(J\))?[A-Z][A-Z0-9]{2,}_[A-Z0-9]{2,}\b",
)


def extract_model_skus(*texts: str | None) -> list[str]:
    """Store SKU tokens (e.g. V8100_BK) not matching HISIS PRD_CD pattern."""
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        for match in _MODEL_SKU_RE.findall(text.upper()):
            if match not in seen:
                seen.add(match)
                found.append(match)
    return found


FILE_EXT_RE = re.compile(
    r"\.(PNG|JPG|JPEG|GIF|WEBP|PDF|PPTX?|XLSX?|XLSB|DOCX?|HWPDX?)\b",
    re.IGNORECASE,
)

# Weekly guides often list dozens of SKUs; prefer category fallback for routing.
MAX_ROUTING_DAMDANGS = 4


def _prepare_text(text: str) -> str:
    return FILE_EXT_RE.sub("", text)


def extract_prd_codes(*texts: str | None) -> list[str]:
    """Return unique PRD_CD-like tokens found in texts (uppercase, stable order)."""
    found: list[str] = []
    seen: set[str] = set()
    for text in texts:
        if not text:
            continue
        cleaned = _prepare_text(text)
        upper = cleaned.upper()
        for match in SERVICE_CODE_RE.findall(upper):
            if match not in seen:
                seen.add(match)
                found.append(match)
        for match in PRD_CODE_RE.findall(upper):
            if match in seen:
                continue
            if any(s.startswith(match + "(") for s in seen):
                continue
            if match not in seen:
                seen.add(match)
                found.append(match)
    return found
