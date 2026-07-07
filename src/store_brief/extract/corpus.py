"""Load post corpora + parsed attachments for provenance repair."""
from __future__ import annotations

from pathlib import Path

from store_brief.extract.provenance import PostCorpus, build_post_corpus
from store_brief.ingest import board
from store_brief.parse.router import ParsedAttachment
from store_brief.parse.store import ParsedAttachmentStore


def load_corpora_for_window(
    as_of,
    *,
    data_dir: str,
    raw_subdir: str = "raw",
) -> tuple[dict[str, PostCorpus], dict[str, list[ParsedAttachment]]]:
    raw_base = Path(data_dir) / raw_subdir
    parsed_root = Path(data_dir) / "parsed"
    posts = board.load_posts_backfill(str(raw_base), as_of)
    parse_store = ParsedAttachmentStore(parsed_root)

    corpora: dict[str, PostCorpus] = {}
    parsed_by_post: dict[str, list[ParsedAttachment]] = {}
    for post in posts:
        parsed: list[ParsedAttachment] = []
        for att in post.attachments:
            loaded = parse_store.load_parsed_attachment(post.id, att.id)
            if loaded is not None:
                parsed.append(loaded)
        parsed_by_post[post.id] = parsed
        corpora[post.id] = build_post_corpus(post, parsed)
    return corpora, parsed_by_post
