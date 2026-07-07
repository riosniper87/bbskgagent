"""Retrieve wiki cards with deterministic filters + keyword/BM25 scoring."""
from __future__ import annotations

import re
from datetime import date, timedelta

from store_brief.llmwiki.card import WikiCard
from store_brief.qa.bm25 import BM25Index
from store_brief.qa.corpus import QACorpus
from store_brief.qa.korean import expand_keywords, keyword_variants
from store_brief.qa.schemas import RetrievalHit, TemporalScope, TimeMode
from store_brief.temporal.query import (
    active_on,
    filter_by_notice_kind,
    observable_on,
    posted_between,
    version_pairs,
)

_PRD_RE = re.compile(r"\b[A-Z]{2,4}-[A-Z0-9]{4,}\b")
_PC_ASSEMBLY_RE = re.compile(r"조립\s*pc|조립pc", re.I)
_INVENTORY_RE = re.compile(
    r"진열소진|소진현황|재고확인|재고현황|지사지점재고확인",
    re.I,
)
_SERVICE_CONTEXT = ("서비스", "설치", "scm", "케어", "선풍기", "냉풍기")
_MIN_GOOD_SCORE = 4.0


def _tables_summary(card: WikiCard, max_rows: int = 5) -> str:
    if not card.tables:
        return ""
    lines: list[str] = []
    for tbl in card.tables[:2]:
        cols = tbl.columns or []
        if cols:
            lines.append(" | ".join(str(c) for c in cols))
        for row in (tbl.rows or [])[:max_rows]:
            lines.append(" | ".join(str(c) for c in row))
    return "\n".join(lines)[:2000]


def _card_search_text(card: WikiCard) -> str:
    return f"{card.post_title} {card.headline} {card.body}"


def _norm_kw(kw: str) -> str:
    return kw.lower().strip()


def _keyword_set(keywords: list[str]) -> set[str]:
    return {_norm_kw(k) for k in keywords if _norm_kw(k)}


def keyword_overlap_count(card: WikiCard, keywords: list[str]) -> int:
    """Count query keywords matching card.keywords or indexed text tokens.

    Each query keyword also matches via its josa-stripped variant, but is
    counted at most once.
    """
    kws = [k for k in {_norm_kw(k) for k in keywords} if k]
    if not kws:
        return 0
    card_kw = {_norm_kw(k) for k in (card.keywords or [])}
    text_l = _card_search_text(card).lower()

    kw_overlap = 0
    text_overlap = 0
    for k in kws:
        variants = [_norm_kw(v) for v in keyword_variants(k)]
        if any(v in card_kw for v in variants):
            kw_overlap += 1
        elif any(v in text_l for v in variants):
            text_overlap += 1
    if kw_overlap:
        return kw_overlap
    return text_overlap


def _score_card(
    card: WikiCard,
    keywords: list[str],
    product_codes: list[str],
    *,
    bm25_score: float = 0.0,
    anchor_post_id: str | None = None,
    anchor_source_ref: str | None = None,
    damdang_boost: set[str] | None = None,
    query_date: date | None = None,
) -> float:
    title_l = card.post_title.lower()
    headline_l = (card.headline or "").lower()
    body_l = (card.body or "").lower()
    text_l = f"{title_l} {headline_l} {body_l}"
    score = bm25_score * 1.5
    if anchor_post_id and card.post_id == anchor_post_id:
        score += 35.0
    if anchor_source_ref and card.source_ref == anchor_source_ref:
        score += 45.0
    elif anchor_source_ref and anchor_source_ref in card.source_ref:
        score += 12.0

    matched_kws: list[str] = []
    for kw in keywords:
        k = kw.lower().strip()
        if not k:
            continue
        variants = [v.lower() for v in keyword_variants(k)]
        if any(v in title_l for v in variants):
            score += 5.0
            matched_kws.append(k)
        elif any(v in headline_l for v in variants):
            score += 3.0
            matched_kws.append(k)
        elif any(v in body_l for v in variants):
            score += 2.0
            matched_kws.append(k)

    if len(matched_kws) >= 2:
        score += 3.0 * (len(matched_kws) - 1)

    q_set = _keyword_set(keywords)
    q_expanded = _keyword_set(expand_keywords(list(q_set)))
    card_kw = {_norm_kw(k) for k in (card.keywords or [])}
    if q_set and card_kw:
        overlap = q_expanded & card_kw
        if overlap:
            score += (min(len(overlap), len(q_set)) / max(len(q_set), 1)) * 8.0

    att_l = (card.attachment_name or "").lower()
    for k in q_expanded:
        if k in att_l:
            score += 3.0
            break

    kw_blob = " ".join(keywords).lower()
    if _INVENTORY_RE.search(kw_blob):
        if _INVENTORY_RE.search(att_l):
            score += 10.0
        if "지사지점재고확인" in body_l or "지사지점재고확인" in headline_l:
            score += 8.0
        if "진열소진현황" in att_l:
            score += 6.0
    if "조립" in kw_blob and any(w in kw_blob for w in _SERVICE_CONTEXT):
        if _PC_ASSEMBLY_RE.search(text_l) and "선풍기" not in text_l:
            score -= 4.0
        if "선풍기" in text_l and "조립" in text_l:
            score += 4.0

    for code in product_codes:
        if code.upper() in [c.upper() for c in card.product_codes]:
            score += 5.0
    for m in _PRD_RE.findall(text_l.upper()):
        if m in [c.upper() for c in card.product_codes]:
            score += 1.0

    if damdang_boost:
        if card.damdang in damdang_boost:
            score += 12.0
        else:
            score -= 2.0

    if query_date and card.posted_date:
        days = (query_date - card.posted_date).days
        if 0 <= days <= 90:
            score += max(0.0, 8.0 - days / 12.0)

    return score


def _apply_temporal(cards: list[WikiCard], scope: TemporalScope) -> list[WikiCard]:
    mode = scope.time_mode
    if mode == TimeMode.none:
        return cards
    if mode == TimeMode.version_diff:
        paired = version_pairs(cards)
        ids = set()
        for p in paired:
            if p.get("old"):
                ids.add(p["old"].id)
            if p.get("new"):
                ids.add(p["new"].id)
        if ids:
            return [c for c in cards if c.id in ids]
        return cards

    qd = scope.query_date
    if mode == TimeMode.active_on and qd:
        return active_on(cards, qd)
    if mode == TimeMode.observable_on and qd:
        return observable_on(cards, qd)
    if mode == TimeMode.posted_between:
        df = scope.date_from
        dt = scope.date_to
        if df and dt:
            return posted_between(cards, df, dt)
        if qd:
            return posted_between(cards, qd - timedelta(days=45), qd)
    return cards


def _dedup_by_topic_key(
    hits: list[RetrievalHit],
    cards_by_id: dict[str, WikiCard],
) -> list[RetrievalHit]:
    if not hits:
        return hits
    by_topic: dict[str, list[RetrievalHit]] = {}
    no_topic: list[RetrievalHit] = []
    for h in hits:
        card = cards_by_id.get(h.card_id)
        tk = card.temporal.topic_key if card else None
        if not tk:
            no_topic.append(h)
        else:
            by_topic.setdefault(tk, []).append(h)

    kept: list[RetrievalHit] = list(no_topic)
    for group in by_topic.values():
        best = max(
            group,
            key=lambda h: (
                cards_by_id[h.card_id].posted_date
                if h.card_id in cards_by_id
                else date.min,
                h.score,
            ),
        )
        kept.append(best)
    kept.sort(key=lambda h: (-h.score, h.posted_date))
    return kept


def _hits_from_pool(
    pool: list[WikiCard],
    corpus: QACorpus,
    *,
    keywords: list[str],
    product_codes: list[str],
    limit: int,
    anchor_post_id: str | None = None,
    anchor_source_ref: str | None = None,
    damdang_boost: set[str] | None = None,
    query_date: date | None = None,
    pool_product_filtered: bool = False,
) -> list[RetrievalHit]:
    query = " ".join(keywords)
    bm25_by_id: dict[str, float] | None = None
    if corpus.search_index and query.strip():
        bm25_by_id = corpus.search_index.score_all(query)
    elif pool:
        docs = [_card_search_text(c) for c in pool]
        bm25 = BM25Index(docs)
        scores = bm25.score_all(query) if query.strip() else [0.0] * len(pool)
        bm25_by_id = {c.id: scores[i] for i, c in enumerate(pool)}

    scored = []
    for card in pool:
        bm = bm25_by_id.get(card.id, 0.0) if bm25_by_id else 0.0
        sc = _score_card(
            card, keywords, product_codes, bm25_score=bm,
            anchor_post_id=anchor_post_id, anchor_source_ref=anchor_source_ref,
            damdang_boost=damdang_boost, query_date=query_date,
        )
        scored.append((card, sc))
    scored.sort(key=lambda x: (x[1], x[0].posted_date), reverse=True)

    hits: list[RetrievalHit] = []
    for card, sc in scored[:limit]:
        if sc <= 0 and keywords and not pool_product_filtered:
            continue
        prov = corpus.provenance_by_card.get(card.id, {})
        hits.append(
            RetrievalHit(
                card_id=card.id,
                damdang=card.damdang,
                headline=card.headline or card.post_title,
                post_id=card.post_id,
                post_title=card.post_title,
                posted_date=card.posted_date.isoformat(),
                attachment_name=card.attachment_name,
                source_ref=card.source_ref,
                product_codes=list(card.product_codes),
                score=sc,
                temporal=card.temporal.to_dict(),
                body_excerpt=(card.body or "")[:1500],
                tables_summary=_tables_summary(card),
                provenance=prov,
                post_url=f"/post/{card.post_id}",
            ),
        )

    # Pad with unscored cards only for keyword-less (browse-style) queries.
    # When keywords exist and nothing matched, returning junk hits causes
    # wrong answers — an empty result lets the caller relax filters instead.
    if not hits and pool and (not keywords or pool_product_filtered):
        for card in pool[:limit]:
            prov = corpus.provenance_by_card.get(card.id, {})
            hits.append(
                RetrievalHit(
                    card_id=card.id,
                    damdang=card.damdang,
                    headline=card.headline or card.post_title,
                    post_id=card.post_id,
                    post_title=card.post_title,
                    posted_date=card.posted_date.isoformat(),
                    attachment_name=card.attachment_name,
                    source_ref=card.source_ref,
                    product_codes=list(card.product_codes),
                    score=0.0,
                    temporal=card.temporal.to_dict(),
                    body_excerpt=(card.body or "")[:1500],
                    tables_summary=_tables_summary(card),
                    provenance=prov,
                    post_url=f"/post/{card.post_id}",
                ),
            )
    return hits


def _filter_product(pool: list[WikiCard], product_codes: list[str]) -> list[WikiCard]:
    want = {p.upper() for p in product_codes}
    return [c for c in pool if want & {x.upper() for x in c.product_codes}]


def _apply_temporal_relaxed(
    pool: list[WikiCard],
    scope: TemporalScope,
    diag: dict,
) -> list[WikiCard]:
    """Apply temporal filter, relaxing when it would empty a non-empty pool.

    active_on that empties the pool falls back to observable_on; if any mode
    still empties the pool, the filter is dropped. Relaxations are recorded
    in diag so retrieval traces show where filtering failed.
    """
    if not pool:
        return pool
    filtered = _apply_temporal(pool, scope)
    if filtered:
        diag["pool_after_temporal"] = len(filtered)
        return filtered

    if scope.time_mode == TimeMode.active_on and scope.query_date:
        relaxed_scope = scope.model_copy(update={"time_mode": TimeMode.observable_on})
        filtered = _apply_temporal(pool, relaxed_scope)
        if filtered:
            diag["temporal_relaxed"] = "active_on->observable_on"
            diag["pool_after_temporal"] = len(filtered)
            return filtered

    diag["temporal_relaxed"] = f"{scope.time_mode.value}->none"
    diag["pool_after_temporal"] = len(pool)
    return pool


def retrieve_wiki_cards(
    corpus: QACorpus,
    *,
    keywords: list[str],
    damdangs: list[str],
    product_codes: list[str] | None = None,
    notice_kinds: list[str] | None = None,
    temporal_scope: TemporalScope | None = None,
    limit: int = 8,
    relax_notice_kinds: bool = True,
    anchor_post_id: str | None = None,
    anchor_source_ref: str | None = None,
    query_date: date | None = None,
    diagnostics_out: dict | None = None,
) -> list[RetrievalHit]:
    diag: dict = diagnostics_out if diagnostics_out is not None else {}
    product_codes = product_codes or []
    if anchor_post_id:
        anchor_d = {
            c.damdang for c in corpus.cards if c.post_id == anchor_post_id
        }
        damdangs = list(dict.fromkeys([*damdangs, *anchor_d]))

    damdang_boost = set(damdangs)
    pool = list(corpus.cards)
    diag["pool_total"] = len(pool)

    if notice_kinds:
        filtered = filter_by_notice_kind(pool, *notice_kinds)
        if filtered or not relax_notice_kinds:
            pool = filtered
        else:
            diag["notice_filter_relaxed"] = True
        diag["pool_after_notice"] = len(pool)

    # Guard: a hallucinated/wrong product code must never zero out retrieval.
    # If the filter empties the pool, keep the unfiltered pool and rely on
    # the +5.0 product-match scoring boost instead.
    pool_product_filtered = False
    if product_codes:
        filtered = _filter_product(pool, product_codes)
        if filtered:
            pool = filtered
            pool_product_filtered = True
        else:
            diag["product_filter_relaxed"] = True
        diag["pool_after_product"] = len(pool)

    if temporal_scope:
        pool = _apply_temporal_relaxed(pool, temporal_scope, diag)

    qd = query_date
    if qd is None and temporal_scope and temporal_scope.query_date:
        qd = temporal_scope.query_date

    cards_by_id = {c.id: c for c in corpus.cards}
    skip_dedup = (
        temporal_scope is not None
        and temporal_scope.time_mode == TimeMode.version_diff
    )

    hits = _hits_from_pool(
        pool, corpus,
        keywords=keywords, product_codes=product_codes, limit=limit,
        anchor_post_id=anchor_post_id, anchor_source_ref=anchor_source_ref,
        damdang_boost=damdang_boost, query_date=qd,
        pool_product_filtered=pool_product_filtered,
    )

    if not skip_dedup:
        hits = _dedup_by_topic_key(hits, cards_by_id)

    if notice_kinds and relax_notice_kinds and not hits:
        diag["notice_filter_relaxed"] = True
        pool2 = list(corpus.cards)
        pool2_product_filtered = False
        if product_codes:
            filtered = _filter_product(pool2, product_codes)
            if filtered:
                pool2 = filtered
                pool2_product_filtered = True
            else:
                diag["product_filter_relaxed"] = True
        if temporal_scope:
            pool2 = _apply_temporal_relaxed(pool2, temporal_scope, diag)
        hits = _hits_from_pool(
            pool2, corpus,
            keywords=keywords, product_codes=product_codes, limit=limit,
            anchor_post_id=anchor_post_id, anchor_source_ref=anchor_source_ref,
            damdang_boost=damdang_boost, query_date=qd,
            pool_product_filtered=pool2_product_filtered,
        )
        if not skip_dedup:
            hits = _dedup_by_topic_key(hits, cards_by_id)

    if anchor_post_id and (not hits or top_hit_score(hits) < 5):
        anchored = [c for c in corpus.cards if c.post_id == anchor_post_id]
        if anchored:
            diag["anchor_fallback"] = True
            hits = _hits_from_pool(
                anchored, corpus,
                keywords=keywords, product_codes=product_codes, limit=limit,
                anchor_post_id=anchor_post_id, anchor_source_ref=anchor_source_ref,
                damdang_boost=damdang_boost, query_date=qd,
                pool_product_filtered=True,
            )

    diag["hit_count"] = len(hits)
    diag["top_score"] = top_hit_score(hits)
    return hits


def top_hit_score(hits: list[RetrievalHit]) -> float:
    return hits[0].score if hits else 0.0


def _top_hit_keyword_coverage(hits: list[RetrievalHit], keywords: list[str]) -> int:
    """Count query keywords (or josa-stripped variants) present in top hit text."""
    if not hits:
        return 0
    top = hits[0]
    text_l = f"{top.post_title} {top.headline} {top.body_excerpt}".lower()
    count = 0
    for kw in _keyword_set(keywords):
        variants = [v.lower() for v in keyword_variants(kw)]
        if any(v in text_l for v in variants):
            count += 1
    return count


def is_weak_retrieval(
    hits: list[RetrievalHit],
    keywords: list[str] | None = None,
) -> bool:
    if not hits:
        return True
    # Corpus-size-invariant signal: top hit shares no keyword with the query.
    if keywords and _top_hit_keyword_coverage(hits, keywords) == 0:
        return True
    top = top_hit_score(hits)
    if top >= 8.0:
        return False
    return len(hits) < 2 or top < _MIN_GOOD_SCORE
