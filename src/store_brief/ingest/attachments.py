"""Run the deterministic parser over each attachment of a post.

Optional persistence via ParsedAttachmentStore for human review before LLM steps.
"""
from __future__ import annotations

import logging
from pathlib import Path

from store_brief.parse import router
from store_brief.parse.store import ParsedAttachmentStore, _att_key

log = logging.getLogger(__name__)


def parse_post_attachments(post, workdir: str, **parse_kwargs):
    parsed = []
    for att in post.attachments:
        if not Path(att.path).is_file():
            continue
        try:
            parsed.append(router.parse(att, workdir, **parse_kwargs))
        except Exception:
            continue
    return parsed


def resolve_parsed_attachments(
    post,
    workdir: str,
    *,
    parsed_root: str | Path | None = None,
    force: bool = False,
    llm=None,
    with_llm_tables: bool = False,
) -> list:
    """Load from parsed cache when fresh; otherwise parse on the fly."""
    parse_kwargs = {"llm": llm, "with_llm_tables": with_llm_tables}
    if parsed_root is None:
        return parse_post_attachments(post, workdir, **parse_kwargs)

    store = ParsedAttachmentStore(parsed_root)
    results = []
    for att in post.attachments:
        if not Path(att.path).is_file():
            continue
        if not force and store.is_fresh(post.id, att.id, Path(att.path)):
            loaded = store.load_parsed_attachment(post.id, att.id)
            if loaded is not None:
                results.append(loaded)
                continue
        try:
            results.append(router.parse(att, workdir, **parse_kwargs))
        except Exception:
            continue
    return results


def parse_and_store_post(
    post,
    workdir: str,
    store: ParsedAttachmentStore,
    *,
    force: bool = False,
    kinds: set[str] | None = None,
    llm=None,
    with_llm_tables: bool = False,
) -> list:
    """Parse attachments, persist under data/parsed/, return ParsedAttachment list."""
    parse_kwargs = {"llm": llm, "with_llm_tables": with_llm_tables}
    results = []
    keys: list[str] = []

    for att in post.attachments:
        if kinds is not None and att.kind not in kinds:
            continue
        if not Path(att.path).is_file():
            log.warning("missing attachment: %s", att.filename)
            continue
        key = _att_key(att.id)
        if not force and store.is_fresh(post.id, att.id, Path(att.path)):
            loaded = store.load_parsed_attachment(post.id, att.id)
            if loaded is not None:
                results.append(loaded)
                keys.append(key)
                continue

        try:
            pa = router.parse(att, workdir, **parse_kwargs)
            store.save(post, att, pa, workdir=Path(workdir))
            results.append(pa)
            keys.append(key)
        except Exception as exc:
            msg = str(exc) or repr(exc)
            log.warning("parse failed %s: %s", att.filename, msg)
            store.save_error(post, att, msg)

    if keys:
        existing: list[str] = []
        meta_path = store.post_dir(post.id) / "meta.json"
        if meta_path.exists():
            import json
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            existing = meta.get("records", [])
        store.update_meta(post, sorted(set(existing) | set(keys)))
    return results
