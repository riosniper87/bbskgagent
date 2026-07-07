"""Load board posts for a given day from data/raw/{as_of}/.

Prototype layout: each day folder holds posts.json (list of posts) and an attachments/
subfolder. Swap this module for a DB/API reader later — nothing downstream depends on the
source, only on the Post model.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from store_brief.extract.schema import Attachment, Post

_EXT_KIND = {
    ".xlsx": "excel", ".xls": "excel", ".xlsb": "excel", ".csv": "excel",
    ".pptx": "pptx", ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
}


def _post_from_record(p: dict, day_dir: Path) -> Post:
    atts = []
    for a in p.get("attachments", []):
        path = str(day_dir / "attachments" / a)
        kind = _EXT_KIND.get(Path(a).suffix.lower(), "unknown")
        atts.append(Attachment(id=f'{p["id"]}_{a}', filename=a, path=path, kind=kind))
    return Post(
        id=p["id"], title=p["title"], body=p["body"],
        posted_date=date.fromisoformat(p["posted_date"]), attachments=atts,
    )


def load_posts(raw_dir: str, as_of: date, *, limit: int | None = None) -> list[Post]:
    day_dir = Path(raw_dir) / as_of.isoformat()
    pj = day_dir / "posts.json"
    if not pj.exists():
        return []
    posts = []
    for p in json.loads(pj.read_text(encoding="utf-8")):
        posts.append(_post_from_record(p, day_dir))
        if limit and len(posts) >= limit:
            break
    return posts


def load_posts_backfill(
    raw_dir: str,
    as_of: date,
    *,
    limit: int | None = None,
) -> list[Post]:
    """Load all posts with posted_date <= as_of across data/raw/{date}/ folders."""
    raw = Path(raw_dir)
    if not raw.exists():
        return []

    by_id: dict[str, Post] = {}
    for day_dir in sorted(raw.iterdir()):
        if not day_dir.is_dir():
            continue
        try:
            day = date.fromisoformat(day_dir.name)
        except ValueError:
            continue
        if day > as_of:
            continue
        pj = day_dir / "posts.json"
        if not pj.exists():
            continue
        for p in json.loads(pj.read_text(encoding="utf-8")):
            post = _post_from_record(p, day_dir)
            by_id[post.id] = post
            if limit and len(by_id) >= limit:
                return list(by_id.values())

    return list(by_id.values())
