"""Schemas for QA evaluation runs."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

FailureType = Literal[
    "corpus_gap",
    "retrieval_miss",
    "attachment_mismatch",
    "answer_quality",
    "suggest_mismatch",
    "unknown",
]

JudgeVerdict = Literal["pass", "partial", "fail", "skipped"]


class EvalCase(BaseModel):
    """Ground truth from suggest step."""
    question: str
    post_id: str
    post_title: str
    posted_date: str
    source_type: str
    source_label: str
    source_ref: str
    excerpt_full: str
    seed: int | None = None
    expect_damdang: str | None = None
    expect_source_contains: str | None = None
    expect_corpus: bool = True


class LayerScores(BaseModel):
    retrieval_hit_at_1: bool = False
    retrieval_hit_at_3: bool = False
    weak_retrieval: bool = True
    attachment_match: bool = False
    corpus_indexed: bool = True
    damdang_match: bool = True
    judge_verdict: JudgeVerdict = "skipped"
    judge_inferred_ratio: float = 0.0
    judge_reason: str = ""


class EvalResult(BaseModel):
    case: EvalCase
    passed: bool = False
    failure_type: FailureType | None = None
    layers: LayerScores = Field(default_factory=LayerScores)
    answer: str = ""
    top_hit_post_id: str | None = None
    top_hit_attachment: str | None = None
    top_hit_source_ref: str | None = None
    top_hit_score: float = 0.0
    citation_attachments: list[str] = Field(default_factory=list)
    suggested_prompt: str = ""
    traces_summary: dict[str, Any] = Field(default_factory=dict)


class EvalRunSummary(BaseModel):
    run_id: str
    as_of: str
    started_at: str
    n_cases: int
    n_passed: int
    overall_pass_rate: float
    retrieval_hit_at_1_rate: float
    retrieval_hit_at_3_rate: float
    attachment_match_rate: float
    damdang_match_rate: float = 1.0
    answer_adequacy_rate: float
    threshold: float
    seed_base: int | None = None
    failure_counts: dict[str, int] = Field(default_factory=dict)
    mermaid_flow: str = ""
    results: list[EvalResult] = Field(default_factory=list)
