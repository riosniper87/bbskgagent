"""Wiki card — one routed slice of parsed/VLM content (not a store Event)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import date

from store_brief.extract.schema import ExtractedTable, ImageNote
from store_brief.temporal.meta import TemporalMeta


@dataclass
class WikiCard:
    damdang: str
    post_id: str
    post_title: str
    posted_date: date
    source_ref: str
    attachment_name: str
    product_codes: list[str] = field(default_factory=list)
    headline: str = ""
    body: str = ""
    vlm: ImageNote | None = None
    tables: list[ExtractedTable] = field(default_factory=list)
    temporal: TemporalMeta = field(default_factory=TemporalMeta)
    keywords: list[str] = field(default_factory=list)

    @property
    def id(self) -> str:
        raw = f"{self.source_ref}|{self.damdang}"
        return hashlib.sha1(raw.encode()).hexdigest()[:16]

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "damdang": self.damdang,
            "post_id": self.post_id,
            "post_title": self.post_title,
            "posted_date": self.posted_date.isoformat(),
            "source_ref": self.source_ref,
            "attachment_name": self.attachment_name,
            "product_codes": self.product_codes,
            "keywords": self.keywords,
            "headline": self.headline,
            "body": self.body,
            "temporal": self.temporal.to_dict(),
            "vlm": self.vlm.model_dump() if self.vlm else None,
            "tables": [t.model_dump() for t in self.tables],
        }

    def to_export_dict(self) -> dict:
        """Serialize for llmwiki.json (omit bulky embedded tables)."""
        d = self.to_dict()
        d.pop("tables", None)
        return d
