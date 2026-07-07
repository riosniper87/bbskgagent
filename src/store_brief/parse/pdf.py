"""PDF -> text; rasterize pages that look image/diagram-heavy for the VLM.

Heuristic for the prototype: if a page has little extractable text, render it to PNG and
let the VLM read it. Tune the threshold once we see real documents.
"""
from __future__ import annotations

import os

from store_brief.parse.layout_schema import PageRecord
from store_brief.parse.router import ParsedAttachment

MIN_TEXT_CHARS = 40


def parse(attachment, workdir: str) -> ParsedAttachment:
    import fitz  # PyMuPDF, lazy

    doc = fitz.open(attachment.path)
    pages: list[PageRecord] = []
    images: list[tuple[str, str]] = []
    text_blocks: list[str] = []

    for i, page in enumerate(doc):
        idx = i + 1
        ref = f"{attachment.id}#p{idx}"
        text = page.get_text().strip()
        image_path: str | None = None

        if len(text) >= MIN_TEXT_CHARS:
            text_blocks.append(f"### p{idx}\n{text}")
        else:
            out = os.path.join(workdir, ref.replace("#", "_") + ".png")
            page.get_pixmap(dpi=150).save(out)
            images.append((out, ref))
            image_path = out

        pages.append(PageRecord(index=idx, ref=ref, text=text, image_path=image_path))

    return ParsedAttachment(
        attachment.id,
        text="\n\n".join(text_blocks),
        image_paths=images,
        pages=pages,
    )
