"""Resolve WikiCard → Post / Attachment / Slice provenance."""
from __future__ import annotations

import hashlib

from store_brief.extract.schema import Attachment, Post
from store_brief.kg.schema import CardProvenance
from store_brief.viewer.urls import media_url


def slice_node_id(source_ref: str) -> str:
    return f"slice:{hashlib.sha1(source_ref.encode()).hexdigest()[:16]}"


def attachment_node_id(attachment_id: str) -> str:
    return f"att:{hashlib.sha1(attachment_id.encode()).hexdigest()[:16]}"


def post_node_id(post_id: str) -> str:
    return f"post:{post_id}"


def product_node_id(prd_cd: str) -> str:
    return f"prd:{prd_cd.strip().upper()}"


def damdang_node_id(name: str) -> str:
    return f"damdang:{name}"


def keyword_node_id(keyword: str) -> str:
    norm = keyword.strip().lower()
    return f"kw:{hashlib.sha1(norm.encode()).hexdigest()[:12]}"


def parse_attachment_id_from_source_ref(source_ref: str) -> str:
    """`{post_id}_{filename}#s1` → attachment_id without hash prefix on post."""
    if "#" in source_ref:
        return source_ref.rsplit("#", 1)[0]
    return source_ref


def find_attachment(post: Post, attachment_name: str, source_ref: str) -> Attachment | None:
    att_id = parse_attachment_id_from_source_ref(source_ref)
    for att in post.attachments:
        if att.id == att_id or att.filename == attachment_name:
            return att
    for att in post.attachments:
        if att.filename == attachment_name:
            return att
    return None


def slice_viewer_rel_path(source_ref: str, attachment_id: str) -> str | None:
    """Map source_ref to parsed images/ path when possible."""
    if "#" not in source_ref:
        return None
    suffix = source_ref.split("#", 1)[1]
    if suffix.startswith("s") and suffix[1:].isdigit():
        slide = int(suffix[1:])
        return f"images/{attachment_id}_s{slide}.png"
    if suffix.startswith("p") and suffix[1:].isdigit():
        page = int(suffix[1:])
        return f"images/{attachment_id}_p{page}.png"
    return None


def build_card_provenance(
    *,
    post: Post,
    attachment: Attachment | None,
    attachment_name: str,
    source_ref: str,
    post_title: str,
) -> CardProvenance:
    att = attachment
    attachment_id = att.id if att else parse_attachment_id_from_source_ref(source_ref)
    rel = slice_viewer_rel_path(source_ref, attachment_id) if att else None
    return CardProvenance(
        post_id=post.id,
        post_title=post_title,
        posted_date=post.posted_date.isoformat(),
        attachment_id=attachment_id,
        attachment_name=attachment_name,
        attachment_path=att.path if att else None,
        attachment_kind=att.kind if att else None,
        source_ref=source_ref,
        slice_id=slice_node_id(source_ref),
        viewer_url=media_url(post.id, rel) if rel else None,
    )


def body_excerpt(body: str, max_len: int = 400) -> str:
    text = (body or "").replace("\r\n", "\n").strip()
    if len(text) <= max_len:
        return text
    return text[:max_len] + "…"
