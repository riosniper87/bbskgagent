"""Generate sample Q&A questions from llmwiki-indexed content only."""
from __future__ import annotations

import random
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from store_brief.llm.client import LLMClient
from store_brief.llmwiki.card import WikiCard
from store_brief.qa.corpus import QACorpus, load_corpus
from store_brief.viewer.loader import PostDetail

_MIN_EXCERPT = 80
_MAX_EXCERPT = 900
_BOILERPLATE = ("프롬프트", "【")

_SYSTEM = """당신은 하이마트 매장 현장 판매 사원이 공지/판촉 내용을 확인하기 위해 질문하는 문장을 만듭니다.

규칙:
- 제공된 발췌 내용만으로 답할 수 있는 질문 1개만 작성하세요.
- 말투는 현장 점포 판매 사원(실제 매장에서 동료나 시스템에 묻는 톤)으로 자연스럽게 하세요.
- 질문은 한국어 1~2문장, 15~80자 내외로 간결하게 하세요.
- 발췌에 없는 브랜드·날짜·상품코드를 새로 만들지 마세요.
- 행사기간, 판촉, 설치, 모델코드, 시행일, 유의사항 등 발췌에 있는 핵심을 묻도록 하세요.
- JSON이 아니라 질문 문장만 출력하세요."""


@dataclass
class ContentSnippet:
    post_id: str
    post_title: str
    posted_date: str
    source_type: str
    source_label: str
    source_ref: str
    text: str
    damdang: str = ""

    @property
    def excerpt_preview(self) -> str:
        t = re.sub(r"\s+", " ", self.text).strip()
        if len(t) <= 160:
            return t
        return t[:160] + "…"


def _usable(text: str) -> bool:
    t = (text or "").strip()
    if len(t) < _MIN_EXCERPT:
        return False
    return not any(b in t for b in _BOILERPLATE)


def _trim(text: str) -> str:
    t = (text or "").strip()
    if len(t) <= _MAX_EXCERPT:
        return t
    return t[:_MAX_EXCERPT] + "\n…(생략)"


def _infer_source_type(card: WikiCard) -> str:
    ref = card.source_ref or ""
    if ref.endswith("#body"):
        return "body"
    if card.vlm:
        return "vlm"
    if re.search(r"#s\d+$", ref, re.I):
        return "slide"
    if ".xlsx" in ref.lower() or card.tables:
        return "sheet"
    return "wiki_card"


def _source_label(card: WikiCard) -> str:
    name = (card.attachment_name or "").strip()
    if name in ("", "(게시글 본문)"):
        base = "게시글 본문"
    else:
        base = f"첨부: {name}"
    if card.headline and card.headline not in base:
        return f"{base} · {card.headline}"
    return base


def card_to_snippet(card: WikiCard) -> ContentSnippet | None:
    body = (card.body or "").strip()
    if card.vlm and card.vlm.description:
        body = body or card.vlm.description
    if not _usable(body):
        return None
    return ContentSnippet(
        post_id=card.post_id,
        post_title=card.post_title,
        posted_date=card.posted_date.isoformat(),
        source_type=_infer_source_type(card),
        source_label=_source_label(card),
        source_ref=card.source_ref,
        text=_trim(body),
        damdang=card.damdang,
    )


def collect_card_snippets(cards: list[WikiCard]) -> list[ContentSnippet]:
    out: list[ContentSnippet] = []
    for card in cards:
        snip = card_to_snippet(card)
        if snip:
            out.append(snip)
    return out


def _parse_posted(d: str | date) -> date | None:
    if isinstance(d, date):
        return d
    try:
        return date.fromisoformat(str(d)[:10])
    except ValueError:
        return None


def sample_snippet_from_corpus(
    corpus: QACorpus,
    *,
    as_of: str | None = None,
    rng: random.Random | None = None,
) -> ContentSnippet:
    """Pick a random llmwiki card excerpt (QA-retrievable content only)."""
    rng = rng or random.Random()
    cutoff = date.fromisoformat(as_of) if as_of else None

    cards = corpus.cards
    if cutoff:
        cards = [
            c for c in cards
            if (pd := _parse_posted(c.posted_date)) is None or pd <= cutoff
        ]

    snippets = collect_card_snippets(cards)
    if not snippets:
        raise ValueError("llmwiki에 샘플 질문으로 쓸 수 있는 카드가 없습니다.")

    return rng.choice(snippets)


# --- legacy helpers (parsed viewer); kept for unit tests ---

def _table_to_text(tbl: dict, *, max_rows: int = 8) -> str:
    cols = tbl.get("columns") or []
    rows = tbl.get("rows") or []
    lines: list[str] = []
    if cols:
        lines.append(" | ".join(str(c) for c in cols))
    for row in rows[:max_rows]:
        lines.append(" | ".join(str(c) for c in row))
    return "\n".join(lines)


def collect_snippets(post: PostDetail) -> list[ContentSnippet]:
    out: list[ContentSnippet] = []
    base = dict(
        post_id=post.post_id,
        post_title=post.title,
        posted_date=post.posted_date,
    )

    if _usable(post.body):
        out.append(ContentSnippet(
            **base,
            source_type="body",
            source_label="게시글 본문",
            source_ref=f"{post.post_id}#body",
            text=_trim(post.body),
        ))

    for att in post.attachments:
        if att.error:
            continue
        att_id = att.attachment_id or att.att_key
        if _usable(att.text):
            out.append(ContentSnippet(
                **base,
                source_type="attachment_text",
                source_label=f"첨부: {att.filename}",
                source_ref=att_id,
                text=_trim(att.text),
            ))
        for page in att.pages:
            if _usable(page.text):
                out.append(ContentSnippet(
                    **base,
                    source_type="slide",
                    source_label=f"{att.filename} · 슬라이드/페이지 {page.index}",
                    source_ref=page.ref or f"{att_id}#s{page.index}",
                    text=_trim(page.text),
                ))
            if page.vlm and _usable(page.vlm.description):
                out.append(ContentSnippet(
                    **base,
                    source_type="vlm",
                    source_label=f"{att.filename} · 이미지 설명 p{page.index}",
                    source_ref=page.vlm.source_ref or page.ref or f"{att_id}#img{page.index}",
                    text=_trim(page.vlm.description),
                ))
        for sheet in att.sheets:
            parts: list[str] = []
            for tbl in sheet.tables:
                blob = _table_to_text(tbl)
                if blob:
                    parts.append(blob)
            if sheet.raw_rows:
                parts.append("\n".join(
                    " | ".join(str(c) for c in row) for row in sheet.raw_rows[:12]
                ))
            blob = "\n".join(parts).strip()
            if _usable(blob):
                sheet_ref = f"{att_id}#sheet:{sheet.sheet}"
                if sheet.tables:
                    first_tbl = sheet.tables[0]
                    tbl_ref = first_tbl.get("source_ref") if isinstance(first_tbl, dict) else None
                    if tbl_ref:
                        sheet_ref = str(tbl_ref)
                out.append(ContentSnippet(
                    **base,
                    source_type="sheet",
                    source_label=f"{att.filename} · 시트 {sheet.sheet}",
                    source_ref=sheet_ref,
                    text=_trim(blob),
                ))
    return out


def generate_question_from_snippet(
    llm: LLMClient,
    snippet: ContentSnippet,
) -> str:
    prompt = f"""게시물 제목: {snippet.post_title}
작성일: {snippet.posted_date}
발췌 출처: {snippet.source_label}

발췌 내용:
{snippet.text}

위 발췌만 보고 현장 판매 사원이 할 법한 질문 1개를 작성하세요."""

    raw = llm.complete(prompt, system=_SYSTEM).strip()
    raw = re.sub(r"^[\d]+[\.\)]\s*", "", raw)
    raw = raw.strip("\"'“”‘’")
    if not raw:
        raise ValueError("질문 생성에 실패했습니다.")
    return raw


def suggest_question(
    llm: LLMClient,
    *,
    data_dir: str | Path,
    as_of: str,
    seed: int | None = None,
    corpus: QACorpus | None = None,
) -> tuple[str, ContentSnippet, int | None]:
    use_seed = seed
    rng = random.Random(seed) if seed is not None else random.Random()
    if use_seed is None:
        use_seed = rng.randint(0, 2**31 - 1)
        rng = random.Random(use_seed)

    qa_corpus = corpus or load_corpus(data_dir, as_of)
    snippet = sample_snippet_from_corpus(qa_corpus, as_of=as_of, rng=rng)
    question = generate_question_from_snippet(llm, snippet)
    return question, snippet, use_seed
