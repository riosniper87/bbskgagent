"""Shared URL helpers for parse viewer media paths."""
from __future__ import annotations

from urllib.parse import quote


def media_url(post_id: str, rel_path: str | None) -> str | None:
    if not rel_path:
        return None
    rel = rel_path.replace("\\", "/")
    encoded = "/".join(quote(part, safe="") for part in rel.split("/"))
    return f"/media/parsed/{post_id}/{encoded}"
