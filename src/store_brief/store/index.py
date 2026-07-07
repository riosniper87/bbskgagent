"""Embedding index for fuzzy recall (relevance/retrieve.py).

Stub: embeddings run on the NPU/CPU box (e.g. bge-m3, multilingual incl. Korean) and a
small local index (sqlite-vec or FAISS) is enough at this scale. Deterministic R&R mapping
is primary; this only widens recall, so it is optional for the first run.
"""
from __future__ import annotations


class VectorIndex:
    def __init__(self, embed_model: str | None = None):
        self.embed_model = embed_model
        self._items: list[tuple[str, str]] = []  # (event_id, text)

    def add(self, event) -> None:
        self._items.append((event.id, f"{event.title} {event.summary}"))

    def search(self, query: str, k: int = 10) -> list[str]:
        # FUTURE: embed query + items, cosine top-k. Stub returns nothing so
        # deterministic R&R mapping is not polluted with arbitrary events.
        return []
