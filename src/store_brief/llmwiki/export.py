"""Export typed events (llmwiki) — primary grouping by 분류담당, secondary by theme."""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from store_brief.extract.schema import Event
from store_brief.llmwiki.grouping import (
    FALLBACK_KEY,
    group_by_damdang,
    group_by_theme,
    load_damdang_map,
)
from store_brief.llmwiki.product_routing import EnrichStats


def _event_dict(e: Event) -> dict:
    return {
        "id": e.id,
        "type": e.type.value if hasattr(e.type, "value") else e.type,
        "title": e.title,
        "summary": e.summary,
        "theme": e.theme,
        "categories": e.categories,
        "branches": e.branches,
        "valid_from": e.valid_from.isoformat() if e.valid_from else None,
        "valid_to": e.valid_to.isoformat() if e.valid_to else None,
        "effective_date": e.effective_date.isoformat() if e.effective_date else None,
        "source_post_id": e.source_post_id,
        "attachment_refs": e.attachment_refs,
        "tables": [t.model_dump() for t in e.tables],
        "images": [i.model_dump() for i in e.images],
        "raw_excerpt": e.raw_excerpt,
        "product_codes": e.product_codes,
        "damdang_tags": e.damdang_tags,
        "routing_basis": e.routing_basis,
    }


def _render_event_md(e: Event) -> str:
    lines = [
        f"#### {e.title}",
        f"- **유형**: {e.type.value if hasattr(e.type, 'value') else e.type}",
        f"- **테마**: {e.theme or '—'}",
        f"- **카테고리**: {', '.join(e.categories) or '—'}",
    ]
    if e.damdang_tags:
        lines.append(f"- **분류담당(상품)**: {', '.join(e.damdang_tags)}")
    if e.product_codes:
        lines.append(f"- **상품코드**: {', '.join(e.product_codes[:8])}"
                       + (" …" if len(e.product_codes) > 8 else ""))
    basis = getattr(e, "routing_basis", None)
    if basis == "product":
        lines.append("- **분류기준**: 상품코드(HISIS→cat.txt)")
    elif basis == "category":
        lines.append("- **분류기준**: LLM 카테고리(상품코드 없음/미매칭)")
    lines.append(f"- **대상 지점**: {', '.join(e.branches)}")
    if e.valid_from or e.valid_to:
        lines.append(f"- **기간**: {e.valid_from or '?'} ~ {e.valid_to or '?'}")
    if e.effective_date:
        lines.append(f"- **시행일**: {e.effective_date}")
    lines.append(f"- **출처**: `{e.source_post_id}`")
    lines.append("")
    lines.append(e.summary)
    if e.images:
        lines.append("")
        lines.append("**이미지/슬라이드**")
        for img in e.images[:6]:
            lines.append(f"- [{img.kind}] {img.description[:200]}")
    if e.tables:
        lines.append("")
        lines.append("**표**")
        for tbl in e.tables:
            title = tbl.title or tbl.source_ref
            lines.append(f"- {title}: {len(tbl.columns)}열 × {len(tbl.rows)}행")
    lines.append("")
    return "\n".join(lines)


def _render_damdang_section(damdang: str, events: list[Event]) -> list[str]:
    lines = [f"## {damdang} ({len(events)})", ""]
    if not events:
        lines.append("(해당 이벤트 없음)")
        lines.append("")
        return lines
    by_theme = group_by_theme(events)
    for theme, evs in by_theme.items():
        lines.append(f"### {theme} ({len(evs)})")
        lines.append("")
        for e in evs:
            lines.append(_render_event_md(e))
    return lines


def export_llmwiki(
    events: list[Event],
    out_dir: str | Path,
    as_of: date,
    *,
    rnr_map_path: str = "config/rnr_category_map.yaml",
    grouping: str = "by_damdang",
    routing_stats: EnrichStats | None = None,
    product_only: bool = False,
) -> dict[str, Path]:
    """Write llmwiki JSON + Markdown grouped by 분류담당. Returns paths written."""
    out = Path(out_dir) / as_of.isoformat()
    out.mkdir(parents=True, exist_ok=True)
    damdang_dir = out / "by_damdang"
    damdang_dir.mkdir(exist_ok=True)
    for old in damdang_dir.glob("*.md"):
        old.unlink()

    dm = load_damdang_map(rnr_map_path)
    by_damdang = group_by_damdang(events, dm, product_only=product_only)

    damdang_payload: dict[str, dict] = {}
    for damdang, evs in by_damdang.items():
        themes = group_by_theme(evs)
        damdang_payload[damdang] = {
            "event_count": len(evs),
            "themes": {
                theme: [_event_dict(e) for e in theme_evs]
                for theme, theme_evs in themes.items()
            },
        }
        section_md = "\n".join(_render_damdang_section(damdang, evs))
        (damdang_dir / f"{damdang}.md").write_text(
            f"# {damdang}\n\n{section_md}", encoding="utf-8",
        )

    payload: dict = {
        "as_of": as_of.isoformat(),
        "grouping": grouping,
        "event_count": len(events),
        "damdang_count": len([d for d, evs in by_damdang.items() if evs]),
        "damdang": damdang_payload,
    }
    if routing_stats is not None:
        payload["routing"] = {
            "events_with_codes": routing_stats.events_with_codes,
            "events_product_routed": routing_stats.events_product_routed,
            "events_category_routed": routing_stats.events_category_routed,
            "unique_codes": routing_stats.unique_codes,
            "codes_resolved": routing_stats.codes_resolved,
        }
    json_path = out / "llmwiki.json"
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    md_lines = [
        f"# llmwiki — {as_of.isoformat()}",
        "",
        f"총 **{len(events)}**개 이벤트 · **담당(분류담당)별** 정리",
        "",
    ]
    for damdang, evs in by_damdang.items():
        if damdang == FALLBACK_KEY and not evs:
            continue
        md_lines.extend(_render_damdang_section(damdang, evs))

    md_path = out / "llmwiki.md"
    md_path.write_text("\n".join(md_lines), encoding="utf-8")

    return {"json": json_path, "markdown": md_path, "by_damdang_dir": damdang_dir}
