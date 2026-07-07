"""Persist deterministic parse results for review before LLM extraction.



Layout:

  data/parsed/{post_id}/meta.json

  data/parsed/{post_id}/{att_key}.json

  data/parsed/{post_id}/images/{att_key}_{ref}.png

"""

from __future__ import annotations



import hashlib

import json

import re

import shutil

from dataclasses import asdict, dataclass, field

from datetime import datetime, timezone

from pathlib import Path



from store_brief.parse.excel_tables import SheetTable

from store_brief.parse.layout_schema import PageRecord, RawSheet, TableLayoutSheet

from store_brief.parse.router import ParsedAttachment





def _utc_now() -> str:

    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()





def _fingerprint(path: Path) -> str:

    st = path.stat()

    return hashlib.sha256(f"{st.st_size}:{st.st_mtime_ns}".encode()).hexdigest()[:16]





def _att_key(attachment_id: str) -> str:

    return hashlib.sha1(attachment_id.encode()).hexdigest()[:12]


_RECORD_KIND_RE = re.compile(rb'"kind"\s*:\s*"([^"]+)"')
_REVIEW_NEEDLE = b'"needs_review": true'


def scan_record_summary(path: Path, *, check_review: bool = True) -> dict:
    """Lightweight metadata for list views — avoids json.loads on huge raw_sheets."""
    if not path.is_file():
        return {"kind": "", "needs_review": False}
    with open(path, "rb") as f:
        head = f.read(8192)
    kind_m = _RECORD_KIND_RE.search(head)
    kind = kind_m.group(1).decode("utf-8") if kind_m else ""
    needs_review = False
    if check_review:
        with open(path, "rb") as f:
            while chunk := f.read(65536):
                if _REVIEW_NEEDLE in chunk:
                    needs_review = True
                    break
    if b'"error"' in head and path.stat().st_size < 32_000:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            return {
                "kind": data.get("kind", kind),
                "needs_review": False,
                "error": bool(data.get("error")),
            }
        except json.JSONDecodeError:
            pass
    return {"kind": kind, "needs_review": needs_review}





def _safe_ref(ref: str) -> str:

    return re.sub(r"[^\w\-]+", "_", ref)[:80]





@dataclass

class StoredImage:

    source_ref: str

    path: str  # relative to post parsed dir





@dataclass

class StoredParseRecord:

    attachment_id: str

    filename: str

    kind: str

    source_path: str

    source_fingerprint: str

    parsed_at: str

    text: str = ""

    images: list[StoredImage] = field(default_factory=list)

    tables: list[dict] = field(default_factory=list)

    raw_sheets: list[dict] = field(default_factory=list)

    layout: list[dict] = field(default_factory=list)

    pages: list[dict] = field(default_factory=list)

    parse_mode: str = ""

    error: str | None = None



    def to_dict(self) -> dict:

        return asdict(self)





@dataclass

class PostParseMeta:

    post_id: str

    title: str

    posted_date: str

    attachment_count: int

    parsed_at: str

    records: list[str] = field(default_factory=list)  # att_key filenames





class ParsedAttachmentStore:

    def __init__(self, root: str | Path):

        self.root = Path(root)



    def post_dir(self, post_id: str) -> Path:

        return self.root / post_id



    def record_path(self, post_id: str, att_key: str) -> Path:

        return self.post_dir(post_id) / f"{att_key}.json"



    def is_fresh(self, post_id: str, attachment_id: str, source_path: Path) -> bool:

        key = _att_key(attachment_id)

        rp = self.record_path(post_id, key)

        if not rp.exists() or not source_path.is_file():

            return False

        rec = json.loads(rp.read_text(encoding="utf-8"))

        return rec.get("source_fingerprint") == _fingerprint(source_path)



    def save(

        self,

        post,

        attachment,

        parsed: ParsedAttachment,

        *,

        workdir: Path | None = None,

    ) -> StoredParseRecord:

        pdir = self.post_dir(post.id)

        img_dir = pdir / "images"

        pdir.mkdir(parents=True, exist_ok=True)

        img_dir.mkdir(exist_ok=True)



        src = Path(attachment.path)

        key = _att_key(attachment.id)

        stored_images: list[StoredImage] = []



        for img_path, ref in parsed.image_paths:

            src_img = Path(img_path)

            if not src_img.is_file():

                continue

            dest_name = f"{key}_{_safe_ref(ref)}{src_img.suffix or '.png'}"

            dest = img_dir / dest_name

            shutil.copy2(src_img, dest)

            stored_images.append(StoredImage(

                source_ref=ref,

                path=str(dest.relative_to(pdir)).replace("\\", "/"),

            ))

        ref_to_stored = {img.source_ref: img.path for img in stored_images}

        stored_pages: list[dict] = []
        for page in parsed.pages:
            stored_pages.append(PageRecord(
                index=page.index,
                ref=page.ref,
                text=page.text,
                image_path=ref_to_stored.get(page.ref),
            ).to_dict())

        record = StoredParseRecord(

            attachment_id=attachment.id,

            filename=attachment.filename,

            kind=attachment.kind,

            source_path=str(src),

            source_fingerprint=_fingerprint(src) if src.is_file() else "",

            parsed_at=_utc_now(),

            text=parsed.text,

            images=stored_images,

            tables=[t.to_dict() for t in parsed.tables],

            raw_sheets=[r.to_dict() for r in parsed.raw_sheets],

            layout=[lay.to_dict() for lay in parsed.layouts],

            pages=stored_pages,

            parse_mode=parsed.parse_mode or "",

        )

        self.record_path(post.id, key).write_text(

            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),

            encoding="utf-8",

        )

        return record



    def save_error(self, post, attachment, error: str) -> StoredParseRecord:

        pdir = self.post_dir(post.id)

        pdir.mkdir(parents=True, exist_ok=True)

        src = Path(attachment.path)

        key = _att_key(attachment.id)

        record = StoredParseRecord(

            attachment_id=attachment.id,

            filename=attachment.filename,

            kind=attachment.kind,

            source_path=str(src),

            source_fingerprint=_fingerprint(src) if src.is_file() else "",

            parsed_at=_utc_now(),

            error=error,

        )

        self.record_path(post.id, key).write_text(

            json.dumps(record.to_dict(), ensure_ascii=False, indent=2),

            encoding="utf-8",

        )

        return record



    def load_record(self, post_id: str, att_key: str) -> StoredParseRecord | None:

        rp = self.record_path(post_id, att_key)

        if not rp.exists():

            return None

        data = json.loads(rp.read_text(encoding="utf-8"))

        images = [StoredImage(**img) for img in data.get("images", [])]

        return StoredParseRecord(

            attachment_id=data["attachment_id"],

            filename=data["filename"],

            kind=data["kind"],

            source_path=data["source_path"],

            source_fingerprint=data["source_fingerprint"],

            parsed_at=data["parsed_at"],

            text=data.get("text", ""),

            images=images,

            tables=data.get("tables", []),

            raw_sheets=data.get("raw_sheets", []),

            layout=data.get("layout", []),

            pages=data.get("pages", []),

            parse_mode=data.get("parse_mode", ""),

            error=data.get("error"),

        )



    def load_parsed_attachment(self, post_id: str, attachment_id: str) -> ParsedAttachment | None:

        key = _att_key(attachment_id)

        rec = self.load_record(post_id, key)

        if rec is None or rec.error:

            return None

        pdir = self.post_dir(post_id)

        image_paths = [

            (str((pdir / img.path).resolve()), img.source_ref)

            for img in rec.images

        ]

        return ParsedAttachment(

            rec.attachment_id,

            text=rec.text,

            image_paths=image_paths,

            tables=[SheetTable(**t) for t in rec.tables],

            raw_sheets=[RawSheet.from_dict(r) for r in rec.raw_sheets],

            layouts=[TableLayoutSheet.from_dict(lay) for lay in rec.layout],

            pages=[PageRecord.from_dict(p) for p in rec.pages],

            parse_mode=rec.parse_mode,

        )



    def build_record_index(
        self,
        post_id: str,
        att_keys: list[str],
        *,
        check_review: bool = True,
    ) -> dict[str, dict]:
        index: dict[str, dict] = {}
        for key in att_keys:
            rp = self.record_path(post_id, key)
            if rp.is_file():
                index[key] = scan_record_summary(rp, check_review=check_review)
        return index

    def ensure_meta_record_index(
        self,
        post_id: str,
        meta: dict,
        *,
        check_review: bool = True,
    ) -> dict[str, dict]:
        keys = meta.get("records", [])
        index = meta.get("record_index")
        if index is not None and set(index) >= set(keys):
            return index
        index = self.build_record_index(post_id, keys, check_review=check_review)
        meta = {**meta, "record_index": index}
        (self.post_dir(post_id) / "meta.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return index



    def update_meta(self, post, record_keys: list[str]) -> None:

        meta_path = self.post_dir(post.id) / "meta.json"
        existing: dict = {}
        if meta_path.exists():
            existing = json.loads(meta_path.read_text(encoding="utf-8"))

        sorted_keys = sorted(record_keys)
        record_index = self.build_record_index(post.id, sorted_keys)

        meta = {
            **asdict(PostParseMeta(
                post_id=post.id,
                title=post.title,
                posted_date=post.posted_date.isoformat(),
                attachment_count=len(getattr(post, "attachments", None) or sorted_keys),
                parsed_at=_utc_now(),
                records=sorted_keys,
            )),
            "record_index": record_index,
        }

        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )



    def list_post_ids(self) -> list[str]:

        if not self.root.exists():

            return []

        return sorted(

            p.name for p in self.root.iterdir()

            if p.is_dir() and not p.name.startswith("_")

        )





def export_review_markdown(store: ParsedAttachmentStore, out_dir: str | Path) -> Path:

    """Write human-readable review files under data/parsed/_review/."""

    out = Path(out_dir)

    out.mkdir(parents=True, exist_ok=True)

    index_lines = ["# Parsed attachments — review", ""]



    for post_id in store.list_post_ids():

        meta_path = store.post_dir(post_id) / "meta.json"

        if not meta_path.exists():

            continue

        meta = json.loads(meta_path.read_text(encoding="utf-8"))

        lines = [

            f"# {meta['title']}",

            "",

            f"- **post_id**: `{post_id}`",

            f"- **posted_date**: {meta['posted_date']}",

            f"- **parsed_at**: {meta['parsed_at']}",

            "",

        ]

        for att_key in meta.get("records", []):

            rec = store.load_record(post_id, att_key)

            if rec is None:

                continue

            lines.append(f"## {rec.filename} (`{rec.kind}`)")

            lines.append("")

            if rec.error:

                lines.append(f"**ERROR**: {rec.error}")

                lines.append("")

                continue

            lines.append(f"- parse_mode: `{rec.parse_mode or '-'}`")

            lines.append(f"- text: **{len(rec.text)}** chars")

            lines.append(f"- images: **{len(rec.images)}**")

            lines.append(f"- tables: **{len(rec.tables)}**")

            lines.append(f"- raw_sheets: **{len(rec.raw_sheets)}**")

            lines.append(f"- pages: **{len(rec.pages)}**")

            lines.append("")

            if rec.layout:

                for lay in rec.layout:

                    flag = " **needs_review**" if lay.get("needs_review") else ""

                    lines.append(

                        f"- layout `{lay.get('sheet')}` — "

                        f"{len(lay.get('regions', []))} region(s), "

                        f"confidence={lay.get('confidence', 0)}{flag}"

                    )

                lines.append("")

            if rec.tables:

                lines.append("### Tables")

                lines.append("")

                for i, table in enumerate(rec.tables, 1):

                    title = table.get("title") or table.get("sheet", f"table_{i}")

                    cols = table.get("columns", [])

                    row_count = len(table.get("rows", []))

                    lines.append(f"- **{title}** — {row_count} rows × {len(cols)} cols")

                lines.append("")

            if rec.text.strip():

                lines.append("### Text")

                lines.append("")

                lines.append("```")

                preview = rec.text if len(rec.text) <= 8000 else rec.text[:8000] + "\n…(truncated)"

                lines.append(preview)

                lines.append("```")

                lines.append("")

            if rec.images:

                lines.append("### Images (VLM input)")

                lines.append("")

                for img in rec.images:

                    lines.append(f"- `{img.source_ref}` → `{img.path}`")

                lines.append("")



        post_md = out / f"{post_id}.md"

        post_md.write_text("\n".join(lines), encoding="utf-8")

        index_lines.append(

            f"- [{meta['title']}]({post_id}.md) — {meta['posted_date']}, "

            f"{len(meta.get('records', []))} attachment(s)"

        )



    index_path = out / "index.md"

    index_path.write_text("\n".join(index_lines) + "\n", encoding="utf-8")

    return index_path


