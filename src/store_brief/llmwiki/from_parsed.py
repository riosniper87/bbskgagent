"""Build llmwiki from parsed attachments + product-code routing (greenfield)."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from store_brief.extract.schema import ExtractedTable, ImageNote
from store_brief.ingestion.parse_xlsx import parse_xlsx_from_record
from store_brief.ingestion.parse_pptx import parse_pptx_from_record
from store_brief.ingestion.parse_pdf import parse_pdf_from_record
from store_brief.ingestion.schema import NormalizedRecord
from store_brief.hisis.batch_lookup import lookup_damdang_map
from store_brief.hisis.prd_codes import extract_model_skus, extract_prd_codes
from store_brief.ingest import board
from store_brief.llmwiki.card import WikiCard
from store_brief.llmwiki.enrichment import (
    PostMeta,
    damdang_hints_from_filename,
    enrich_records,
    is_promo_excel_slice,
)
from store_brief.llmwiki.from_posts import collect_post_body_cards, infer_damdangs_from_text
from store_brief.llmwiki.keywords import enrich_cards_keywords
from store_brief.llmwiki.grouping import (
    FALLBACK_KEY,
    MANAGER_KEY,
    load_qa_damdang_roster,
    load_rnr_damdang_roster,
    product_codes_for_damdang,
    product_damdang_for_codes,
)
from store_brief.parse.store import ParsedAttachmentStore
from store_brief.temporal.meta import TemporalMeta, link_card_versions

_SLIDE_SPLIT = re.compile(r"(?=###\s*슬라이드\s*\d+)", re.MULTILINE)
_MAX_BODY = 1_200
_MIN_POST_BODY_LEN = 80
_INVENTORY_SHEET_RE = re.compile(
    r"지사지점재고|소진율|재고확인|마감기준|전사재고|타사환출|히어로.*진행|생산\s*계획|종합현황",
    re.I,
)
_COL_HEADER_NOISE = re.compile(r"col_\d+")
_PROMO_EXCEL_RE = re.compile(
    r"소진\s*리스트|추가행사가|기존소진가|출하가|클리어런스|행사가",
    re.I,
)


def _damdang_hints_from_filename(filename: str) -> set[str]:
    return damdang_hints_from_filename(filename)


def _is_promo_excel_slice(kind: str, filename: str, text: str) -> bool:
    return is_promo_excel_slice(kind, filename, text)


@dataclass
class BuildStats:
    posts_scanned: int = 0
    slices_scanned: int = 0
    slices_with_codes: int = 0
    post_body_cards: int = 0
    cards_written: int = 0
    unique_codes: int = 0
    codes_resolved: int = 0


def _headline(text: str, fallback: str, *, source_ref: str = "", filename: str = "") -> str:
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("●"):
            title = line[1:].strip()
            if title and not _COL_HEADER_NOISE.search(title):
                return title[:120]
    m = re.search(r"###\s*시트:\s*(.+)", text)
    if m:
        sheet = m.group(1).strip()
        if _INVENTORY_SHEET_RE.search(sheet):
            return fallback[:120]
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("●"):
                return f"{sheet} — {line[1:].strip()}"[:120]
        if sheet and sheet != "Sheet1":
            return sheet[:120]
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("###") or line.startswith("|"):
            continue
        if line in ("No.", "구분", "모델명", "세트코드", "제품코드"):
            continue
        if _COL_HEADER_NOISE.search(line) and "모델명" not in line and "모델" not in line:
            continue
        return line[:120]
    if filename:
        stem = Path(filename).stem
        if stem and stem not in ("Sheet1", "table0"):
            return stem[:120]
    return fallback[:120]

def _skip_noisy_slice(text: str, source_ref: str, filename: str) -> bool:
    blob = f"{text}\n{filename}\n{source_ref}"
    if _INVENTORY_SHEET_RE.search(blob):
        return True
    m = re.search(r"###\s*시트:\s*(.+)", text or "")
    if m and _INVENTORY_SHEET_RE.search(m.group(1)):
        return True
    head = (text or "").strip().split("\n", 1)[0]
    if head.startswith("|") and _COL_HEADER_NOISE.search(head):
        if "모델명" not in head and "모델" not in head and "제품명" not in head:
            return True
    return False


def _iter_slices(record) -> list[tuple[str, str]]:
    """Yield (source_ref, text) units from a stored parse record."""
    if record.pages:
        return [(p["ref"], p.get("text") or "") for p in record.pages]
    if getattr(record, "images", None):
        out: list[tuple[str, str]] = []
        for img in record.images:
            ref = getattr(img, "source_ref", None) or (img.get("source_ref") if isinstance(img, dict) else None)
            if ref:
                out.append((ref, ""))
        if out:
            return out
    text = record.text or ""
    blocks = _SLIDE_SPLIT.split(text)
    if len(blocks) <= 1:
        return [(record.attachment_id, text)]
    out: list[tuple[str, str]] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m = re.search(r"###\s*슬라이드\s*(\d+)", block)
        ref = f"{record.attachment_id}#s{m.group(1)}" if m else record.attachment_id
        out.append((ref, block))
    return out


def _tables_for_ref(record, source_ref: str) -> list[ExtractedTable]:
    if "#row:" in source_ref:
        return []
    out: list[ExtractedTable] = []
    for idx, tbl in enumerate(record.tables or []):
        if not isinstance(tbl, dict):
            continue
        if "columns" not in tbl and "rows" not in tbl:
            continue
        ref = f"{record.attachment_id}#table{idx}"
        if source_ref == ref or source_ref.startswith(record.attachment_id):
            out.append(
                ExtractedTable(
                    source_ref=ref,
                    title=tbl.get("title"),
                    columns=list(tbl.get("columns") or []),
                    rows=[list(r) for r in tbl.get("rows") or []],
                ),
            )
    return out


def _sheet_slices(record) -> list[tuple[str, str]]:
    slices: list[tuple[str, str]] = []
    for sheet in record.raw_sheets or []:
        name = sheet.get("sheet") if isinstance(sheet, dict) else sheet.sheet
        rows = sheet.get("rows") if isinstance(sheet, dict) else sheet.rows
        lines = ["\t".join(str(c) for c in row) for row in rows[:40]]
        text = f"시트: {name}\n" + "\n".join(lines)
        ref = f"{record.attachment_id}#sheet:{name}"
        slices.append((ref, text))
    for idx, tbl in enumerate(record.tables or []):
        if isinstance(tbl, dict):
            title = tbl.get("title") or f"table{idx}"
            cols = tbl.get("columns") or []
            rows = tbl.get("rows") or []
        else:
            title = tbl.title or f"table{idx}"
            cols = tbl.columns
            rows = tbl.rows
        lines = [" | ".join(cols)] + [" | ".join(str(c) for c in r) for r in rows[:20]]
        ref = f"{record.attachment_id}#table{idx}"
        slices.append((ref, f"{title}\n" + "\n".join(lines)))
    return slices


_MAX_CODES_PER_SLICE = 24


def _roster_set(rnr_path: str) -> set[str]:
    return set(load_qa_damdang_roster(rnr_path))


def _filter_damdangs(
    damdangs: list[str],
    *,
    roster: set[str],
    filename_hints: set[str],
) -> list[str]:
    out: list[str] = []
    for d in damdangs:
        if d not in roster or d == MANAGER_KEY:
            continue
        if filename_hints and d not in filename_hints and d != FALLBACK_KEY:
            continue
        if d not in out:
            out.append(d)
    return out


def records_to_wiki_cards(
    norm_records: list[NormalizedRecord],
    *,
    post_id: str,
    post_title: str,
    posted_date: date,
    record,
    lookup: dict[str, tuple[str, ...]],
    roster: set[str],
    vlm_index: dict[str, ImageNote] | None = None,
    stats: BuildStats | None = None,
) -> list[WikiCard]:
    """Convert enriched NormalizedRecords to WikiCards."""
    vlm_index = vlm_index or {}
    cards: list[WikiCard] = []
    filename = record.filename

    for nrec in norm_records:
        source_ref = nrec.provenance.source_ref
        vlm = vlm_index.get(source_ref)
        vlm_text = vlm.description if vlm else ""
        effective_text = (nrec.body or "").strip() or vlm_text
        is_promo_excel = _is_promo_excel_slice(record.kind, filename, effective_text)
        is_fallback = nrec.review_flag in ("xlsx_fallback", "fallback_content")

        if is_fallback and _skip_noisy_slice(effective_text, source_ref, filename) and not is_promo_excel:
            continue

        damdangs = list(nrec.damdangs) if nrec.damdangs else (
            [nrec.damdang] if nrec.damdang else []
        )
        if not damdangs:
            continue

        codes = list(nrec.product_codes)
        body = effective_text.strip()
        if len(body) > _MAX_BODY:
            body = body[:_MAX_BODY] + "\n…(생략)"

        tables = _tables_for_ref(record, source_ref)
        headline = nrec.title or _headline(
            effective_text, post_title, source_ref=source_ref, filename=filename,
        )
        if stats:
            stats.slices_scanned += 1
            if codes:
                stats.slices_with_codes += 1

        card_temporal = TemporalMeta.from_dict(nrec.temporal) if nrec.temporal else TemporalMeta()

        for damdang in damdangs:
            codes_for_d = (
                product_codes_for_damdang(codes, damdang, lookup) if codes else list(codes)
            )
            if codes and not codes_for_d and product_damdang_for_codes(codes, lookup):
                if damdang != FALLBACK_KEY:
                    continue
            cards.append(
                WikiCard(
                    damdang=damdang,
                    post_id=post_id,
                    post_title=post_title,
                    posted_date=posted_date,
                    source_ref=source_ref,
                    attachment_name=filename,
                    product_codes=codes_for_d or list(codes),
                    headline=headline,
                    body=body,
                    vlm=vlm,
                    tables=tables,
                    temporal=card_temporal,
                ),
            )
    return cards


def _build_cards_from_normalized(
    norm_records: list[NormalizedRecord],
    *,
    post_id: str,
    post_title: str,
    posted_date: date,
    record,
    lookup: dict[str, tuple[str, ...]],
    roster: set[str],
    vlm_index: dict[str, ImageNote] | None,
    stats: BuildStats | None,
) -> list[WikiCard]:
    if not norm_records:
        return []
    post_meta = PostMeta(
        post_id=post_id,
        post_title=post_title,
        posted_date=posted_date,
        filename=record.filename,
        record_kind=record.kind,
    )
    enriched = enrich_records(
        norm_records,
        lookup=lookup,
        roster=roster,
        post_meta=post_meta,
        vlm_index=vlm_index,
        tables_for_ref=_tables_for_ref,
        record=record,
    )
    return records_to_wiki_cards(
        enriched,
        post_id=post_id,
        post_title=post_title,
        posted_date=posted_date,
        record=record,
        lookup=lookup,
        roster=roster,
        vlm_index=vlm_index,
        stats=stats,
    )


def collect_cards(
    as_of: date,
    *,
    data_dir: str,
    lookup: dict[str, tuple[str, ...]],
    vlm_index: dict[str, ImageNote] | None = None,
    rnr_path: str = "data/rnr.txt",
) -> tuple[list[WikiCard], BuildStats]:
    raw_base = Path(data_dir) / "raw"
    parsed_root = Path(data_dir) / "parsed"
    posts = {p.id: p for p in board.load_posts_backfill(str(raw_base), as_of)}
    store = ParsedAttachmentStore(parsed_root)
    vlm_index = vlm_index or {}
    roster = _roster_set(rnr_path)

    stats = BuildStats()
    cards: list[WikiCard] = []
    all_codes: list[str] = []
    excel_handled: set[str] = set()

    for post_id, post in posts.items():
        meta_path = parsed_root / post_id / "meta.json"
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        stats.posts_scanned += 1
        post_title = meta.get("title") or post.title

        for att_key in meta.get("records", []):
            record = store.load_record(post_id, att_key)
            if record is None or record.error:
                continue

            if record.kind == "excel":
                norm_records = parse_xlsx_from_record(
                    record, post_id, data_dir=data_dir,
                )
                if norm_records:
                    excel_handled.add(record.attachment_id)
                    row_cards = _build_cards_from_normalized(
                        norm_records,
                        post_id=post_id,
                        post_title=post_title,
                        posted_date=post.posted_date,
                        record=record,
                        lookup=lookup,
                        roster=roster,
                        vlm_index=vlm_index,
                        stats=stats,
                    )
                    cards.extend(row_cards)
                    for c in row_cards:
                        all_codes.extend(c.product_codes)
                    continue

            if record.kind == "pptx":
                norm_records = parse_pptx_from_record(record, post_id)
                if norm_records:
                    pptx_cards = _build_cards_from_normalized(
                        norm_records,
                        post_id=post_id,
                        post_title=post_title,
                        posted_date=post.posted_date,
                        record=record,
                        lookup=lookup,
                        roster=roster,
                        vlm_index=vlm_index,
                        stats=stats,
                    )
                    cards.extend(pptx_cards)
                    for c in pptx_cards:
                        all_codes.extend(c.product_codes)
                    continue

            if record.kind == "pdf":
                norm_records = parse_pdf_from_record(record, post_id)
                if norm_records:
                    pdf_cards = _build_cards_from_normalized(
                        norm_records,
                        post_id=post_id,
                        post_title=post_title,
                        posted_date=post.posted_date,
                        record=record,
                        lookup=lookup,
                        roster=roster,
                        vlm_index=vlm_index,
                        stats=stats,
                    )
                    cards.extend(pdf_cards)
                    for c in pdf_cards:
                        all_codes.extend(c.product_codes)
                    continue

            slices = _iter_slices(record)
            if record.kind == "excel" and not slices:
                slices = _sheet_slices(record)

            for source_ref, text in slices:
                stats.slices_scanned += 1
                vlm = vlm_index.get(source_ref)
                vlm_text = vlm.description if vlm else ""
                effective_text = (text or "").strip() or vlm_text
                is_promo_excel = _is_promo_excel_slice(
                    record.kind, record.filename, effective_text,
                )
                if _skip_noisy_slice(effective_text, source_ref, record.filename) and not is_promo_excel:
                    continue
                codes = extract_prd_codes(effective_text, vlm_text)
                if not codes:
                    codes = extract_model_skus(effective_text)
                post_title = meta.get("title") or post.title
                blob = f"{post_title}\n{record.filename}\n{effective_text}"

                damdangs: list[str] = []
                if codes and len(codes) <= _MAX_CODES_PER_SLICE:
                    stats.slices_with_codes += 1
                    all_codes.extend(codes)
                    damdangs = _filter_damdangs(
                        product_damdang_for_codes(codes, lookup),
                        roster=roster,
                        filename_hints=_damdang_hints_from_filename(record.filename),
                    )
                    if not damdangs:
                        damdangs = infer_damdangs_from_text(blob, roster)
                        damdangs = [d for d in damdangs if d in roster and d != MANAGER_KEY]
                elif is_promo_excel:
                    damdangs = infer_damdangs_from_text(blob, roster)
                    file_hints = _damdang_hints_from_filename(record.filename)
                    for d in file_hints:
                        if d in roster and d not in damdangs:
                            damdangs.append(d)
                    damdangs = [d for d in damdangs if d in roster and d != MANAGER_KEY]
                    if damdangs:
                        stats.slices_with_codes += 1
                        all_codes.extend(codes[:_MAX_CODES_PER_SLICE])
                elif len(effective_text.strip()) >= _MIN_POST_BODY_LEN and vlm_text:
                    damdangs = infer_damdangs_from_text(blob, roster)
                    damdangs = [d for d in damdangs if d in roster and d != MANAGER_KEY]
                else:
                    continue

                if not damdangs:
                    continue

                body = effective_text.strip()
                if len(body) > _MAX_BODY:
                    body = body[:_MAX_BODY] + "\n…(생략)"

                tables = _tables_for_ref(record, source_ref)
                headline = _headline(
                    effective_text, post_title, source_ref=source_ref, filename=record.filename,
                )
                for damdang in damdangs:
                    codes_for_d = (
                        product_codes_for_damdang(codes, damdang, lookup) if codes else list(codes)
                    )
                    if codes and not codes_for_d and product_damdang_for_codes(codes, lookup):
                        continue
                    card_temporal = extract_temporal_meta(
                        text=body or effective_text,
                        posted_date=post.posted_date,
                        title=headline or post_title,
                        filename=record.filename,
                        damdang=damdang,
                        tables=tables,
                    )
                    cards.append(
                        WikiCard(
                            damdang=damdang,
                            post_id=post_id,
                            post_title=post_title,
                            posted_date=post.posted_date,
                            source_ref=source_ref,
                            attachment_name=record.filename,
                            product_codes=codes_for_d or list(codes),
                            headline=headline,
                            body=body,
                            vlm=vlm,
                            tables=tables,
                            temporal=card_temporal,
                        ),
                    )

    post_body = collect_post_body_cards(
        posts,
        lookup=lookup,
        roster=roster,
    )
    stats.post_body_cards = len(post_body)
    cards.extend(post_body)
    for c in post_body:
        all_codes.extend(c.product_codes)

    link_card_versions(cards)

    enrich_cards_keywords(cards)

    stats.unique_codes = len(set(all_codes))
    stats.codes_resolved = sum(1 for c in set(all_codes) if lookup.get(c))
    stats.cards_written = len(cards)
    return cards, stats


def group_cards(
    cards: list[WikiCard],
    *,
    rnr_path: str = "data/rnr.txt",
) -> dict[str, list[WikiCard]]:
    buckets: dict[str, list[WikiCard]] = {}
    for card in cards:
        buckets.setdefault(card.damdang, []).append(card)
    order = load_rnr_damdang_roster(rnr_path)
    extras = sorted(k for k in buckets if k not in order)
    order = order + extras
    all_cards = list(cards)
    result: dict[str, list[WikiCard]] = {MANAGER_KEY: all_cards}
    for key in order:
        if key == MANAGER_KEY:
            continue
        result[key] = buckets.get(key, [])
    if FALLBACK_KEY not in result:
        result[FALLBACK_KEY] = []
    return {k: result.get(k, []) for k in order if k in result or k == FALLBACK_KEY}


def _render_card_md(card: WikiCard) -> list[str]:
    lines = [
        f"#### {card.headline}",
        f"- **게시물**: {card.post_title}",
        f"- **작성일**: {card.posted_date}",
        f"- **분류담당**: {card.damdang}",
    ]
    tm = card.temporal
    if tm.notice_kind.value != "기타":
        lines.append(f"- **유형**: {tm.notice_kind.value}")
    if tm.valid_from or tm.valid_to:
        lines.append(f"- **적용기간**: {tm.valid_from or '?'} ~ {tm.valid_to or '?'}")
    if len(tm.event_windows) > 1:
        parts = [
            f"{a}~{b or '?'}" for a, b in tm.event_windows[:6]
        ]
        lines.append(f"- **행사구간**: {', '.join(parts)}")
    if tm.effective_date:
        lines.append(f"- **시행일**: {tm.effective_date}")
    lines.extend([
        f"- **상품코드**: {', '.join(card.product_codes[:12])}"
        + (" …" if len(card.product_codes) > 12 else ""),
        f"- **첨부**: {card.attachment_name}",
        f"- **출처**: `{card.source_ref}`",
        "",
    ])
    if card.body:
        lines.append(card.body)
        lines.append("")
    if card.vlm:
        lines.append("**VLM**")
        lines.append(f"- [{card.vlm.kind}] {card.vlm.description[:400]}")
        lines.append("")
    if card.tables:
        lines.append("**표**")
        for tbl in card.tables[:2]:
            title = tbl.title or tbl.source_ref
            lines.append(f"- {title}: {len(tbl.columns)}열 × {len(tbl.rows)}행")
        lines.append("")
    return lines


def export_cards(
    cards: list[WikiCard],
    out_dir: str | Path,
    as_of: date,
    *,
    stats: BuildStats | None = None,
    rnr_path: str = "data/rnr.txt",
) -> dict[str, Path]:
    out = Path(out_dir) / as_of.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    damdang_dir = out / "by_damdang"
    damdang_dir.mkdir(exist_ok=True)
    for old in damdang_dir.glob("*.md"):
        old.unlink()

    grouped = group_cards(cards, rnr_path=rnr_path)
    payload_damdang: dict = {}
    md_lines = [
        f"# llmwiki — {as_of.isoformat()}",
        "",
        f"parsed/VLM 슬라이스 **{stats.slices_scanned if stats else '?'}**개 중 "
        f"상품코드 매칭 **{stats.cards_written if stats else len(cards)}** 카드 "
        f"(HISIS→cat.txt 담당 라우팅)",
        "",
    ]

    for damdang, group in grouped.items():
        if damdang == FALLBACK_KEY and not group:
            continue
        if damdang == MANAGER_KEY:
            payload_damdang[damdang] = {"card_count": len(group)}
            continue
        section = [f"## {damdang} ({len(group)})", ""]
        if not group:
            section.append("(해당 카드 없음)")
            section.append("")
        else:
            by_post: dict[str, list[WikiCard]] = {}
            for c in group:
                by_post.setdefault(c.post_title, []).append(c)
            for post_title in sorted(by_post):
                section.append(f"### {post_title} ({len(by_post[post_title])})")
                section.append("")
                for card in by_post[post_title]:
                    section.extend(_render_card_md(card))

        payload_damdang[damdang] = {
            "card_count": len(group),
            "cards": [c.to_export_dict() for c in group],
        }
        (damdang_dir / f"{damdang}.md").write_text(
            f"# {damdang}\n\n" + "\n".join(section),
            encoding="utf-8",
        )
        md_lines.extend(section)

    payload = {
        "as_of": as_of.isoformat(),
        "grouping": "from_parsed_product_codes",
        "card_count": len(cards),
        "damdang_count": len([d for d, g in grouped.items() if g and d != MANAGER_KEY]),
        "damdang": payload_damdang,
    }
    if stats:
        payload["build"] = {
            "posts_scanned": stats.posts_scanned,
            "slices_scanned": stats.slices_scanned,
            "slices_with_codes": stats.slices_with_codes,
            "unique_codes": stats.unique_codes,
            "codes_resolved": stats.codes_resolved,
        }

    json_path = out / "llmwiki.json"
    with json_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    md_path = out / "llmwiki.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")
    return {"json": json_path, "markdown": md_path, "by_damdang_dir": damdang_dir}


def _collect_all_codes(
    as_of: date,
    *,
    data_dir: str,
    vlm_index: dict[str, ImageNote] | None = None,
) -> list[str]:
    parsed_root = Path(data_dir) / "parsed"
    raw_base = Path(data_dir) / "raw"
    posts = board.load_posts_backfill(str(raw_base), as_of)
    store = ParsedAttachmentStore(parsed_root)
    vlm_index = vlm_index or {}
    codes: list[str] = []

    for post in posts:
        meta_path = parsed_root / post.id / "meta.json"
        if not meta_path.is_file():
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        for att_key in meta.get("records", []):
            record = store.load_record(post.id, att_key)
            if not record or record.error:
                continue
            for source_ref, text in _iter_slices(record):
                vlm = vlm_index.get(source_ref)
                codes.extend(extract_prd_codes(text, vlm.description if vlm else ""))
            if record.kind == "excel":
                for source_ref, text in _sheet_slices(record):
                    codes.extend(extract_prd_codes(text))
    return list(dict.fromkeys(codes))


def build_llmwiki_from_parsed(
    as_of: date,
    *,
    data_dir: str,
    cat_path: str | Path | None = None,
    sql_path: str | Path | None = None,
    cache_path: str | Path | None = None,
    cache_only: bool = False,
    refresh_cache: bool = False,
    vlm_index: dict[str, ImageNote] | None = None,
    rnr_path: str = "data/rnr.txt",
) -> tuple[dict[str, Path], BuildStats]:
    """Greenfield llmwiki: parsed slices → product codes → HISIS/cat → by_damdang."""
    all_codes = _collect_all_codes(as_of, data_dir=data_dir, vlm_index=vlm_index)
    lookup = lookup_damdang_map(
        all_codes,
        cat_path=cat_path,
        sql_path=sql_path,
        cache_path=cache_path,
        cache_only=cache_only,
        refresh=refresh_cache,
    )
    cards, stats = collect_cards(
        as_of, data_dir=data_dir, lookup=lookup, vlm_index=vlm_index, rnr_path=rnr_path,
    )
    paths = export_cards(
        cards, Path(data_dir) / "llmwiki", as_of, stats=stats, rnr_path=rnr_path,
    )
    from store_brief.index.build import build_search_index_for_as_of

    index_meta = build_search_index_for_as_of(cards, data_dir, as_of.isoformat())
    paths["search_index"] = Path(index_meta.path)
    return paths, stats
