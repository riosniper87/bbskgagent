"""Lightweight BM25 scoring for Q&A retrieval (no external deps)."""
from __future__ import annotations

import math
import re
from collections import Counter

from store_brief.qa.korean import strip_josa

_TOKEN_RE = re.compile(r"[\w가-힣]+", re.UNICODE)


def tokenize(text: str) -> list[str]:
    """Tokenize with josa dual-emit: each token yields itself plus its
    particle-stripped variant (when different), so doc-side "냉장고는" and
    query-side "냉장고" match in both directions. Never replaces tokens.
    """
    out: list[str] = []
    for t in _TOKEN_RE.findall(text or ""):
        if len(t) < 2:
            continue
        low = t.lower()
        out.append(low)
        stem = strip_josa(low)
        if stem != low and len(stem) >= 2:
            out.append(stem)
    return out


class BM25Index:
    def __init__(self, documents: list[str], *, k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[list[str]] = [tokenize(d) for d in documents]
        self.n = len(self.docs)
        self.avgdl = sum(len(d) for d in self.docs) / self.n if self.n else 0.0
        self.df: Counter[str] = Counter()
        for doc in self.docs:
            for term in set(doc):
                self.df[term] += 1

    def score(self, query: str, doc_idx: int) -> float:
        if doc_idx < 0 or doc_idx >= self.n:
            return 0.0
        doc = self.docs[doc_idx]
        if not doc:
            return 0.0
        dl = len(doc)
        tf = Counter(doc)
        total = 0.0
        for term in tokenize(query):
            if term not in tf:
                continue
            idf = math.log(1 + (self.n - self.df[term] + 0.5) / (self.df[term] + 0.5))
            freq = tf[term]
            denom = freq + self.k1 * (1 - self.b + self.b * dl / (self.avgdl or 1))
            total += idf * (freq * (self.k1 + 1)) / denom
        return total

    def score_all(self, query: str) -> list[float]:
        return [self.score(query, i) for i in range(self.n)]
