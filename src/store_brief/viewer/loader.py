"""Aggregate parsed attachments, raw posts, and llmwiki VLM notes for the viewer."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from store_brief.parse.layout_schema import PageRecord
from store_brief.parse.store import ParsedAttachmentStore, StoredParseRecord
from store_brief.viewer.urls import media_url

_SHEET_MD_HDR = re.compile(r"^###\s+시트:\s*(.+)\s*$", re.MULTILINE)
_PAGE_HDR = re.compile(r"^###\s+p(\d+)\s*$", re.MULTILINE)


@dataclass
class VlmNote:
    source_ref: str
    kind: str
    description: str


@dataclass
class PageView:
    index: int
    ref: str
    text: str
    image_url: str | None
    vlm: VlmNote | None = None


@dataclass
class ExcelSheetView:
    sheet: str
    image_url: str | None
    image_urls: list[str] = field(default_factory=list)
    tables: list[dict] = field(default_factory=list)
    raw_rows: list[list[str]] = field(default_factory=list)
    layout: dict | None = None


@dataclass
class AttachmentView:
    att_key: str
    filename: str
    kind: str
    parse_mode: str
    error: str | None
    view_type: str  # slides | excel | text
    pages: list[PageView] = field(default_factory=list)
    sheets: list[ExcelSheetView] = field(default_factory=list)
    text: str = ""
    attachment_id: str = ""


@dataclass
class PostSummary:
    post_id: str
    title: str
    posted_date: str
    attachment_count: int
    needs_review: bool = False
    kinds: list[str] = field(default_factory=list)


@dataclass
class PostDetail:
    post_id: str
    title: str
    body: str
    posted_date: str
    parsed_at: str
    attachments: list[AttachmentView] = field(default_factory=list)


def _parse_markdown_table(block: str) -> tuple[list[str], list[list[str]]] | None:
    lines = [ln.strip() for ln in block.strip().splitlines() if ln.strip()]
    if len(lines) < 2 or "|" not in lines[0]:
        return None
    header = [c.strip() for c in lines[0].strip("|").split("|")]
    rows: list[list[str]] = []
    for ln in lines[2:]:
        if "|" not in ln:
            break
        rows.append([c.strip() for c in ln.strip("|").split("|")])
    return header, rows


def _sheets_from_markdown(text: str) -> dict[str, list[dict]]:
    """Legacy parse records: extract per-sheet markdown tables from text field."""
    out: dict[str, list[dict]] = {}
    if not text.strip():
        return out
    matches = list(_SHEET_MD_HDR.finditer(text))
    for i, m in enumerate(matches):
        sheet = m.group(1).strip()
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        block = text[start:end]
        parsed = _parse_markdown_table(block)
        if parsed is None:
            continue
        cols, rows = parsed
        out.setdefault(sheet, []).append({
            "sheet": sheet,
            "title": sheet,
            "columns": cols,
            "rows": rows[:50],
            "total_rows": len(rows),
            "truncated": len(rows) > 50,
        })
    return out


_SLIDE_HDR = re.compile(r"^###\s+슬라이드\s+(\d+)\s*$", re.MULTILINE)


def _parse_text_pages(text: str, images: list[dict], att_id: str, kind: str) -> list[PageRecord]:
    """Reconstruct pages from legacy records without pages[]."""
    hdr = _SLIDE_HDR if kind == "pptx" else _PAGE_HDR
    prefix = "#s" if kind == "pptx" else "#p"
    sections: dict[int, str] = {}
    if text.strip():
        matches = list(hdr.finditer(text))
        for i, m in enumerate(matches):
            idx = int(m.group(1))
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
            sections[idx] = text[start:end].strip()

    img_by_idx: dict[int, str] = {}
    for img in images:
        ref = img.get("source_ref", "")
        m = re.search(rf"{re.escape(att_id)}{re.escape(prefix)}(\d+)$", ref)
        if m:
            img_by_idx[int(m.group(1))] = img.get("path", "")

    indices = sorted(set(sections) | set(img_by_idx))
    if not indices and images:
        for img in images:
            ref = img.get("source_ref", "")
            m = re.search(rf"{re.escape(att_id)}{re.escape(prefix)}(\d+)$", ref)
            if m:
                indices.append(int(m.group(1)))
        indices = sorted(set(indices))

    return [
        PageRecord(
            index=idx,
            ref=f"{att_id}{prefix}{idx}",
            text=sections.get(idx, ""),
            image_path=img_by_idx.get(idx),
        )
        for idx in indices
    ]


def _sheet_from_ref(ref: str, att_id: str) -> str:
    prefix = f"{att_id}#"
    if not ref.startswith(prefix):
        return ref
    tail = ref[len(prefix):]
    if "_t" in tail:
        base, suffix = tail.rsplit("_t", 1)
        if suffix.isdigit():
            return base
    return tail


def _tile_index(ref: str, att_id: str) -> int:
    prefix = f"{att_id}#"
    if not ref.startswith(prefix):
        return 0
    tail = ref[len(prefix):]
    if "_t" in tail:
        _, suffix = tail.rsplit("_t", 1)
        if suffix.isdigit():
            return int(suffix)
    return 0


def _trim_grid(rows: list[list[str]], *, max_rows: int = 50, max_cols: int = 30) -> list[list[str]]:
    if not rows:
        return []
    width = min(max((len(r) for r in rows), default=0), max_cols)
    out: list[list[str]] = []
    for row in rows[:max_rows]:
        cells = list(row[:width])
        if len(cells) < width:
            cells.extend([""] * (width - len(cells)))
        out.append(cells)
    return out


def pair_excel(
    post_id: str,
    att_id: str,
    images: list[dict],
    tables: list[dict],
    layout: list[dict],
    raw_sheets: list[dict] | None = None,
    text: str = "",
) -> list[ExcelSheetView]:
    layout_by_sheet = {lay.get("sheet"): lay for lay in layout}
    tables_by_sheet: dict[str, list[dict]] = {}
    for tbl in tables:
        sheet = tbl.get("sheet") or "(unknown)"
        tables_by_sheet.setdefault(sheet, []).append(tbl)
    for sheet, tbls in _sheets_from_markdown(text).items():
        if sheet not in tables_by_sheet:
            tables_by_sheet[sheet] = tbls

    raw_by_sheet: dict[str, list[list[str]]] = {}
    for raw in raw_sheets or []:
        name = raw.get("sheet")
        if name:
            raw_by_sheet[name] = raw.get("rows", [])

    imgs_by_sheet: dict[str, list[tuple[int, str]]] = {}
    for img in images:
        ref = img.get("source_ref", "")
        sheet = _sheet_from_ref(ref, att_id)
        path = img.get("path", "")
        imgs_by_sheet.setdefault(sheet, []).append((_tile_index(ref, att_id), path))

    sheet_names = sorted(
        set(tables_by_sheet) | set(imgs_by_sheet) | set(layout_by_sheet) | set(raw_by_sheet)
    )
    views: list[ExcelSheetView] = []
    for sheet in sheet_names:
        sorted_imgs = sorted(imgs_by_sheet.get(sheet, []), key=lambda x: x[0])
        urls = [media_url(post_id, p) for _, p in sorted_imgs if p]
        urls = [u for u in urls if u]
        views.append(ExcelSheetView(
            sheet=sheet,
            image_url=urls[0] if urls else None,
            image_urls=urls,
            tables=tables_by_sheet.get(sheet, []),
            raw_rows=_trim_grid(raw_by_sheet.get(sheet, [])),
            layout=layout_by_sheet.get(sheet),
        ))
    return views


def enrich_pages(
    post_id: str,
    pages: list[PageRecord],
    vlm_index: dict[str, VlmNote],
) -> list[PageView]:
    result: list[PageView] = []
    for page in pages:
        result.append(PageView(
            index=page.index,
            ref=page.ref,
            text=page.text,
            image_url=media_url(post_id, page.image_path),
            vlm=vlm_index.get(page.ref),
        ))
    return result


def _build_vlm_index(llmwiki_path: Path | None) -> dict[str, VlmNote]:
    if llmwiki_path is None or not llmwiki_path.is_file():
        return {}
    data = json.loads(llmwiki_path.read_text(encoding="utf-8"))
    index: dict[str, VlmNote] = {}
    damdang = data.get("damdang", {})
    for block in damdang.values():
        for theme_events in block.get("themes", {}).values():
            for ev in theme_events:
                for img in ev.get("images", []):
                    ref = img.get("source_ref", "")
                    if ref and ref not in index:
                        index[ref] = VlmNote(
                            source_ref=ref,
                            kind=img.get("kind", ""),
                            description=img.get("description", ""),
                        )
    return index


def _find_llmwiki(data_dir: Path, as_of: str | None) -> Path | None:
    wiki_root = data_dir / "llmwiki"
    if not wiki_root.exists():
        return None
    if as_of:
        candidate = wiki_root / as_of / "llmwiki.json"
        if candidate.is_file():
            return candidate
    dated = sorted(
        (p for p in wiki_root.iterdir() if p.is_dir()),
        key=lambda p: p.name,
        reverse=True,
    )
    for d in dated:
        candidate = d / "llmwiki.json"
        if candidate.is_file():
            return candidate
    return None


def _load_raw_posts(raw_dir: Path) -> dict[str, dict]:
    posts: dict[str, dict] = {}
    if not raw_dir.exists():
        return posts
    for day_dir in raw_dir.iterdir():
        if not day_dir.is_dir():
            continue
        pj = day_dir / "posts.json"
        if not pj.exists():
            continue
        for p in json.loads(pj.read_text(encoding="utf-8")):
            posts[p["id"]] = p
    return posts


class ParseViewerLoader:
    def __init__(
        self,
        data_dir: str | Path,
        *,
        as_of: str | None = None,
    ):
        self.data_dir = Path(data_dir)
        self.parsed_root = self.data_dir / "parsed"
        self.raw_dir = self.data_dir / "raw"
        self.store = ParsedAttachmentStore(self.parsed_root)
        self.raw_posts = _load_raw_posts(self.raw_dir)
        self.vlm_index = _build_vlm_index(_find_llmwiki(self.data_dir, as_of))

    def _record_needs_review(self, rec: StoredParseRecord) -> bool:
        if any(lay.get("needs_review") for lay in rec.layout):
            return True
        if any(tbl.get("needs_review") for tbl in rec.tables):
            return True
        return False

    def _build_attachment_view(self, post_id: str, att_key: str, rec: StoredParseRecord) -> AttachmentView:
        if rec.error:
            return AttachmentView(
                att_key=att_key,
                attachment_id=rec.attachment_id,
                filename=rec.filename,
                kind=rec.kind,
                parse_mode=rec.parse_mode or "",
                error=rec.error,
                view_type="text",
            )

        pages_data = rec.pages
        if not pages_data and rec.kind in ("pptx", "pdf"):
            images_dict = [{"source_ref": i.source_ref, "path": i.path} for i in rec.images]
            legacy_pages = _parse_text_pages(rec.text, images_dict, rec.attachment_id, rec.kind)
            pages_data = [p.to_dict() for p in legacy_pages]

        pages = [PageRecord.from_dict(p) for p in pages_data]

        if rec.kind == "excel":
            images_dict = [{"source_ref": i.source_ref, "path": i.path} for i in rec.images]
            sheets = pair_excel(
                post_id,
                rec.attachment_id,
                images_dict,
                rec.tables,
                rec.layout,
                rec.raw_sheets,
                rec.text,
            )
            return AttachmentView(
                att_key=att_key,
                attachment_id=rec.attachment_id,
                filename=rec.filename,
                kind=rec.kind,
                parse_mode=rec.parse_mode or "",
                error=None,
                view_type="excel",
                sheets=sheets,
                text=rec.text,
            )

        if rec.kind in ("pptx", "pdf") and (pages or rec.images):
            page_views = enrich_pages(post_id, pages, self.vlm_index)
            return AttachmentView(
                att_key=att_key,
                attachment_id=rec.attachment_id,
                filename=rec.filename,
                kind=rec.kind,
                parse_mode=rec.parse_mode or "",
                error=None,
                view_type="slides",
                pages=page_views,
                text=rec.text,
            )

        return AttachmentView(
            att_key=att_key,
            attachment_id=rec.attachment_id,
            filename=rec.filename,
            kind=rec.kind,
            parse_mode=rec.parse_mode or "",
            error=None,
            view_type="text",
            text=rec.text,
        )

    def list_posts(
        self,
        *,
        query: str | None = None,
        kind: str | None = None,
        needs_review: bool | None = None,
    ) -> list[PostSummary]:
        results: list[PostSummary] = []
        q = (query or "").strip().lower()
        check_review = needs_review is not None

        for post_id in self.store.list_post_ids():
            meta_path = self.store.post_dir(post_id) / "meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            title = meta.get("title", post_id)
            if q and q not in title.lower() and q not in post_id.lower():
                continue

            record_index = self.store.ensure_meta_record_index(
                post_id,
                meta,
                check_review=check_review,
            )

            kinds = sorted({v.get("kind", "") for v in record_index.values() if v.get("kind")})
            review = any(v.get("needs_review") for v in record_index.values())

            if kind and kind not in kinds:
                continue
            if needs_review is True and not review:
                continue
            if needs_review is False and review:
                continue

            results.append(PostSummary(
                post_id=post_id,
                title=title,
                posted_date=meta.get("posted_date", ""),
                attachment_count=len(meta.get("records", [])),
                needs_review=review,
                kinds=kinds,
            ))

        results.sort(key=lambda p: (p.posted_date, p.title), reverse=True)
        return results

    def load_post_detail(self, post_id: str) -> PostDetail | None:
        meta_path = self.store.post_dir(post_id) / "meta.json"
        if not meta_path.exists():
            return None
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        raw = self.raw_posts.get(post_id, {})
        attachments: list[AttachmentView] = []
        for att_key in meta.get("records", []):
            rec = self.store.load_record(post_id, att_key)
            if rec is None:
                continue
            attachments.append(self._build_attachment_view(post_id, att_key, rec))

        return PostDetail(
            post_id=post_id,
            title=meta.get("title") or raw.get("title", post_id),
            body=raw.get("body", ""),
            posted_date=meta.get("posted_date", raw.get("posted_date", "")),
            parsed_at=meta.get("parsed_at", ""),
            attachments=attachments,
        )

    def resolve_media_path(self, post_id: str, rel_path: str) -> Path | None:
        base = (self.parsed_root / post_id).resolve()
        target = (base / rel_path).resolve()
        if not str(target).startswith(str(base)):
            return None
        if target.is_file():
            return target
        return None
