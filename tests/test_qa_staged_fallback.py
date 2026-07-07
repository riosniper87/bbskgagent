"""Tests for the orchestrator's staged retrieval fallback (LLM last)."""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.llmwiki.card import WikiCard
from store_brief.qa.corpus import QACorpus
from store_brief.qa.orchestrator import QAOrchestrator
from store_brief.qa.schemas import QAAskRequest, QuestionIntent, TimeMode
from store_brief.temporal.meta import TemporalMeta


class FailingRefineLLM:
    """LLM whose intent parse works but keyword-refine call fails (offline vLLM).

    parse_question_intent calls complete_json WITH a system prompt; the
    keyword-refine call passes no system prompt — that distinguishes them.
    """

    def __init__(self, intent: QuestionIntent):
        self.intent = intent
        self.refine_calls = 0

    def complete_structured(self, prompt, *, system=None, json_schema=None, schema_name=None):
        return self.intent.model_dump(mode="json")

    def complete(self, prompt, system=None):
        return "테스트 답변"

    def complete_json(self, prompt, system=None):
        if system is not None:  # intent parse
            return self.intent.model_dump(mode="json")
        self.refine_calls += 1
        return self._refine()

    def _refine(self):
        raise RuntimeError("LLM unavailable")


class RefiningLLM(FailingRefineLLM):
    def _refine(self):
        return ["냉장고"]


def _card(post_id, damdang, body, posted, headline):
    return WikiCard(
        damdang=damdang,
        post_id=post_id,
        post_title=f"공지 {post_id}",
        posted_date=posted,
        source_ref=f"{post_id}#s1",
        attachment_name="promo.xlsx",
        headline=headline,
        body=body,
        temporal=TemporalMeta(),
    )


@pytest.fixture
def corpus():
    return QACorpus(
        as_of="2026-06-17",
        cards=[
            _card("a", "대형가전1", "LG 냉장고 판촉 행사", date(2026, 6, 5), "냉장고 판촉"),
            _card("b", "IT", "노트북 안내", date(2026, 6, 10), "노트북"),
        ],
        provenance_by_card={},
    )


def _orch(llm, corpus, tmp_path):
    data_dir = tmp_path / "data"
    llmwiki = data_dir / "llmwiki" / "2026-06-17"
    llmwiki.mkdir(parents=True)
    llmwiki.joinpath("llmwiki.json").write_text(
        json.dumps({"as_of": "2026-06-17", "damdang": {}}), encoding="utf-8",
    )
    (data_dir / "rnr.txt").write_text("", encoding="utf-8")
    orch = QAOrchestrator(
        llm=llm,
        data_dir=str(data_dir),
        as_of="2026-06-17",
        rnr_path=str(data_dir / "rnr.txt"),
    )
    orch._corpus = corpus
    orch._roster = ["대형가전1", "IT", "생활리빙"]
    return orch


def _stages(resp):
    return [
        t.input.get("stage")
        for t in resp.traces
        if t.tool == "retrieve_wiki_cards"
    ]


def test_deterministic_stages_before_llm(corpus, tmp_path):
    # Keywords match nothing → every deterministic stage runs, then LLM refine.
    intent = QuestionIntent(
        keywords=["존재하지않는키워드"],
        damdang_hints=["대형가전1"],
        notice_kinds=["판촉"],
        time_mode=TimeMode.none,
    )
    llm = FailingRefineLLM(intent)
    resp = _orch(llm, corpus, tmp_path).ask(
        QAAskRequest(question="존재하지않는키워드?", damdang="대형가전1"),
    )

    stages = _stages(resp)
    assert stages[0] == "initial"
    assert "broaden_damdang" in stages
    assert "drop_notice_kinds" in stages
    # LLM refine ran last and its failure was recorded, not raised.
    refine = [t for t in resp.traces if t.tool == "refine_retrieval_query"]
    assert len(refine) == 1
    assert refine[0].output["llm_ok"] is False
    assert "llm_refine" not in stages  # no extra keywords → no extra retrieval
    assert resp.answer  # pipeline still completes


def test_llm_refine_runs_last_and_uses_keywords(corpus, tmp_path):
    intent = QuestionIntent(
        keywords=["존재하지않는키워드"],
        damdang_hints=["대형가전1"],
        time_mode=TimeMode.none,
    )
    llm = RefiningLLM(intent)
    resp = _orch(llm, corpus, tmp_path).ask(
        QAAskRequest(question="냉장고?", damdang="대형가전1"),
    )

    stages = _stages(resp)
    assert stages[-1] == "llm_refine"
    assert stages.index("llm_refine") > stages.index("broaden_damdang")
    # Refined keyword found the card.
    hit_ids = [h.post_id for h in resp.hits]
    assert "a" in hit_ids


def test_good_initial_retrieval_skips_fallbacks(corpus, tmp_path):
    intent = QuestionIntent(
        keywords=["냉장고", "판촉"],
        damdang_hints=["대형가전1"],
        time_mode=TimeMode.none,
    )
    llm = FailingRefineLLM(intent)
    resp = _orch(llm, corpus, tmp_path).ask(QAAskRequest(question="냉장고 판촉?"))

    stages = _stages(resp)
    assert "drop_notice_kinds" not in stages
    assert "llm_refine" not in stages
    assert llm.refine_calls == 0
    assert resp.hits and resp.hits[0].post_id == "a"


def test_retrieve_traces_include_diagnostics(corpus, tmp_path):
    intent = QuestionIntent(
        keywords=["냉장고"],
        damdang_hints=["대형가전1"],
        time_mode=TimeMode.none,
    )
    llm = FailingRefineLLM(intent)
    resp = _orch(llm, corpus, tmp_path).ask(QAAskRequest(question="냉장고?"))
    rt = [t for t in resp.traces if t.tool == "retrieve_wiki_cards"]
    assert rt
    diag = rt[0].output.get("diagnostics")
    assert diag is not None
    assert diag["pool_total"] == 2
