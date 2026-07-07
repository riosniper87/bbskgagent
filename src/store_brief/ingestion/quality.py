"""Parse-quality report: review_flag / extraction distribution over parsed data.

Runs the deterministic ingestion normalizers over ``data/parsed`` and
aggregates how many records carry a review_flag, per extraction kind and
per attachment kind — the before/after comparison tool for parsing changes.
"""
from __future__ import annotations

import json
import logging
from collections import Counter
from pathlib import Path
from typing import Any

from store_brief.ingestion.parse_pdf import parse_pdf_from_record
from store_brief.ingestion.parse_pptx import parse_pptx_from_record
from store_brief.ingestion.parse_xlsx import parse_xlsx_from_record
from store_brief.parse.store import ParsedAttachmentStore

log = logging.getLogger(__name__)

_MAX_FLAGGED_LISTED = 200


def build_quality_report(data_dir: str | Path) -> dict[str, Any]:
    """Aggregate normalized-record quality stats from ``<data_dir>/parsed``."""
    data_dir = Path(data_dir)
    parsed_root = data_dir / "parsed"
    store = ParsedAttachmentStore(parsed_root)

    totals: Counter[str] = Counter()
    flags: Counter[str] = Counter()
    extractions: Counter[str] = Counter()
    kinds: Counter[str] = Counter()
    flagged: list[dict[str, Any]] = []
    attachments_scanned = 0

    for post_id in store.list_post_ids():
        meta_path = parsed_root / post_id / "meta.json"
        if not meta_path.is_file():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except Exception as exc:
            log.warning("bad meta.json for %s: %s", post_id, exc)
            continue
        for att_key in meta.get("records", []):
            record = store.load_record(post_id, att_key)
            if record is None or record.error:
                continue
            if record.kind == "excel":
                norm = parse_xlsx_from_record(record, post_id, data_dir=data_dir)
            elif record.kind == "pptx":
                norm = parse_pptx_from_record(record, post_id)
            elif record.kind == "pdf":
                norm = parse_pdf_from_record(record, post_id)
            else:
                continue
            attachments_scanned += 1
            kinds[record.kind] += len(norm)
            for rec in norm:
                totals["records"] += 1
                extractions[rec.provenance.extraction] += 1
                if rec.review_flag:
                    flags[rec.review_flag] += 1
                    if len(flagged) < _MAX_FLAGGED_LISTED:
                        flagged.append({
                            "post_id": post_id,
                            "attachment": rec.attachment_name,
                            "locator": rec.provenance.locator,
                            "flag": rec.review_flag,
                            "title": rec.title[:80],
                        })

    total = totals["records"]
    flagged_total = sum(flags.values())
    return {
        "attachments_scanned": attachments_scanned,
        "records_total": total,
        "flagged_total": flagged_total,
        "flagged_ratio": round(flagged_total / total, 4) if total else 0.0,
        "flags": dict(flags.most_common()),
        "extractions": dict(extractions.most_common()),
        "records_by_kind": dict(kinds.most_common()),
        "flagged_records": flagged,
    }
