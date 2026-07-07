"""Standalone image -> hand straight to the VLM (no text to parse here).

PaddleOCR fallback hook lives here for later; prototype uses VLM-only extraction.
"""
from __future__ import annotations

from store_brief.parse.router import ParsedAttachment


def parse(attachment, workdir: str) -> ParsedAttachment:
    ref = f"{attachment.id}#img0"
    return ParsedAttachment(attachment.id, text="", image_paths=[(attachment.path, ref)])
    # FUTURE: if VLM extraction proves unreliable, add PaddleOCR here and reconcile.
