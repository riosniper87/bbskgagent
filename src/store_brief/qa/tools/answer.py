"""Compose grounded answer from retrieval hits."""
from __future__ import annotations

from store_brief.llm.client import LLMClient
from store_brief.qa.schemas import Citation, RetrievalHit, TemporalScope
from store_brief.qa.tools.brands import build_brand_context, display_title, infer_card_brands

_SYSTEM = """당신은 매장 운영 공지·판촉 안내 도우미입니다.
제공된 참조 카드만 근거로 한국어로 답변하세요.

## 기본 규칙
- 참조에 없는 내용은 추측하지 마세요.
- 적용기간·게시일·상품코드를 명확히 언급하세요.
- 개정/변경 질문이면 이전과 이후 차이를 요약하세요.
- 참조 목록에는 **게시물 제목(post_title)** 을 사용하세요. 슬라이드 소제목(예: 일반, 벽걸이)만 단독으로 쓰지 마세요.

## 브랜드·메이커 구분 (매우 중요)
매장 공지에는 여러 브랜드가 섞여 있습니다. 질문과 카드의 브랜드를 반드시 구분하세요.

### 브랜드 유형
- **메이커(OEM)**: 삼성, LG, 위니아, 쿠쿠, 하이얼, TCL, 샤프, 다이슨, 드리미, 애플, 마이디어 등
- **자사 PB**: PLUX(플럭스), 상품코드 **PLX-** 접두
- **혼합 공지**: "LG/삼성 세트", "삼성 감사페스티벌" 등 — 질문 브랜드에 해당하는 항목만 발췌

### 답변 시
1. 질문에 특정 브랜드가 있으면 **그 브랜드 판촉·행사·모델만** 답하세요.
2. [브랜드 필터]에서 **✗ 질문 브랜드와 불일치** 로 표시된 카드 내용은 답변 본문에 넣지 마세요.
3. 삼성·LG 등 메이커 질문에 PLUX/PLX- 단독 카드(하이마트 PB)를 메이커 판촉처럼 소개하지 마세요.
4. PLUX·플럭스·PB 질문에는 PLUX/PB 내용만 답하세요.
5. 혼합 공지 카드는 질문 브랜드 관련 문단·모델·행사만 인용하세요.
6. 해당 브랜드 전용 내용이 참조에 없으면 솔직히 알리고, 있는 범위에서만 답하세요.

## 답변 형식
- 본문 답변 후 빈 줄
- **참조한 공지** 제목을 bullet으로 나열 (게시물 제목 기준)"""


def _format_hits(hits: list[RetrievalHit], temporal: TemporalScope | None) -> str:
    parts = []
    if temporal and temporal.description:
        parts.append(f"[시간 필터] {temporal.description} mode={temporal.time_mode.value}")
        if temporal.query_date:
            parts.append(f"query_date={temporal.query_date.isoformat()}")
    for i, h in enumerate(hits, 1):
        brands = infer_card_brands(h)
        block = [
            f"--- 카드 {i} ---",
            f"추정 브랜드: {', '.join(brands)}",
            f"담당: {h.damdang}",
            f"게시물 제목: {h.post_title} ({h.posted_date})",
            f"카드 헤드라인: {h.headline}",
            f"첨부: {h.attachment_name}",
            f"상품코드: {', '.join(h.product_codes[:8])}",
            f"시간메타: {h.temporal}",
            f"본문:\n{h.body_excerpt}",
        ]
        if h.tables_summary:
            block.append(f"표:\n{h.tables_summary}")
        parts.append("\n".join(block))
    return "\n\n".join(parts)


def compose_answer(
    llm: LLMClient,
    *,
    question: str,
    hits: list[RetrievalHit],
    temporal_scope: TemporalScope | None = None,
) -> tuple[str, list[Citation]]:
    if not hits:
        return (
            "참조할 수 있는 공지 카드를 찾지 못했습니다. 담당·기간·키워드를 바꿔 다시 질문해 주세요.",
            [],
        )

    brand_ctx = build_brand_context(question, hits)
    context = _format_hits(hits, temporal_scope)
    brand_block = f"\n\n{brand_ctx.guidance}\n" if brand_ctx.guidance else ""

    prompt = f"""질문: {question}
{brand_block}
참조 카드:
{context}

위 참조만 사용해 답변하세요. 브랜드 필터 규칙을 반드시 지키세요."""

    answer = llm.complete(prompt, system=_SYSTEM)
    citations = [
        Citation(
            card_id=h.card_id,
            headline=display_title(h),
            post_title=h.post_title,
            attachment_name=h.attachment_name,
        )
        for h in hits[:5]
    ]
    return answer, citations
