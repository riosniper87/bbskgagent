"""LLM-as-judge for answer adequacy."""
from __future__ import annotations

from store_brief.llm.client import LLMClient
from store_brief.qa.eval.schema import EvalCase, JudgeVerdict
from store_brief.qa.schemas import QAResponse

_SYSTEM = """당신은 Q&A 품질 평가자입니다.
발췌(excerpt)만으로 질문에 답할 수 있는지, 실제 답변이 발췌에 근거하는지 평가하세요.

JSON만 반환:
{
  "verdict": "pass" | "partial" | "fail",
  "inferred_ratio": 0.0~1.0,
  "reason": "한국어 1~2문장"
}

기준:
- pass: 발췌 내용으로 질문에 충분히 답함, 환각 없음
- partial: 일부만 답하거나 불확실한 추론 포함
- fail: "자료에 없음"인데 발췌에 있음, 또는 명백한 환각/무관 답변"""


def judge_answer(
    llm: LLMClient,
    case: EvalCase,
    response: QAResponse,
) -> tuple[JudgeVerdict, float, str]:
    hits_blob = ""
    for h in response.hits[:3]:
        hits_blob += f"\n- [{h.damdang}] {h.headline} ({h.attachment_name})\n  {h.body_excerpt[:200]}"

    prompt = f"""질문: {case.question}

정답 근거 발췌:
{case.excerpt_full}

실제 답변:
{response.answer}

검색된 카드 요약:{hits_blob or " (없음)"}

발췌만 기준으로 답변 적절성을 평가하세요."""

    try:
        raw = llm.complete_json(prompt, system=_SYSTEM)
        if isinstance(raw, dict):
            verdict = str(raw.get("verdict", "fail")).lower()
            if verdict not in ("pass", "partial", "fail"):
                verdict = "fail"
            ratio = float(raw.get("inferred_ratio", 0.0))
            ratio = max(0.0, min(1.0, ratio))
            reason = str(raw.get("reason", ""))
            return verdict, ratio, reason  # type: ignore[return-value]
    except Exception as exc:
        return "skipped", 0.0, f"judge error: {exc}"

    return "skipped", 0.0, "judge returned invalid response"
