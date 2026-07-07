"""VLM inference of Excel table layout from sheet images."""
from __future__ import annotations

from store_brief.extract.schema import TableLayoutDraft, TableRegionDraft
from store_brief.llm import prompts
from store_brief.llm.client import pydantic_json_schema
from store_brief.parse.layout_schema import TableLayoutSheet, TableRegionSpec


def _draft_to_layout(draft: TableLayoutDraft) -> TableLayoutSheet:
    regions = [
        TableRegionSpec(
            sheet=draft.sheet,
            title=r.title,
            header_rows=list(r.header_rows),
            data_start_row=int(r.data_start_row),
            columns=list(r.columns),
            col_indices=list(r.col_indices),
            data_end_row=r.data_end_row,
            region=int(r.region),
        )
        for r in draft.regions
    ]
    return TableLayoutSheet(
        sheet=draft.sheet,
        regions=regions,
        confidence=float(draft.confidence),
        needs_review=bool(draft.needs_review),
    )


def infer_layout(
    image_path: str,
    *,
    sheet_name: str,
    filename: str,
    grid_snippet: str,
    llm,
) -> TableLayoutSheet | None:
    prompt = prompts.TABLE_LAYOUT_FROM_IMAGE.format(
        grid_snippet=grid_snippet or "(없음)",
        filename=filename,
        sheet_name=sheet_name,
    )
    try:
        schema = pydantic_json_schema(TableLayoutDraft)
        data = llm.describe_image_structured(
            image_path,
            prompt,
            json_schema=schema,
            schema_name="table_layout",
        )
        draft = TableLayoutDraft.model_validate(data)
        draft.sheet = sheet_name
        if not draft.regions:
            return None
        return _draft_to_layout(draft)
    except Exception:
        return None
