"""Map temporal intent to TemporalScope."""
from __future__ import annotations

from datetime import date, timedelta

from store_brief.qa.schemas import QuestionIntent, TemporalScope, TimeMode

_DESCRIPTIONS = {
    TimeMode.active_on: "적용/행사 기간 기준",
    TimeMode.posted_between: "게시일 기준 기간",
    TimeMode.observable_on: "해당 시점에 유효했던 공지",
    TimeMode.version_diff: "개정·변경 전후 비교",
    TimeMode.none: "시간 필터 없음",
}


def resolve_temporal_scope(
    intent: QuestionIntent,
    *,
    default_query_date: date | None = None,
) -> TemporalScope:
    qd = intent.query_date or default_query_date
    df = intent.date_from
    dt = intent.date_to

    if intent.time_mode == TimeMode.posted_between and qd and not df and not dt:
        df = qd - timedelta(days=45)
        dt = qd

    return TemporalScope(
        time_mode=intent.time_mode,
        query_date=qd,
        date_from=df,
        date_to=dt,
        description=_DESCRIPTIONS.get(intent.time_mode, ""),
    )
