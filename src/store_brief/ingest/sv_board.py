"""Normalize SV board zip exports into data/raw/{date}/ layout.

Reads sv게시판.zip (post folders + 게시물출력.pdf) and ingest.zip (decrypted
attachments). Matches attachments by filename, preferring ingest copies.
"""
from __future__ import annotations

import hashlib
import io
import json
import shutil
import zipfile
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from store_brief.parse.board_pdf import parse_board_pdf

BOARD_PDF_NAMES = {"게시물출력.pdf", "게시물 출력.pdf"}
ATTACH_EXTS = {".xlsx", ".xls", ".xlsb", ".csv", ".pptx", ".pdf", ".png", ".jpg", ".jpeg", ".webp"}

_EXT_KIND = {
    ".xlsx": "excel", ".xls": "excel", ".xlsb": "excel", ".csv": "excel",
    ".pptx": "pptx", ".pdf": "pdf",
    ".png": "image", ".jpg": "image", ".jpeg": "image", ".webp": "image",
}


@dataclass
class PrepareStats:
    posts: int = 0
    attachments_total: int = 0
    attachments_from_ingest: int = 0
    attachments_from_sv: int = 0
    attachments_missing: int = 0
    dates: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)


def _open_zip(path: Path) -> zipfile.ZipFile:
    try:
        return zipfile.ZipFile(path, metadata_encoding="cp437")
    except TypeError:
        return zipfile.ZipFile(path)


def _extract_zip(zf: zipfile.ZipFile, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for info in zf.infolist():
        name = info.filename
        if name.endswith("/"):
            (dest / name).mkdir(parents=True, exist_ok=True)
            continue
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        with zf.open(info) as src, open(target, "wb") as dst:
            shutil.copyfileobj(src, dst)


def _is_drm_payload(data: bytes) -> bool:
    return len(data) >= 7 and data[0] == 0x9B and data[1:7] == b"DRMONE"


def _is_valid_attachment_bytes(data: bytes, filename: str) -> bool:
    if not data:
        return False
    if _is_drm_payload(data):
        return False
    ext = Path(filename).suffix.lower()
    if ext in (".xlsx", ".pptx", ".docx", ".xlsm"):
        return zipfile.is_zipfile(io.BytesIO(data))
    if ext == ".xlsb":
        return data[:4] == b"\xd0\xcf\x11\xe0" or zipfile.is_zipfile(io.BytesIO(data))
    if ext == ".xls":
        return data[:4] == b"\xd0\xcf\x11\xe0"
    if ext == ".pdf":
        return data[:4] == b"%PDF"
    if ext == ".csv":
        return True
    if ext in (".png", ".jpg", ".jpeg", ".webp"):
        return True
    return False


def _is_valid_attachment_file(path: Path) -> bool:
    if not path.is_file():
        return False
    return _is_valid_attachment_bytes(path.read_bytes(), path.name)


def build_ingest_index_from_zip(ingest_zip: Path, cache_dir: Path) -> dict[str, Path]:
    """Map basename -> decrypted file path, read directly from ingest.zip."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    index: dict[str, Path] = {}
    with _open_zip(ingest_zip) as zf:
        for info in sorted(zf.infolist(), key=lambda i: i.filename):
            if info.is_dir():
                continue
            name = Path(info.filename).name
            if Path(name).suffix.lower() not in ATTACH_EXTS:
                continue
            data = zf.read(info.filename)
            if not _is_valid_attachment_bytes(data, name):
                continue
            out = cache_dir / name
            out.write_bytes(data)
            index[name] = out
    return index


def build_ingest_index(ingest_dir: Path) -> dict[str, Path]:
    """Map basename -> path from extracted ingest dir (valid files only)."""
    index: dict[str, Path] = {}
    if not ingest_dir.exists():
        return index
    for p in sorted(ingest_dir.rglob("*")):
        if p.is_file() and _is_valid_attachment_file(p):
            index.setdefault(p.name, p)
    return index


def _extract_from_zip(zip_path: Path, member_name: str, cache_dir: Path) -> Path | None:
    """Extract a single member from download.zip into cache_dir."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    out = cache_dir / Path(member_name).name
    if out.exists():
        return out
    with zipfile.ZipFile(zip_path) as zf:
        for n in zf.namelist():
            if Path(n).name == Path(member_name).name:
                out.write_bytes(zf.read(n))
                return out
    return None


def _resolve_attachment(
    ref: _AttachmentRef,
    ingest_index: dict[str, Path],
    zip_cache: Path,
    stats: PrepareStats,
) -> Path | None:
    fn = ref.filename
    if fn in ingest_index:
        stats.attachments_from_ingest += 1
        return ingest_index[fn]
    # SV / nested zip only if file is not DRM-encrypted
    if ref.sv_path and ref.sv_path.exists() and _is_valid_attachment_file(ref.sv_path):
        stats.attachments_from_sv += 1
        return ref.sv_path
    if ref.zip_path:
        extracted = _extract_from_zip(ref.zip_path, fn, zip_cache / ref.zip_path.parent.name)
        if extracted and _is_valid_attachment_file(extracted):
            stats.attachments_from_sv += 1
            return extracted
    stats.attachments_missing += 1
    return None


@dataclass
class _AttachmentRef:
    filename: str
    sv_path: Path | None = None
    zip_path: Path | None = None  # download.zip if file is inside


def _list_post_attachments(post_dir: Path) -> list[_AttachmentRef]:
    refs: list[_AttachmentRef] = []
    seen: set[str] = set()

    def add(filename: str, sv_path: Path | None = None, zip_path: Path | None = None):
        if filename in seen or Path(filename).suffix.lower() not in ATTACH_EXTS:
            return
        seen.add(filename)
        refs.append(_AttachmentRef(filename, sv_path=sv_path, zip_path=zip_path))

    for p in post_dir.iterdir():
        if not p.is_file():
            continue
        if p.name in BOARD_PDF_NAMES or p.name.lower() == "download.zip":
            continue
        if p.suffix.lower() in ATTACH_EXTS:
            add(p.name, sv_path=p)

    dz = post_dir / "download.zip"
    if dz.exists():
        with zipfile.ZipFile(dz) as inner:
            for n in inner.namelist():
                if n.endswith("/"):
                    continue
                bn = Path(n).name
                sv_file = post_dir / bn
                add(bn, sv_path=sv_file if sv_file.exists() else None, zip_path=dz)
    return refs


def _find_board_pdf(post_dir: Path) -> Path | None:
    for name in BOARD_PDF_NAMES:
        p = post_dir / name
        if p.exists():
            return p
    for p in post_dir.glob("*.pdf"):
        if "출력" in p.stem or p.name.startswith("게시물"):
            return p
    return None


def _copy_or_link(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.resolve() == dst.resolve():
        return
    dst.write_bytes(src.read_bytes())


def _collect_post_dirs(sv_root: Path) -> list[Path]:
    dirs: list[Path] = []
    for p in sv_root.rglob("*"):
        if p.is_dir() and _find_board_pdf(p):
            dirs.append(p)
    # dedupe: keep deepest dirs that have board pdf
    dirs.sort(key=lambda d: len(d.parts), reverse=True)
    seen_parents: set[Path] = set()
    result: list[Path] = []
    for d in dirs:
        if any(d.is_relative_to(s) for s in seen_parents):
            continue
        result.append(d)
        seen_parents.add(d)
    return result


def prepare_raw(
    sv_zip: str | Path,
    ingest_zip: str | Path,
    out_dir: str | Path,
    *,
    staging_dir: str | Path | None = None,
    dry_run: bool = False,
) -> PrepareStats:
    sv_zip, ingest_zip, out_dir = Path(sv_zip), Path(ingest_zip), Path(out_dir)
    staging = Path(staging_dir) if staging_dir else out_dir.parent / "staging"
    sv_staging = staging / "sv"
    ingest_staging = staging / "ingest"

    stats = PrepareStats()

    if not dry_run:
        if sv_staging.exists():
            shutil.rmtree(sv_staging)
        if ingest_staging.exists():
            shutil.rmtree(ingest_staging)
        with _open_zip(sv_zip) as zf:
            _extract_zip(zf, sv_staging)
        with _open_zip(ingest_zip) as zf:
            _extract_zip(zf, ingest_staging)

    ingest_cache = staging / "ingest_cache"
    if ingest_zip.is_file():
        ingest_index = build_ingest_index_from_zip(ingest_zip, ingest_cache)
    else:
        ingest_index = build_ingest_index(ingest_staging)

    # locate sv root (may be nested under sv게시판/)
    sv_root = sv_staging
    children = [p for p in sv_staging.iterdir() if p.is_dir()]
    if len(children) == 1 and not _find_board_pdf(sv_staging):
        sv_root = children[0]

    posts_by_date: dict[str, list[dict]] = defaultdict(list)
    attachment_plan: dict[str, list[tuple[str, Path]]] = defaultdict(list)
    zip_cache = staging / "zip_cache"

    for post_dir in _collect_post_dirs(sv_root):
        pdf = _find_board_pdf(post_dir)
        if not pdf:
            continue
        try:
            draft = parse_board_pdf(pdf, folder_name=post_dir.name)
        except Exception as exc:
            stats.errors.append(f"{post_dir.name}: {exc}")
            continue

        att_refs = _list_post_attachments(post_dir)
        resolved: list[str] = []
        for ref in att_refs:
            src = _resolve_attachment(ref, ingest_index, zip_cache, stats)
            stats.attachments_total += 1
            if src:
                resolved.append(ref.filename)
                if not dry_run:
                    attachment_plan[draft.posted_date.isoformat()].append((ref.filename, src))

        post_rec = {
            "id": draft.id,
            "title": draft.title,
            "body": draft.body,
            "posted_date": draft.posted_date.isoformat(),
            "attachments": resolved,
        }
        if draft.author:
            post_rec["author"] = draft.author

        date_key = draft.posted_date.isoformat()
        posts_by_date[date_key].append(post_rec)
        stats.dates[date_key] = stats.dates.get(date_key, 0) + 1
        stats.posts += 1

    if dry_run:
        return stats

    for date_key, posts in posts_by_date.items():
        day_dir = out_dir / date_key
        att_dir = day_dir / "attachments"
        att_dir.mkdir(parents=True, exist_ok=True)

        for fn, src in attachment_plan.get(date_key, []):
            _copy_or_link(src, att_dir / fn)

        pj = day_dir / "posts.json"
        pj.write_text(json.dumps(posts, ensure_ascii=False, indent=2), encoding="utf-8")

    return stats


def remap_raw_attachments_from_ingest(
    raw_dir: str | Path,
    ingest_zip: str | Path,
    *,
    staging_dir: str | Path | None = None,
) -> dict:
    """Re-copy attachments in existing data/raw from ingest.zip (by filename)."""
    raw_dir, ingest_zip = Path(raw_dir), Path(ingest_zip)
    staging = Path(staging_dir) if staging_dir else raw_dir.parent / "staging"
    ingest_cache = staging / "ingest_cache"
    ingest_index = build_ingest_index_from_zip(ingest_zip, ingest_cache)

    stats = {"days": 0, "copied": 0, "missing_in_ingest": 0, "ingest_index_size": len(ingest_index)}

    for day_dir in sorted(raw_dir.iterdir()):
        if not day_dir.is_dir():
            continue
        pj = day_dir / "posts.json"
        if not pj.exists():
            continue
        posts = json.loads(pj.read_text(encoding="utf-8"))
        att_dir = day_dir / "attachments"
        att_dir.mkdir(exist_ok=True)
        stats["days"] += 1
        for post in posts:
            for fn in post.get("attachments", []):
                src = ingest_index.get(fn)
                if src is None:
                    stats["missing_in_ingest"] += 1
                    continue
                _copy_or_link(src, att_dir / fn)
                stats["copied"] += 1

    return stats
