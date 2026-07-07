"""Tests for Q&A orchestrator (mock LLM, no API key)."""
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
from store_brief.llmwiki.from_posts import infer_damdangs_from_text
from store_brief.qa.tools.intent import normalize_intent_dict
from store_brief.qa.tools.retrieve import is_weak_retrieval, retrieve_wiki_cards
from store_brief.qa.tools.routing import resolve_damdang_scope
from store_brief.qa.tools.temporal import resolve_temporal_scope
from store_brief.temporal.meta import NoticeKind, extract_temporal_meta


class MockLLM:
  def __init__(self, intent: QuestionIntent | None = None, answer: str = "테스트 답변"):
    self.intent = intent or QuestionIntent(
      keywords=["판촉", "냉장고"],
      damdang_hints=["대형가전1"],
      time_mode=TimeMode.active_on,
      query_date=date(2026, 6, 10),
      notice_kinds=["판촉"],
    )
    self.answer = answer

  def complete_structured(self, prompt, *, system=None, json_schema=None, schema_name=None):
    return self.intent.model_dump(mode="json")

  def complete(self, prompt, system=None):
    return self.answer

  def complete_json(self, prompt, system=None):
    return ["판촉", "냉장고", "6월"]


def _card(post_id, damdang, body, posted, promo_range=None):
  tm = extract_temporal_meta(
    text=body or (promo_range or ""),
    posted_date=posted,
    damdang=damdang,
  )
  if promo_range and not tm.valid_from:
    vf, vt = None, None
    from store_brief.temporal.parse import parse_validity_range
    vf, vt = parse_validity_range(promo_range, year=posted.year)
    tm.valid_from, tm.valid_to = vf, vt
    tm.notice_kind = NoticeKind.promotion
  return WikiCard(
    damdang=damdang,
    post_id=post_id,
    post_title=f"공지 {post_id}",
    posted_date=posted,
    source_ref=f"{post_id}#s1",
    attachment_name="promo.xlsx",
    product_codes=["X324GB5.AKOR"],
    headline="냉장고 판촉",
    body=body or promo_range or "",
    temporal=tm,
  )


@pytest.fixture
def mini_corpus():
  cards = [
    _card("a", "대형가전1", "LG 냉장고 판촉", date(2026, 6, 5), "6/5~8"),
    _card("b", "대형가전1", "old promo", date(2026, 5, 1), "5/1~5/10"),
    _card("c", "IT", "노트북", date(2026, 6, 12)),
  ]
  return QACorpus(as_of="2026-06-17", cards=cards, provenance_by_card={})


def test_resolve_damdang_scope_alias():
  roster = ["대형가전1", "대형가전2", "IT", "생활리빙", "지원"]
  assert resolve_damdang_scope(damdang_hints=["대형가전"], roster=roster, confidence="high", question="대형가전 판촉") == [
    "대형가전1", "대형가전2",
  ]


def test_retrieve_active_on_mid_june(mini_corpus):
  intent = QuestionIntent(
    keywords=["냉장고", "판촉"],
    time_mode=TimeMode.active_on,
    query_date=date(2026, 6, 7),
    notice_kinds=["판촉"],
  )
  scope = resolve_temporal_scope(intent, default_query_date=date(2026, 6, 17))
  hits = retrieve_wiki_cards(
    mini_corpus,
    keywords=intent.keywords,
    damdangs=["대형가전1"],
    notice_kinds=["판촉"],
    temporal_scope=scope,
  )
  assert len(hits) >= 1
  assert hits[0].post_id == "a"


def test_orchestrator_mock_llm(mini_corpus, tmp_path, monkeypatch):
  data_dir = tmp_path / "data"
  llmwiki = data_dir / "llmwiki" / "2026-06-17"
  llmwiki.mkdir(parents=True)
  llmwiki.joinpath("llmwiki.json").write_text(
    json.dumps({"as_of": "2026-06-17", "damdang": {}}),
    encoding="utf-8",
  )
  (data_dir / "rnr.txt").write_text("", encoding="utf-8")

  orch = QAOrchestrator(
    llm=MockLLM(),
    data_dir=str(data_dir),
    as_of="2026-06-17",
    rnr_path=str(data_dir / "rnr.txt"),
  )
  orch._corpus = mini_corpus
  orch._roster = ["대형가전1", "대형가전2", "IT"]

  resp = orch.ask(QAAskRequest(question="6월 중순 대형가전 판촉"))
  assert resp.answer
  assert any(t.tool == "parse_question_intent" for t in resp.traces)
  assert any(t.tool == "compose_answer" for t in resp.traces)


def test_openai_key_missing():
  import os
  from store_brief.llm.client import LLMClient

  old = os.environ.pop("OPENAI_API_KEY", None)
  try:
    with pytest.raises(RuntimeError, match="OPENAI_API_KEY"):
      LLMClient.openai()
  finally:
    if old:
      os.environ["OPENAI_API_KEY"] = old


_FAN_BODY = """\
[SCM서비스혁신팀] 선풍기 조립 서비스 안내
1. 시행일자 : 26년 6월 17일 부(설치기준)
2. 안내사항
1) 조립서비스만 구매 시 : 부가서비스코드만 판매접수 등록
2) 배송 + 조립 필요 시 : 상품코드 + 부가서비스 코드 판매접수 등록
3. 조립서비스 코드
- 일반형 : INS-FAN(STAND)
- 벽걸이 : INS-FAN(WALL)
4. 유의사항
- 상품수량과 부가서비스코드 수량 동일하게 판매접수 등록
- 벽걸이 선풍기 조립의 경우 층고 3m 이하만 가능
"""


def _fan_card():
  tm = extract_temporal_meta(
    text=_FAN_BODY,
    posted_date=date(2026, 6, 16),
    title="[SCM서비스혁신팀] 선풍기 조립 서비스 안내",
    damdang="케어서비스",
  )
  return WikiCard(
    damdang="케어서비스",
    post_id="bfbfb62fe0da",
    post_title="[SCM서비스혁신팀] 선풍기 조립 서비스 안내",
    posted_date=date(2026, 6, 16),
    source_ref="bfbfb62fe0da#body",
    attachment_name="(게시글 본문)",
    product_codes=["INS-FAN(STAND)", "INS-FAN(WALL)"],
    headline="[SCM서비스혁신팀] 선풍기 조립 서비스 안내",
    body=_FAN_BODY,
    temporal=tm,
  )


@pytest.fixture
def service_corpus(mini_corpus):
  pc = _card("pc", "IT", "조립PC 오피스 패키지 코드 집중 판매", date(2026, 6, 1))
  return QACorpus(
    as_of="2026-06-17",
    cards=mini_corpus.cards + [_fan_card(), pc],
    provenance_by_card={},
  )


def test_infer_damdang_fan_service():
  roster = {"케어서비스", "생활주방", "생활리빙", "IT"}
  d = infer_damdangs_from_text("선풍기 조립 서비스 SCM", roster)
  assert "케어서비스" in d
  assert "생활주방" in d or "생활리빙" in d


def test_intent_service_question():
  intent = normalize_intent_dict({}, question="선풍기 조립 서비스에 대해 알려줘")
  assert "케어서비스" in intent["damdang_hints"]
  assert "정책" in intent["notice_kinds"] or "공지" in intent["notice_kinds"]


def test_retrieve_fan_assembly_over_pc(service_corpus):
  hits = retrieve_wiki_cards(
    service_corpus,
    keywords=["선풍기", "조립", "서비스"],
    damdangs=["케어서비스", "생활주방", "생활리빙", "IT"],
    notice_kinds=["정책"],
    temporal_scope=None,
  )
  assert hits
  assert hits[0].post_id == "bfbfb62fe0da"
  assert not is_weak_retrieval(hits)


def test_service_code_extract():
  from store_brief.hisis.prd_codes import extract_prd_codes

  codes = extract_prd_codes("일반형 : INS-FAN(STAND), 벽걸이 : INS-FAN(WALL)")
  assert "INS-FAN(STAND)" in codes
  assert "INS-FAN(WALL)" in codes


def test_intent_oclean_routes_living():
  intent = normalize_intent_dict({}, question="오클린 전동칫솔 V8100 추가 행사가 알려줘")
  assert "생활리빙" in intent["damdang_hints"]


def test_retrieve_oclean_promo_sheet():
  from pathlib import Path

  from store_brief.qa.corpus import load_corpus

  data = Path(__file__).resolve().parents[1] / "data"
  if not (data / "llmwiki" / "2026-06-17" / "llmwiki.json").is_file():
    pytest.skip("llmwiki corpus not built")
  corpus = load_corpus(data, "2026-06-17")
  hits = retrieve_wiki_cards(
    corpus,
    keywords=["오클린", "전동칫솔", "V8100", "추가행사가"],
    damdangs=["생활리빙"],
  )
  assert hits
  assert hits[0].post_id == "9c9f6727c664"
  assert "오클린" in hits[0].attachment_name or "V8100" in hits[0].body
  assert not is_weak_retrieval(hits)


def test_anchor_boosts_sample_post():
  from pathlib import Path

  from store_brief.qa.corpus import load_corpus

  data = Path(__file__).resolve().parents[1] / "data"
  if not (data / "llmwiki" / "2026-06-17" / "llmwiki.json").is_file():
    pytest.skip("llmwiki corpus not built")
  corpus = load_corpus(data, "2026-06-17")
  hits = retrieve_wiki_cards(
    corpus,
    keywords=["오클린", "행사"],
    damdangs=["대형가전1"],
    anchor_post_id="9c9f6727c664",
  )
  assert hits[0].post_id == "9c9f6727c664"
  assert hits[0].score >= 20


def test_retrieve_notebook_inventory_sheet_over_lineup_pptx():
  from pathlib import Path

  from store_brief.qa.corpus import load_corpus

  data = Path(__file__).resolve().parents[1] / "data"
  if not (data / "llmwiki" / "2026-06-17" / "llmwiki.json").is_file():
    pytest.skip("llmwiki corpus not built")
  corpus = load_corpus(data, "2026-06-17")
  hits = retrieve_wiki_cards(
    corpus,
    keywords=["노트북", "진열소진현황", "재고확인"],
    damdangs=["PC솔루션"],
    notice_kinds=None,
    limit=8,
  )
  assert hits
  assert "진열소진현황" in hits[0].attachment_name
  assert "지사지점재고확인" in hits[0].body_excerpt
  assert hits[0].damdang == "PC솔루션"
  assert not is_weak_retrieval(hits)
