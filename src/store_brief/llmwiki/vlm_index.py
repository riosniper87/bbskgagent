"""Index VLM ImageNotes by source_ref (read from store; no event grouping)."""
from __future__ import annotations

from datetime import date

from store_brief.extract.schema import ImageNote


def load_vlm_index(store, as_of: date, weeks: int = 4) -> dict[str, ImageNote]:
    """Flatten all VLM notes in the retention window, keyed by source_ref."""
    index: dict[str, ImageNote] = {}
    for event in store.load_recent(as_of, weeks):
        for img in event.images:
            if img.source_ref and img.source_ref not in index:
                index[img.source_ref] = img
    return index
