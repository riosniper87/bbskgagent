"""Change detection: week-over-week and policy-version diffs.

Detection is structural and deterministic. Only the human-readable *explanation* of a
policy change is delegated to the LLM (see describe_policy_change), because summarizing
'what changed between two texts' is a language task, while 'which records changed' is not.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Iterable


def updated_since(events: Iterable, as_of: date, days: int = 7) -> list:
    """Events whose `last_updated` falls in the trailing window (내용이 갱신된 항목)."""
    window_start = as_of - timedelta(days=days)
    out = []
    for e in events:
        upd = getattr(e, "last_updated", None)
        if upd is not None and window_start <= upd <= as_of and getattr(e, "version_of", None):
            out.append(e)
    return out


def policy_change_pairs(events: Iterable, as_of: date, days: int = 7) -> list[dict]:
    """Pair each newly-superseding policy with the record it replaced.

    Returns [{"old": Event|None, "new": Event, "diff": ""}]. `diff` is filled later by
    describe_policy_change(); kept empty here so detection stays LLM-free and testable.
    """
    by_id = {getattr(e, "id", None): e for e in events}
    pairs: list[dict] = []
    for e in updated_since(events, as_of, days):
        prev = by_id.get(getattr(e, "version_of", None))
        pairs.append({"old": prev, "new": e, "diff": ""})
    return pairs


def describe_policy_change(old, new, llm) -> str:
    """LLM hook: given the prior and current policy records, produce a short Korean
    description of what changed. `llm` is an llm.client.LLMClient. Skeleton only.
    """
    from store_brief.llm import prompts  # local import to avoid hard dep at module load

    old_text = "" if old is None else f"{old.title}\n{old.summary}"
    prompt = prompts.POLICY_DIFF.format(old=old_text, new=f"{new.title}\n{new.summary}")
    return llm.complete(prompt)
