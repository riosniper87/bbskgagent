"""Lightweight theme labelling, anchored to the known category vocabulary.

Category is already chosen during extraction (constrained to the seed list). Here we add a
short free-form theme label per event. Clustering of free themes into stable ones is a
later step (theme/cluster.py) — not needed for the prototype.
"""
from __future__ import annotations

from store_brief.llm import prompts


def assign_theme(event, categories: list[str], llm) -> str:
    prompt = prompts.CLASSIFY_THEME.format(
        categories=", ".join(categories), title=event.title, summary=event.summary,
    )
    return llm.complete(prompt).strip()
