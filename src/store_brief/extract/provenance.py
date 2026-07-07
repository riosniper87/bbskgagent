"""Event provenance: scope attachments to the right event and fix wrong post attribution."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field

from store_brief.extract.schema import Event, ExtractedEventDraft, ExtractedTable, ImageNote
from store_brief.hisis.prd_codes import extract_prd_codes
from store_brief.parse.router import ParsedAttachment

_SLIDE_SPLIT = re.compile(r"(?=###\s*슬라이드\s*\d+)", re.MULTILINE)
_TITLE_NOISE = re.compile(r"[\[\(（][^\]\)）]*[\]\)）]")
_MIN_KEYWORD_LEN = 2


def event_id(source_post_id: str, title: str) -> str:
    return hashlib.sha1(f"{source_post_id}|{title}".encode()).hexdigest()[:16]


def normalize_title(title: str) -> str:
    t = _TITLE_NOISE.sub("", title)
    t = re.sub(r"\s+", " ", t).strip().lower()
    return t


def keyword_set(text: str) -> set[str]:
    if not text:
        return set()
    codes = set(extract_prd_codes(text))
    korean = {w for w in re.findall(r"[가-힣]{2,}", text) if len(w) >= _MIN_KEYWORD_LEN}
    latin = {w.lower() for w in re.findall(r"[A-Za-z]{3,}", text)}
    stop = {"안내", "공지", "가이드", "운영", "이벤트", "판촉", "필수", "전점", "매장", "isp", "pb"}
    return (codes | korean | latin) - stop


def title_anchors(title: str) -> list[str]:
    normalized = normalize_title(title)
    return [
        w for w in re.findall(r"[가-힣]{2,}", normalized)
        if w not in {"안내", "공지", "가이드", "운영", "이벤트", "판촉", "필수", "전점", "매장"}
    ]


def title_anchor_fit(title: str, corpus: PostCorpus) -> float:
    """How many title anchor words literally appear in the post corpus."""
    anchors = title_anchors(title)
    if not anchors:
        return 1.0
    blob = corpus.full_text()
    hits = sum(1 for word in anchors if word in blob)
    return hits / len(anchors)


@dataclass
class TextSection:
    source_ref: str
    text: str


@dataclass
class PostCorpus:
    post_id: str
    title: str
    body: str
    sections: list[TextSection] = field(default_factory=list)

    def full_text(self) -> str:
        parts = [self.title, self.body]
        parts.extend(s.text for s in self.sections)
        return "\n".join(parts)


def _split_attachment_text(attachment_id: str, text: str) -> list[TextSection]:
    if not text.strip():
        return []
    blocks = _SLIDE_SPLIT.split(text)
    if len(blocks) <= 1:
        return [TextSection(attachment_id, text)]
    sections: list[TextSection] = []
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        m = re.search(r"###\s*슬라이드\s*(\d+)", block)
        ref = f"{attachment_id}#s{m.group(1)}" if m else attachment_id
        sections.append(TextSection(ref, block))
    return sections


def build_post_corpus(post, parsed_attachments: list[ParsedAttachment]) -> PostCorpus:
    sections: list[TextSection] = []
    for pa in parsed_attachments:
        if pa.pages:
            for page in pa.pages:
                sections.append(TextSection(page.ref, page.text or ""))
        else:
            sections.extend(_split_attachment_text(pa.attachment_id, pa.text))
    return PostCorpus(
        post_id=post.id,
        title=post.title,
        body=post.body,
        sections=sections,
    )


def fit_score(keywords: set[str], corpus: PostCorpus) -> float:
    if not keywords:
        return 0.0
    corpus_keywords = keyword_set(corpus.full_text())
    hits = keywords & corpus_keywords
    if hits:
        return len(hits) / len(keywords)
    # Phrase-level fallback for short titles (e.g. "종이 줄자")
    title_blob = corpus.full_text()
    phrase_hits = sum(1 for kw in keywords if kw in title_blob)
    return phrase_hits / len(keywords)


def _ref_matches(source_ref: str, matched_refs: set[str]) -> bool:
    if not matched_refs:
        return False
    base = source_ref.split("#", 1)[0]
    for m in matched_refs:
        mbase = m.split("#", 1)[0]
        if source_ref == m or source_ref.startswith(m) or m.startswith(source_ref):
            return True
        if base == mbase:
            return True
    return False


def match_sections(keywords: set[str], corpus: PostCorpus, *, min_ratio: float = 0.25) -> set[str]:
    matched: set[str] = set()
    for section in corpus.sections:
        section_kw = keyword_set(section.text)
        if not section_kw:
            continue
        ratio = len(keywords & section_kw) / max(len(keywords), 1)
        phrase_hit = any(kw in section.text for kw in keywords if len(kw) >= 3)
        if ratio >= min_ratio or (phrase_hit and ratio > 0):
            matched.add(section.source_ref)
    return matched


def scope_payload(
    event: Event,
    *,
    post_id: str,
    matched_refs: set[str],
    parsed_attachments: list[ParsedAttachment],
) -> None:
    """Keep only images/tables/refs from this post and matching sections."""
    prefix = f"{post_id}_"

    def belongs(ref: str) -> bool:
        if not ref.startswith(post_id) and not ref.startswith(prefix):
            return False
        return _ref_matches(ref, matched_refs) if matched_refs else True

    event.images = [img for img in event.images if belongs(img.source_ref)]
    event.tables = [tbl for tbl in event.tables if belongs(tbl.source_ref)]
    event.attachment_refs = sorted({
        ref for ref in event.attachment_refs if belongs(ref)
    } | {img.source_ref for img in event.images} | {tbl.source_ref for tbl in event.tables})

    if not event.tables:
        for pa in parsed_attachments:
            for idx, table in enumerate(pa.tables or []):
                ref = f"{pa.attachment_id}#table{idx}"
                if belongs(ref):
                    event.tables.append(
                        ExtractedTable(
                            source_ref=ref,
                            title=table.title,
                            columns=list(table.columns),
                            rows=[list(row) for row in table.rows],
                        ),
                    )


def match_refs_for_draft(
    draft: ExtractedEventDraft,
    parsed_attachments: list[ParsedAttachment],
    notes: list[ImageNote],
    tables: list[ExtractedTable],
    *,
    post_id: str,
) -> set[str]:
    keywords = keyword_set(f"{draft.title}\n{draft.summary}")
    corpus = PostCorpus(
        post_id=post_id,
        title="",
        body="",
        sections=[
            *(
                TextSection(page.ref, page.text or "")
                for pa in parsed_attachments
                for page in (pa.pages or [])
            ),
            *(
                sec
                for pa in parsed_attachments
                for sec in _split_attachment_text(pa.attachment_id, pa.text)
            ),
        ],
    )
    matched = match_sections(keywords, corpus)
    if not matched and keywords:
        for note in notes:
            if keyword_set(note.description) & keywords:
                matched.add(note.source_ref)
        for table in tables:
            blob = " ".join(table.columns) + " ".join(" ".join(r) for r in table.rows)
            if keyword_set(blob) & keywords:
                matched.add(table.source_ref)
    if not matched:
        for pa in parsed_attachments:
            matched.add(pa.attachment_id)
    return matched


def _titles_similar(a: str, b: str) -> bool:
    ka, kb = keyword_set(a), keyword_set(b)
    if not ka or not kb:
        return False
    return len(ka & kb) / min(len(ka), len(kb)) >= 0.55


@dataclass
class SanitizeStats:
    input_count: int = 0
    kept_count: int = 0
    dropped_count: int = 0
    reassigned_count: int = 0
    deduped_count: int = 0
    rescoped_count: int = 0


def _event_quality(event: Event, corpus: PostCorpus) -> tuple:
    keywords = keyword_set(f"{event.title}\n{event.summary}")
    prefix = event.source_post_id
    refs_ok = sum(
        1 for ref in event.attachment_refs
        if ref.startswith(prefix) or ref.startswith(f"{prefix}_")
    )
    return (title_anchor_fit(event.title, corpus), fit_score(keywords, corpus), refs_ok, len(event.attachment_refs))


def sanitize_post_events(
    events: list[Event],
    post,
    parsed_attachments: list[ParsedAttachment],
    *,
    all_corpora: dict[str, PostCorpus] | None = None,
    parsed_by_post: dict[str, list[ParsedAttachment]] | None = None,
) -> tuple[list[Event], SanitizeStats]:
    """Fix provenance for events extracted from a single post."""
    stats = SanitizeStats(input_count=len(events))
    corpus = build_post_corpus(post, parsed_attachments)
    corpora = all_corpora or {post.id: corpus}
    parsed_map = parsed_by_post or {post.id: parsed_attachments}
    cleaned: list[Event] = []

    for event in events:
        keywords = keyword_set(f"{event.title}\n{event.summary}")
        source_fit = fit_score(keywords, corpus)
        source_anchor = title_anchor_fit(event.title, corpus)
        target_post = post.id
        target_corpus = corpus
        target_parsed = parsed_attachments
        best_fit = source_fit
        best_anchor = source_anchor

        needs_better_post = source_anchor < 0.5 or source_fit < 0.35
        if all_corpora and needs_better_post:
            for pid, other in all_corpora.items():
                if pid == post.id:
                    continue
                score = fit_score(keywords, other)
                anchor = title_anchor_fit(event.title, other)
                if anchor > best_anchor + 0.2 or (
                    anchor >= best_anchor and score > best_fit + 0.12
                ):
                    best_fit = score
                    best_anchor = anchor
                    target_post = pid
                    target_corpus = other
                    target_parsed = parsed_map.get(pid, [])

        if keywords and best_anchor < 0.34 and best_fit < 0.25:
            stats.dropped_count += 1
            continue

        if target_post != event.source_post_id:
            event.source_post_id = target_post
            stats.reassigned_count += 1

        matched = match_sections(keywords, target_corpus)
        if not matched and keywords:
            matched = {s.source_ref for s in target_corpus.sections[:1]} if target_corpus.sections else set()

        scope_payload(
            event,
            post_id=target_post,
            matched_refs=matched,
            parsed_attachments=target_parsed,
        )
        stats.rescoped_count += 1

        new_id = event_id(event.source_post_id, event.title)
        if new_id != event.id:
            event.id = new_id
        cleaned.append(event)

    stats.kept_count = len(cleaned)
    return cleaned, stats


def dedupe_events(
    events: list[Event],
    corpora: dict[str, PostCorpus],
) -> tuple[list[Event], int]:
    """Drop near-duplicate events, keeping the best-provenance copy."""
    if len(events) < 2:
        return events, 0

    groups: list[list[Event]] = []
    for event in events:
        placed = False
        for group in groups:
            if _titles_similar(event.title, group[0].title):
                group.append(event)
                placed = True
                break
        if not placed:
            groups.append([event])

    kept: list[Event] = []
    dropped = 0
    for group in groups:
        if len(group) == 1:
            kept.append(group[0])
            continue
        posts = {e.source_post_id for e in group}
        if len(posts) == 1:
            kept.extend(group)
            continue
        best = max(
            group,
            key=lambda e: _event_quality(e, corpora.get(e.source_post_id, PostCorpus(e.source_post_id, "", ""))),
        )
        kept.append(best)
        dropped += len(group) - 1
    return kept, dropped


def sanitize_all_events(
    events: list[Event],
    corpora: dict[str, PostCorpus],
    parsed_by_post: dict[str, list[ParsedAttachment]],
) -> tuple[list[Event], SanitizeStats]:
    """Re-sanitize persisted events using all post corpora."""
    stats = SanitizeStats(input_count=len(events))
    by_post: dict[str, list[Event]] = {}
    for event in events:
        by_post.setdefault(event.source_post_id, []).append(event)

    cleaned: list[Event] = []
    for post_id, group in by_post.items():
        corpus = corpora.get(post_id)
        if corpus is None:
            cleaned.extend(group)
            continue
        class _Post:
            id = post_id
            title = corpus.title
            body = corpus.body

        fixed, partial = sanitize_post_events(
            group,
            _Post(),
            parsed_by_post.get(post_id, []),
            all_corpora=corpora,
            parsed_by_post=parsed_by_post,
        )
        cleaned.extend(fixed)
        stats.dropped_count += partial.dropped_count
        stats.reassigned_count += partial.reassigned_count
        stats.rescoped_count += partial.rescoped_count

    cleaned, deduped = dedupe_events(cleaned, corpora)
    stats.deduped_count = deduped
    stats.kept_count = len(cleaned)
    stats.dropped_count += deduped
    return cleaned, stats
