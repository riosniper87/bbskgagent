"""Batch QA evaluation: suggest → ask → score."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

from store_brief.llm.client import LLMClient
from store_brief.qa.eval.checks import (
    build_suggested_prompt,
    check_attachment,
    check_corpus_metadata,
    check_damdang_match,
    check_retrieval,
    classify_failure,
    compute_pass,
    corpus_has_source,
)
from store_brief.qa.eval.promote import load_regression_cases
from store_brief.qa.eval.judge import judge_answer
from store_brief.qa.eval.report import update_global_summary, write_run_report
from store_brief.qa.eval.schema import EvalCase, EvalResult, EvalRunSummary, LayerScores
from store_brief.qa.korean import extract_question_keywords
from store_brief.qa.orchestrator import QAOrchestrator
from store_brief.qa.schemas import QAAskRequest, QAResponse
from store_brief.qa.tools.suggest_question import suggest_question
from store_brief.qa.corpus import load_corpus
from store_brief.llmwiki.grouping import load_qa_damdang_roster
from store_brief.qa.tools.retrieve import retrieve_wiki_cards


def _traces_summary(traces: list) -> dict:
    return {
        t.tool: {"ms": t.ms, "output_keys": list((t.output or {}).keys())}
        for t in traces
    }


def run_single_case(
    *,
    orch: QAOrchestrator,
    llm: LLMClient,
    as_of: str,
    seed: int,
    use_judge: bool = True,
    min_judge_ratio: float = 0.7,
) -> EvalResult:
    question, snippet, use_seed = suggest_question(
        llm, data_dir=orch.data_dir, as_of=as_of, seed=seed, corpus=orch.corpus,
    )
    case = EvalCase(
        question=question,
        post_id=snippet.post_id,
        post_title=snippet.post_title,
        posted_date=snippet.posted_date,
        source_type=snippet.source_type,
        source_label=snippet.source_label,
        source_ref=snippet.source_ref,
        excerpt_full=snippet.text,
        seed=use_seed,
    )

    resp = orch.ask(
        QAAskRequest(
            question=question,
            as_of=as_of,
            anchor_post_id=case.post_id,
            anchor_source_ref=case.source_ref,
        ),
    )

    corpus = orch.corpus
    indexed = corpus_has_source(corpus.cards, case)
    hit1, hit3, weak = check_retrieval(resp.hits, case)
    att_match = check_attachment(resp.hits, resp.citations, case)

    layers = LayerScores(
        retrieval_hit_at_1=hit1,
        retrieval_hit_at_3=hit3,
        weak_retrieval=weak,
        attachment_match=att_match,
        corpus_indexed=indexed,
    )

    if use_judge:
        verdict, ratio, reason = judge_answer(llm, case, resp)
        layers.judge_verdict = verdict
        layers.judge_inferred_ratio = ratio
        layers.judge_reason = reason

    passed = compute_pass(layers, min_judge_ratio=min_judge_ratio)
    failure_type = None
    suggested = ""
    if not passed:
        failure_type = classify_failure(
            layers=layers,
            case=case,
            response=resp,
            corpus_indexed=indexed,
        )
        suggested = build_suggested_prompt(case, failure_type, resp, layers)

    top = resp.hits[0] if resp.hits else None
    return EvalResult(
        case=case,
        passed=passed,
        failure_type=failure_type,
        layers=layers,
        answer=resp.answer,
        top_hit_post_id=top.post_id if top else None,
        top_hit_attachment=top.attachment_name if top else None,
        top_hit_source_ref=top.source_ref if top else None,
        top_hit_score=top.score if top else 0.0,
        citation_attachments=[c.attachment_name for c in resp.citations],
        suggested_prompt=suggested,
        traces_summary=_traces_summary(resp.traces),
    )


def run_eval(
    *,
    data_dir: str | Path,
    as_of: str,
    n_cases: int = 10,
    seed: int | None = None,
    threshold: float = 0.85,
    use_judge: bool = True,
    min_judge_ratio: float = 0.7,
    openai_model: str | None = None,
) -> EvalRunSummary:
    data_dir = Path(data_dir)
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8]
    started = datetime.now(timezone.utc).isoformat()

    llm = LLMClient.openai(model=openai_model)
    orch = QAOrchestrator(llm=llm, data_dir=str(data_dir), as_of=as_of)
    _ = orch.corpus  # preload

    base_seed = seed if seed is not None else 42
    results: list[EvalResult] = []
    for i in range(n_cases):
        case_seed = base_seed + i
        try:
            result = run_single_case(
                orch=orch,
                llm=llm,
                as_of=as_of,
                seed=case_seed,
                use_judge=use_judge,
                min_judge_ratio=min_judge_ratio,
            )
            results.append(result)
        except Exception as exc:
            results.append(EvalResult(
                case=EvalCase(
                    question="",
                    post_id="",
                    post_title="",
                    posted_date="",
                    source_type="",
                    source_label="",
                    source_ref="",
                    excerpt_full="",
                    seed=case_seed,
                ),
                passed=False,
                failure_type="unknown",
                answer=f"eval error: {exc}",
                suggested_prompt=f"Eval case {i} failed with: {exc}",
            ))

    n = len(results) or 1
    n_passed = sum(1 for r in results if r.passed)
    failure_counts: dict[str, int] = {}
    for r in results:
        if r.failure_type:
            failure_counts[r.failure_type] = failure_counts.get(r.failure_type, 0) + 1

    def _rate(pred) -> float:
        return sum(1 for r in results if pred(r)) / n

    summary = EvalRunSummary(
        run_id=run_id,
        as_of=as_of,
        started_at=started,
        n_cases=n,
        n_passed=n_passed,
        overall_pass_rate=n_passed / n,
        retrieval_hit_at_1_rate=_rate(lambda r: r.layers.retrieval_hit_at_1),
        retrieval_hit_at_3_rate=_rate(lambda r: r.layers.retrieval_hit_at_3),
        attachment_match_rate=_rate(lambda r: r.layers.attachment_match),
        damdang_match_rate=_rate(lambda r: r.layers.damdang_match),
        answer_adequacy_rate=_rate(
            lambda r: r.layers.judge_verdict in ("pass", "partial")
            and (r.layers.judge_verdict == "pass" or r.layers.judge_inferred_ratio >= min_judge_ratio),
        ),
        threshold=threshold,
        seed_base=base_seed,
        failure_counts=failure_counts,
        results=results,
    )

    out_dir = data_dir / "eval" / as_of / run_id
    write_run_report(summary, out_dir)
    update_global_summary(data_dir, summary)
    return summary


def run_regression_eval(
    *,
    data_dir: str | Path,
    as_of: str,
    threshold: float = 0.85,
    use_judge: bool = True,
    min_judge_ratio: float = 0.7,
    openai_model: str | None = None,
) -> EvalRunSummary:
    """Run frozen regression_cases.json through the eval pipeline."""
    data_dir = Path(data_dir)
    cases = load_regression_cases(data_dir)
    if not cases:
        raise ValueError("no regression cases in data/eval/regression_cases.json")

    run_id = "regression-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    started = datetime.now(timezone.utc).isoformat()

    llm = None
    orch = None
    try:
        llm = LLMClient.openai(model=openai_model)
        orch = QAOrchestrator(llm=llm, data_dir=str(data_dir), as_of=as_of)
        _ = orch.corpus
    except RuntimeError:
        if use_judge:
            raise

    corpus = orch.corpus if orch else load_corpus(data_dir, as_of)
    roster = load_qa_damdang_roster(str(Path(data_dir) / "rnr.txt"))

    results: list[EvalResult] = []
    for case in cases:
        try:
            if orch is not None and llm is not None:
                resp = orch.ask(
                    QAAskRequest(
                        question=case.question,
                        as_of=as_of,
                        anchor_post_id=case.post_id,
                        anchor_source_ref=case.source_ref,
                    ),
                )
            else:
                # Offline (no-LLM) path: deterministic keyword extraction,
                # mirroring the intent-parse fallback used in the live pipeline.
                offline_keywords = extract_question_keywords(case.question)
                if not offline_keywords:
                    offline_keywords = case.question.split()[:8]
                hits = retrieve_wiki_cards(
                    corpus,
                    keywords=offline_keywords,
                    damdangs=roster,
                    anchor_post_id=case.post_id,
                    anchor_source_ref=case.source_ref,
                )
                resp = QAResponse(question=case.question, answer="", hits=hits)

            indexed = corpus_has_source(corpus.cards, case)
            _, meta_ok = check_corpus_metadata(corpus.cards, case)
            damdang_ok = check_damdang_match(corpus.cards, case)
            hit1, hit3, weak = check_retrieval(resp.hits, case)
            att_match = check_attachment(resp.hits, resp.citations, case)

            layers = LayerScores(
                retrieval_hit_at_1=hit1,
                retrieval_hit_at_3=hit3,
                weak_retrieval=weak,
                attachment_match=att_match,
                corpus_indexed=indexed and meta_ok,
                damdang_match=damdang_ok,
            )

            if use_judge and case.expect_corpus and llm is not None:
                verdict, ratio, reason = judge_answer(llm, case, resp)
                layers.judge_verdict = verdict
                layers.judge_inferred_ratio = ratio
                layers.judge_reason = reason
            else:
                layers.judge_verdict = "skipped"

            passed = compute_pass(layers, min_judge_ratio=min_judge_ratio)
            if not case.expect_corpus:
                passed = True
            elif not indexed:
                passed = False
            elif not meta_ok:
                passed = False
            elif not damdang_ok:
                passed = False

            failure_type = None
            suggested = ""
            if not passed:
                failure_type = classify_failure(
                    layers=layers,
                    case=case,
                    response=resp,
                    corpus_indexed=indexed,
                )
                suggested = build_suggested_prompt(case, failure_type, resp, layers)

            top = resp.hits[0] if resp.hits else None
            results.append(EvalResult(
                case=case,
                passed=passed,
                failure_type=failure_type,
                layers=layers,
                answer=resp.answer,
                top_hit_post_id=top.post_id if top else None,
                top_hit_attachment=top.attachment_name if top else None,
                top_hit_source_ref=top.source_ref if top else None,
                top_hit_score=top.score if top else 0.0,
                citation_attachments=[c.attachment_name for c in resp.citations],
                suggested_prompt=suggested,
                traces_summary=_traces_summary(resp.traces),
            ))
        except Exception as exc:
            results.append(EvalResult(
                case=case,
                passed=False,
                failure_type="unknown",
                answer=f"eval error: {exc}",
                suggested_prompt=str(exc),
            ))

    n = len(results) or 1
    n_passed = sum(1 for r in results if r.passed)
    failure_counts: dict[str, int] = {}
    for r in results:
        if r.failure_type:
            failure_counts[r.failure_type] = failure_counts.get(r.failure_type, 0) + 1

    def _rate(pred) -> float:
        return sum(1 for r in results if pred(r)) / n

    summary = EvalRunSummary(
        run_id=run_id,
        as_of=as_of,
        started_at=started,
        n_cases=n,
        n_passed=n_passed,
        overall_pass_rate=n_passed / n,
        retrieval_hit_at_1_rate=_rate(lambda r: r.layers.retrieval_hit_at_1),
        retrieval_hit_at_3_rate=_rate(lambda r: r.layers.retrieval_hit_at_3),
        attachment_match_rate=_rate(lambda r: r.layers.attachment_match),
        damdang_match_rate=_rate(lambda r: r.layers.damdang_match),
        answer_adequacy_rate=_rate(
            lambda r: r.layers.judge_verdict in ("pass", "partial")
            and (r.layers.judge_verdict == "pass" or r.layers.judge_inferred_ratio >= min_judge_ratio),
        ),
        threshold=threshold,
        seed_base=None,
        failure_counts=failure_counts,
        results=results,
    )

    out_dir = data_dir / "eval" / as_of / run_id
    write_run_report(summary, out_dir)
    update_global_summary(data_dir, summary)
    return summary
