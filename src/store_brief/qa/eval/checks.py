"""Rule-based checks for QA evaluation."""
from __future__ import annotations

import re

from store_brief.llmwiki.card import WikiCard
from store_brief.qa.eval.schema import EvalCase, FailureType, LayerScores
from store_brief.qa.schemas import Citation, QAResponse, RetrievalHit
from store_brief.qa.tools.retrieve import is_weak_retrieval


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def _filename_stem(label: str) -> str:
    """Extract attachment filename stem from source_label."""
    blob = label or ""
    if " · " in blob:
        blob = blob.split(" · ", 1)[0]
    if blob.startswith("첨부: "):
        blob = blob[4:]
    return Path_stem(blob)


def Path_stem(name: str) -> str:
    base = name.rsplit(".", 1)[0] if "." in name else name
    return _norm(base)


def _refs_match(expected: str, actual: str) -> bool:
    if not expected or not actual:
        return False
    if expected == actual:
        return True
    exp, act = _norm(expected), _norm(actual)
    if exp == act or exp in act or act in exp:
        return True
    exp_att, _, exp_frag = expected.partition("#")
    act_att, _, act_frag = actual.partition("#")
    if _norm(exp_att) in _norm(act_att) or _norm(act_att) in _norm(exp_att):
        if not exp_frag or not act_frag:
            return True
        if _norm(exp_frag) in _norm(act_frag) or _norm(act_frag) in _norm(exp_frag):
            return True
        # row-level refs (#row:sheet:n) vs legacy (#table0 / attachment-only)
        if exp_frag.startswith("row:") or act_frag.startswith("row:"):
            exp_parts = exp_frag.split(":")
            act_parts = act_frag.split(":")
            if len(exp_parts) >= 3 and len(act_parts) >= 3:
                if _norm(exp_parts[1]) == _norm(act_parts[1]):
                    return True
    return False


def _card_matches_case(card: WikiCard, case: EvalCase) -> bool:
    if card.post_id != case.post_id:
        return False
    if _refs_match(case.source_ref, card.source_ref):
        return True
    if case.source_type == "body" and card.source_ref.endswith("#body"):
        return True
    stem = _filename_stem(case.source_label)
    if stem and stem in _norm(card.attachment_name):
        if case.expect_source_contains:
            blob = _norm(f"{card.headline}\n{card.body}")
            if _norm(case.expect_source_contains) in blob:
                return True
            return False
        if not case.source_ref or "#" not in case.source_ref:
            return True
    if case.expect_source_contains:
        blob = _norm(f"{card.headline}\n{card.body}\n{card.attachment_name}")
        if _norm(case.expect_source_contains) in blob:
            if stem and stem in _norm(card.attachment_name):
                return True
    return False


def corpus_has_source(cards: list[WikiCard], case: EvalCase) -> bool:
    if not case.expect_corpus:
        return True
    return any(_card_matches_case(card, case) for card in cards)


def check_corpus_metadata(cards: list[WikiCard], case: EvalCase) -> tuple[bool, bool]:
    """Return (indexed, metadata_ok) for expect_damdang / expect_source_contains."""
    if not case.expect_corpus:
        return True, True
    matched = [c for c in cards if _card_matches_case(c, case)]
    if not matched:
        return False, False
    if case.expect_damdang:
        if not any(c.damdang == case.expect_damdang for c in matched):
            return True, False
    if case.expect_source_contains:
        needle = _norm(case.expect_source_contains)
        if not any(
            needle in _norm(f"{c.headline}\n{c.body}") for c in matched
        ):
            return True, False
    return True, True


def check_damdang_match(cards: list[WikiCard], case: EvalCase) -> bool:
    """True when expect_damdang is absent or a matching card exists."""
    if not case.expect_damdang or not case.expect_corpus:
        return True
    matched = [c for c in cards if _card_matches_case(c, case)]
    if not matched:
        return False
    return any(c.damdang == case.expect_damdang for c in matched)


def check_retrieval(
    hits: list[RetrievalHit],
    case: EvalCase,
) -> tuple[bool, bool, bool]:
    """Return (hit@1, hit@3, weak)."""
    if not hits:
        return False, False, True
    hit1 = hits[0].post_id == case.post_id
    hit3 = any(h.post_id == case.post_id for h in hits[:3])
    weak = is_weak_retrieval(hits)
    return hit1, hit3, weak


def check_attachment(
    hits: list[RetrievalHit],
    citations: list[Citation],
    case: EvalCase,
) -> bool:
    stem = _filename_stem(case.source_label)
    targets = {_norm(case.source_ref), _norm(stem), _norm(case.source_label)}

    for h in hits[:5]:
        if h.post_id != case.post_id:
            continue
        if _refs_match(case.source_ref, h.source_ref):
            return True
        if stem and stem in _norm(h.attachment_name):
            return True
        if stem and stem in _norm(h.source_ref):
            return True

    for c in citations:
        if stem and stem in _norm(c.attachment_name):
            return True
        if _norm(c.attachment_name) in targets:
            return True

    if case.source_type == "body":
        for h in hits[:3]:
            if h.post_id == case.post_id and "(게시글 본문)" in h.attachment_name:
                return True

    return False


def classify_failure(
    *,
    layers: LayerScores,
    case: EvalCase,
    response: QAResponse,
    corpus_indexed: bool,
) -> FailureType:
    if not corpus_indexed:
        return "corpus_gap"
    if not layers.retrieval_hit_at_1 and not layers.retrieval_hit_at_3:
        return "retrieval_miss"
    if not layers.attachment_match:
        return "attachment_mismatch"
    if layers.judge_verdict == "fail":
        if "없" in (response.answer or "") and len(case.excerpt_full) > 100:
            return "answer_quality"
        return "answer_quality"
    if layers.judge_verdict == "partial" and layers.judge_inferred_ratio < 0.7:
        return "answer_quality"
    if not layers.retrieval_hit_at_1:
        return "retrieval_miss"
    return "unknown"


def build_suggested_prompt(
    case: EvalCase,
    failure_type: FailureType,
    response: QAResponse,
    layers: LayerScores,
) -> str:
    top = response.hits[0] if response.hits else None
    lines = [
        f"QA eval 실패 ({failure_type}) — 다음 케이스를 수정해 주세요.",
        "",
        f"질문: {case.question}",
        f"기대 출처: {case.post_title} / {case.source_label}",
        f"source_ref: {case.source_ref}",
        f"발췌: {case.excerpt_full[:400]}…",
        "",
        f"실제 답변: {response.answer[:300]}",
    ]
    if top:
        lines.extend([
            "",
            f"Top hit: [{top.damdang}] {top.headline} (score={top.score})",
            f"  post_id={top.post_id} attachment={top.attachment_name}",
            f"  source_ref={top.source_ref}",
        ])
    lines.extend([
        "",
        f"검증: hit@1={layers.retrieval_hit_at_1} attachment={layers.attachment_match} "
        f"judge={layers.judge_verdict} ratio={layers.judge_inferred_ratio}",
        "",
        "최소 범위로 수정하고 pytest tests/test_qa_*.py 를 통과시킨 뒤 "
        "python scripts/run_qa_eval.py -n 5 로 재검증하세요.",
    ])
    if failure_type == "corpus_gap":
        lines.append("힌트: from_parsed.py 색인 로직 확인 (llmwiki rebuild 필요)")
    elif failure_type == "retrieval_miss":
        lines.append("힌트: retrieve.py / intent.py / routing.py 확인")
    elif failure_type == "attachment_mismatch":
        lines.append("힌트: anchor_source_ref 부스트 및 citation 로직 확인")
    elif failure_type == "answer_quality":
        lines.append("힌트: answer.py 프롬프트 및 hits 컨텍스트 확인")
    return "\n".join(lines)


def compute_pass(
    layers: LayerScores,
    *,
    min_judge_ratio: float = 0.7,
) -> bool:
    if not layers.retrieval_hit_at_1:
        return False
    if not layers.attachment_match:
        return False
    if layers.judge_verdict == "skipped":
        return True
    if layers.judge_verdict == "fail":
        return False
    if layers.judge_verdict == "partial":
        return layers.judge_inferred_ratio >= min_judge_ratio
    return layers.judge_verdict == "pass"
