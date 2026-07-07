"""Search-only Q&A (no LLM intent/answer)."""
from __future__ import annotations

import time
from datetime import date

from store_brief.llmwiki.grouping import load_qa_damdang_roster
from store_brief.qa.bm25 import tokenize
from store_brief.qa.corpus import QACorpus, load_corpus
from store_brief.qa.schemas import QASearchBody, QASearchResponse, TemporalScope, TimeMode, ToolTrace
from store_brief.qa.tools.retrieve import retrieve_wiki_cards


def simple_keywords(question: str) -> list[str]:
    return tokenize(question)


def search_wiki_cards(
    corpus: QACorpus,
    *,
    question: str,
    damdangs: list[str],
    keywords: list[str] | None = None,
    query_date: date | None = None,
    limit: int = 10,
) -> QASearchResponse:
    started = time.perf_counter()
    kws = list(keywords) if keywords else simple_keywords(question)
    if not kws and question.strip():
        kws = [question.strip()]

    temporal = TemporalScope(
        time_mode=TimeMode.none,
        query_date=query_date,
        description="search-only",
    )
    hits = retrieve_wiki_cards(
        corpus,
        keywords=kws,
        damdangs=damdangs,
        temporal_scope=temporal,
        limit=limit,
        relax_notice_kinds=True,
        query_date=query_date,
    )
    trace = ToolTrace(
        tool="retrieve_wiki_cards",
        input={"question": question, "keywords": kws, "damdangs": damdangs, "limit": limit},
        output={"count": len(hits), "card_ids": [h.card_id for h in hits]},
        ms=int((time.perf_counter() - started) * 1000),
    )
    return QASearchResponse(
        hits=hits,
        damdangs_used=damdangs,
        index_loaded=corpus.search_index is not None,
        traces=[trace],
    )


def resolve_search_damdangs(
    *,
    damdang: str | None,
    rnr_path: str,
) -> list[str]:
    roster = load_qa_damdang_roster(rnr_path)
    if damdang and damdang in roster:
        return [damdang]
    return list(roster)


def load_search_corpus(data_dir: str, as_of: str) -> QACorpus:
    return load_corpus(data_dir, as_of)
