"""Load Event objects for llmwiki re-export."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from store_brief.extract.schema import Event, EventType, ExtractedTable, ImageNote


def _parse_date(value: str | date | None) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def event_from_dict(data: dict) -> Event:
    payload = dict(data)
    if isinstance(payload.get("type"), str):
        payload["type"] = EventType(payload["type"])
    for key in ("valid_from", "valid_to", "effective_date", "first_seen", "last_updated"):
        if key in payload:
            payload[key] = _parse_date(payload.get(key))
    if "tables" in payload:
        payload["tables"] = [ExtractedTable(**t) for t in payload["tables"]]
    if "images" in payload:
        payload["images"] = [ImageNote(**i) for i in payload["images"]]
    allowed = set(Event.model_fields)
    return Event(**{k: v for k, v in payload.items() if k in allowed})


def events_from_llmwiki_json(path: str | Path) -> list[Event]:
    """Deduplicate events embedded in llmwiki.json (same id may appear in multiple sections)."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    by_id: dict[str, dict] = {}
    for block in data.get("damdang", {}).values():
        for theme_events in block.get("themes", {}).values():
            for item in theme_events:
                by_id[item["id"]] = item
    return [event_from_dict(d) for d in by_id.values()]
