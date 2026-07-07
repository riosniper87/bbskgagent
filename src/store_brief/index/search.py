"""Load and query persistent BM25 search index."""
from __future__ import annotations

import pickle
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from store_brief.qa.bm25 import BM25Index, tokenize


@dataclass
class SearchIndexMeta:
    as_of: str
    card_count: int
    built_at: str
    path: str


class CardSearchIndex:
    """BM25 index keyed by WikiCard id."""

    def __init__(
        self,
        *,
        card_ids: list[str],
        documents: list[str],
        k1: float = 1.5,
        b: float = 0.75,
        as_of: str = "",
        built_at: str = "",
    ):
        self.card_ids = card_ids
        self._id_to_idx = {cid: i for i, cid in enumerate(card_ids)}
        self._bm25 = BM25Index(documents, k1=k1, b=b)
        self.as_of = as_of
        self.built_at = built_at

    @property
    def card_count(self) -> int:
        return len(self.card_ids)

    def score(self, query: str, card_id: str) -> float:
        idx = self._id_to_idx.get(card_id)
        if idx is None:
            return 0.0
        return self._bm25.score(query, idx)

    def score_all(self, query: str) -> dict[str, float]:
        if not self.card_ids:
            return {}
        scores = self._bm25.score_all(query)
        return {cid: scores[i] for i, cid in enumerate(self.card_ids)}

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "as_of": self.as_of,
            "built_at": self.built_at or datetime.now(timezone.utc).isoformat(),
            "card_ids": self.card_ids,
            "documents": self._bm25.docs,
            "k1": self._bm25.k1,
            "b": self._bm25.b,
            "n": self._bm25.n,
            "avgdl": self._bm25.avgdl,
            "df": dict(self._bm25.df),
        }
        with path.open("wb") as f:
            pickle.dump(payload, f, protocol=pickle.HIGHEST_PROTOCOL)
        return path

    @classmethod
    def load(cls, path: str | Path) -> CardSearchIndex:
        path = Path(path)
        with path.open("rb") as f:
            payload = pickle.load(f)
        card_ids = list(payload["card_ids"])
        tokenized_docs = payload["documents"]
        k1 = float(payload.get("k1", 1.5))
        b = float(payload.get("b", 0.75))
        idx = cls(
            card_ids=card_ids,
            documents=[""] * len(card_ids),
            k1=k1,
            b=b,
            as_of=str(payload.get("as_of", "")),
            built_at=str(payload.get("built_at", "")),
        )
        idx._bm25.docs = tokenized_docs
        idx._bm25.n = int(payload.get("n", len(tokenized_docs)))
        idx._bm25.avgdl = float(payload.get("avgdl", 0.0))
        from collections import Counter
        idx._bm25.df = Counter(payload.get("df", {}))
        return idx

    @classmethod
    def from_documents(
        cls,
        card_ids: list[str],
        documents: list[str],
        *,
        as_of: str = "",
    ) -> CardSearchIndex:
        built_at = datetime.now(timezone.utc).isoformat()
        return cls(
            card_ids=card_ids,
            documents=documents,
            as_of=as_of,
            built_at=built_at,
        )


def default_index_path(data_dir: str | Path, as_of: str) -> Path:
    return Path(data_dir) / "index" / as_of / "search_index.pkl"


def tokenize_query(text: str) -> list[str]:
    return tokenize(text)
