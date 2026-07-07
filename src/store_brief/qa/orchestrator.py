"""Q&A orchestrator — MCP-style tool pipeline."""
from __future__ import annotations

import time
from datetime import date

from store_brief.llm.client import LLMClient
from store_brief.llmwiki.grouping import load_qa_damdang_roster
from store_brief.qa.corpus import QACorpus, load_corpus
from store_brief.qa.schemas import QAAskRequest, QAResponse, ToolTrace
from store_brief.qa.tools.answer import compose_answer
from store_brief.qa.tools.attachments import list_attachments
from store_brief.qa.tools.intent import parse_question_intent
from store_brief.qa.tools.retrieve import (
    is_weak_retrieval,
    keyword_overlap_count,
    retrieve_wiki_cards,
)
from store_brief.qa.tools.routing import (
    infer_damdang_confidence,
    pool_was_narrowed,
    resolve_damdang_scope,
)
from store_brief.qa.tools.temporal import resolve_temporal_scope


class QAOrchestrator:
    def __init__(
        self,
        *,
        llm: LLMClient,
        data_dir: str,
        as_of: str,
        rnr_path: str | None = None,
    ):
        self.llm = llm
        self.data_dir = data_dir
        self.as_of = as_of
        self.rnr_path = rnr_path or f"{data_dir}/rnr.txt"
        self._corpus: QACorpus | None = None
        self._roster: list[str] | None = None

    @property
    def corpus(self) -> QACorpus:
        if self._corpus is None:
            self._corpus = load_corpus(self.data_dir, self.as_of)
        return self._corpus

    @property
    def roster(self) -> list[str]:
        if self._roster is None:
            self._roster = load_qa_damdang_roster(self.rnr_path)
        return self._roster

    def _trace(self, tool: str, inp: dict, out: dict, started: float) -> ToolTrace:
        return ToolTrace(
            tool=tool,
            input=inp,
            output=out,
            ms=int((time.perf_counter() - started) * 1000),
        )

    def ask(self, req: QAAskRequest) -> QAResponse:
        traces: list[ToolTrace] = []
        default_qd = req.query_date
        if default_qd is None:
            try:
                default_qd = date.fromisoformat(self.as_of)
            except ValueError:
                default_qd = None

        t0 = time.perf_counter()
        intent = parse_question_intent(
            self.llm,
            question=req.question,
            default_query_date=default_qd,
            damdang_roster=self.roster,
        )
        traces.append(
            self._trace(
                "parse_question_intent",
                {"question": req.question},
                intent.model_dump(mode="json"),
                t0,
            ),
        )

        t0 = time.perf_counter()
        confidence = infer_damdang_confidence(
            question=req.question,
            damdang_hints=intent.damdang_hints,
            product_codes=intent.product_codes,
            roster=self.roster,
            anchor_post_id=req.anchor_post_id,
            damdang_override=req.damdang,
        )
        damdangs = resolve_damdang_scope(
            damdang_hints=intent.damdang_hints,
            roster=self.roster,
            override=req.damdang,
            confidence=confidence,
            question=req.question,
        )
        traces.append(
            self._trace(
                "resolve_damdang_scope",
                {"hints": intent.damdang_hints, "override": req.damdang, "confidence": confidence},
                {"damdangs": damdangs},
                t0,
            ),
        )

        t0 = time.perf_counter()
        temporal_scope = resolve_temporal_scope(intent, default_query_date=default_qd)
        traces.append(
            self._trace(
                "resolve_temporal_scope",
                intent.model_dump(mode="json"),
                temporal_scope.model_dump(mode="json"),
                t0,
            ),
        )

        keywords = list(intent.keywords)
        if intent.refine_query:
            keywords.append(intent.refine_query)

        def _retrieve(
            *,
            stage: str,
            r_keywords: list[str],
            r_damdangs: list[str],
            notice_kinds: list[str] | None,
            trace_extra: dict | None = None,
        ) -> list:
            t0 = time.perf_counter()
            diag: dict = {}
            stage_hits = retrieve_wiki_cards(
                self.corpus,
                keywords=r_keywords,
                damdangs=r_damdangs,
                product_codes=intent.product_codes,
                notice_kinds=notice_kinds,
                temporal_scope=temporal_scope,
                anchor_post_id=req.anchor_post_id,
                anchor_source_ref=req.anchor_source_ref,
                query_date=default_qd,
                diagnostics_out=diag,
            )
            traces.append(
                self._trace(
                    "retrieve_wiki_cards",
                    {
                        "stage": stage,
                        "keywords": r_keywords,
                        "damdangs": r_damdangs if len(r_damdangs) < len(self.roster) else "all",
                        **(trace_extra or {}),
                    },
                    {
                        "count": len(stage_hits),
                        "card_ids": [h.card_id for h in stage_hits],
                        "diagnostics": diag,
                    },
                    t0,
                ),
            )
            return stage_hits

        def _better(new_hits: list, old_hits: list) -> list:
            """Keep the stronger result so a fallback stage never degrades hits.

            Note: scores are compared across stages that use different
            damdang_boost sets (broadened stages boost every roster card),
            so broadened results tend to win. Acceptable because fallback
            stages only run when the current result is already weak, but
            the comparison is not truly apples-to-apples — future tuning
            could normalize out the boost before comparing.
            """
            if not old_hits:
                return new_hits
            if not new_hits:
                return old_hits
            if new_hits[0].score >= old_hits[0].score:
                return new_hits
            return old_hits

        hits = _retrieve(
            stage="initial",
            r_keywords=keywords,
            r_damdangs=damdangs,
            notice_kinds=intent.notice_kinds or None,
        )

        narrowed = pool_was_narrowed(damdangs, self.roster)
        skip_early_broaden = (
            req.damdang
            or confidence == "high"
            or any(
                t in req.question
                for t in ("진열소진", "소진현황", "재고확인", "지사지점재고확인")
            )
        )
        if hits and narrowed and not req.anchor_post_id and not skip_early_broaden:
            top_card = next((c for c in self.corpus.cards if c.id == hits[0].card_id), None)
            if top_card and keyword_overlap_count(top_card, keywords) < 2:
                hits = _retrieve(
                    stage="early_broaden",
                    r_keywords=keywords,
                    r_damdangs=list(self.roster),
                    notice_kinds=intent.notice_kinds or None,
                )
                damdangs = list(self.roster)

        # Staged deterministic fallback: broaden damdang first, then drop the
        # notice-kind filter; only ask the LLM for extra keywords as a last
        # resort (it may be unavailable, and its keywords add noise).
        if is_weak_retrieval(hits, keywords) and pool_was_narrowed(damdangs, self.roster):
            hits = _better(
                _retrieve(
                    stage="broaden_damdang",
                    r_keywords=keywords,
                    r_damdangs=list(self.roster),
                    notice_kinds=intent.notice_kinds or None,
                ),
                hits,
            )

        if is_weak_retrieval(hits, keywords) and intent.notice_kinds:
            hits = _better(
                _retrieve(
                    stage="drop_notice_kinds",
                    r_keywords=keywords,
                    r_damdangs=list(self.roster),
                    notice_kinds=None,
                ),
                hits,
            )

        if is_weak_retrieval(hits, keywords):
            t0 = time.perf_counter()
            refine_prompt = f"""질문: {req.question}
현재 키워드: {keywords}
검색 결과가 부족합니다. 추가 검색 키워드 3개를 JSON 배열로만 반환하세요. 예: ["냉장고","판촉","6월"]"""
            extra_keywords: list[str] = []
            llm_refine_ok = True
            try:
                extra = self.llm.complete_json(refine_prompt)
                if isinstance(extra, list):
                    extra_keywords = [str(x) for x in extra if x]
                elif isinstance(extra, dict) and "keywords" in extra:
                    extra_keywords = [str(x) for x in extra["keywords"] if x]
            except Exception:
                llm_refine_ok = False
            traces.append(
                self._trace(
                    "refine_retrieval_query",
                    {"question": req.question},
                    {"extra_keywords": extra_keywords, "llm_ok": llm_refine_ok},
                    t0,
                ),
            )
            if extra_keywords:
                keywords.extend(extra_keywords)
                hits = _better(
                    _retrieve(
                        stage="llm_refine",
                        r_keywords=keywords,
                        r_damdangs=list(self.roster),
                        notice_kinds=None,
                    ),
                    hits,
                )

        t0 = time.perf_counter()
        attachments = list_attachments(hits)
        traces.append(
            self._trace(
                "list_attachments",
                {"hit_count": len(hits)},
                {"count": len(attachments)},
                t0,
            ),
        )

        t0 = time.perf_counter()
        answer, citations = compose_answer(
            self.llm,
            question=req.question,
            hits=hits,
            temporal_scope=temporal_scope,
        )
        traces.append(
            self._trace(
                "compose_answer",
                {"question": req.question, "hits": len(hits)},
                {"answer_len": len(answer), "citations": len(citations)},
                t0,
            ),
        )

        return QAResponse(
            answer=answer,
            citations=citations,
            attachments=attachments,
            hits=hits,
            damdangs=damdangs,
            temporal_scope=temporal_scope,
            traces=traces,
        )
