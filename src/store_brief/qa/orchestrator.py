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

        t0 = time.perf_counter()
        hits = retrieve_wiki_cards(
            self.corpus,
            keywords=keywords,
            damdangs=damdangs,
            product_codes=intent.product_codes,
            notice_kinds=intent.notice_kinds or None,
            temporal_scope=temporal_scope,
            anchor_post_id=req.anchor_post_id,
            anchor_source_ref=req.anchor_source_ref,
            query_date=default_qd,
        )
        traces.append(
            self._trace(
                "retrieve_wiki_cards",
                {"keywords": keywords, "damdangs": damdangs, "limit": 8},
                {"count": len(hits), "card_ids": [h.card_id for h in hits]},
                t0,
            ),
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
                t0 = time.perf_counter()
                hits = retrieve_wiki_cards(
                    self.corpus,
                    keywords=keywords,
                    damdangs=list(self.roster),
                    product_codes=intent.product_codes,
                    notice_kinds=intent.notice_kinds or None,
                    temporal_scope=temporal_scope,
                    anchor_post_id=req.anchor_post_id,
                    anchor_source_ref=req.anchor_source_ref,
                    query_date=default_qd,
                )
                damdangs = list(self.roster)
                traces.append(
                    self._trace(
                        "retrieve_wiki_cards",
                        {"keywords": keywords, "damdangs": "all", "early_broaden": True},
                        {"count": len(hits)},
                        t0,
                    ),
                )

        refined = False
        if is_weak_retrieval(hits) and not refined:
            t0 = time.perf_counter()
            refine_prompt = f"""질문: {req.question}
현재 키워드: {keywords}
검색 결과가 부족합니다. 추가 검색 키워드 3개를 JSON 배열로만 반환하세요. 예: ["냉장고","판촉","6월"]"""
            try:
                extra = self.llm.complete_json(refine_prompt)
                if isinstance(extra, list):
                    keywords.extend(str(x) for x in extra if x)
                elif isinstance(extra, dict) and "keywords" in extra:
                    keywords.extend(str(x) for x in extra["keywords"] if x)
            except Exception:
                pass
            traces.append(
                self._trace(
                    "refine_retrieval_query",
                    {"question": req.question},
                    {"keywords": keywords},
                    t0,
                ),
            )
            t0 = time.perf_counter()
            hits = retrieve_wiki_cards(
                self.corpus,
                keywords=keywords,
                damdangs=damdangs,
                product_codes=intent.product_codes,
                notice_kinds=intent.notice_kinds or None,
                temporal_scope=temporal_scope,
                anchor_post_id=req.anchor_post_id,
                anchor_source_ref=req.anchor_source_ref,
                query_date=default_qd,
            )
            traces.append(
                self._trace(
                    "retrieve_wiki_cards",
                    {"keywords": keywords, "refined": True},
                    {"count": len(hits)},
                    t0,
                ),
            )
            refined = True

        if is_weak_retrieval(hits):
            t0 = time.perf_counter()
            broad_damdangs = list(self.roster)
            hits = retrieve_wiki_cards(
                self.corpus,
                keywords=keywords,
                damdangs=broad_damdangs,
                product_codes=intent.product_codes,
                notice_kinds=None,
                temporal_scope=temporal_scope,
                anchor_post_id=req.anchor_post_id,
                anchor_source_ref=req.anchor_source_ref,
                query_date=default_qd,
            )
            traces.append(
                self._trace(
                    "retrieve_wiki_cards",
                    {"keywords": keywords, "damdangs": "all", "broadened": True},
                    {"count": len(hits)},
                    t0,
                ),
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
