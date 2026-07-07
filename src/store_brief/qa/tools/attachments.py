"""List attachments from retrieval hits."""
from __future__ import annotations

from store_brief.qa.schemas import AttachmentRef, RetrievalHit


def list_attachments(hits: list[RetrievalHit]) -> list[AttachmentRef]:
    seen: set[str] = set()
    out: list[AttachmentRef] = []
    for h in hits:
        key = f"{h.post_id}|{h.attachment_name}"
        if key in seen:
            continue
        seen.add(key)
        prov = h.provenance or {}
        out.append(
            AttachmentRef(
                attachment_id=prov.get("attachment_id") or key,
                attachment_name=h.attachment_name,
                post_id=h.post_id,
                post_title=h.post_title,
                kind=prov.get("attachment_kind"),
                path=prov.get("attachment_path"),
                post_url=h.post_url or f"/post/{h.post_id}",
            ),
        )
    return out
