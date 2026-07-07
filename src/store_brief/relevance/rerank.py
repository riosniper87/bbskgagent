"""Optional LLM rerank/filter of candidate events for a given employee. Skeleton."""
from __future__ import annotations

import json

from store_brief.llm import prompts


def rerank(employee, candidates, llm) -> list:
    if not candidates:
        return []
    listing = "\n".join(f'{{"id":"{e.id}","title":"{e.title}","summary":"{e.summary}"}}'
                        for e in candidates)
    prompt = prompts.RERANK.format(
        branch=employee.branch, is_manager=employee.is_store_manager,
        categories=", ".join(employee.categories), candidates=listing,
    )
    try:
        order = json.loads(llm.complete(prompt))
    except Exception:
        return candidates  # fall back to deterministic order if rerank output is unusable
    by_id = {e.id: e for e in candidates}
    return [by_id[i] for i in order if i in by_id]
