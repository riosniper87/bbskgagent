"""Attachment parsing: normalize each file into text + extractable images.

Runs on the NPU/CPU box — no model here by default. Each parser returns a ParsedAttachment:
  - text: everything textual the file contains (already-structured, model-free)
  - image_paths: (path, source_ref) of images to hand to the VLM later
  - tables / raw_sheets / layouts: Excel structured outputs (VLM layout optional)
"""
from __future__ import annotations

from dataclasses import dataclass, field

from store_brief.parse.excel_tables import SheetTable
from store_brief.parse.layout_schema import PageRecord, RawSheet, TableLayoutSheet


@dataclass
class ParsedAttachment:
    attachment_id: str
    text: str = ""
    image_paths: list[tuple[str, str]] = field(default_factory=list)  # (path, source_ref)
    tables: list[SheetTable] = field(default_factory=list)
    raw_sheets: list[RawSheet] = field(default_factory=list)
    layouts: list[TableLayoutSheet] = field(default_factory=list)
    pages: list[PageRecord] = field(default_factory=list)
    parse_mode: str = ""


def parse(attachment, workdir: str, **kwargs) -> ParsedAttachment:
    """Dispatch by kind. `attachment` is schema.Attachment; `workdir` holds extracted images."""
    from store_brief.parse import excel, image, pdf, pptx

    kind = getattr(attachment, "kind", "unknown")
    handler = {
        "excel": excel.parse,
        "pptx": pptx.parse,
        "pdf": pdf.parse,
        "image": image.parse,
    }.get(kind)
    if handler is None:
        return ParsedAttachment(attachment_id=attachment.id, text="")
    if kind == "excel":
        return handler(attachment, workdir, **kwargs)
    return handler(attachment, workdir)
