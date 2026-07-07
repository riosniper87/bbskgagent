"""Vision pass: turn an image into an ImageNote, and a table image into an ExtractedTable.

Prototype policy: trust the VLM's auto-extraction. The verification loop (OCR<->VLM
cross-check) is intentionally not implemented — the place it will live is marked below.
"""

from __future__ import annotations

from store_brief.extract.schema import ExtractedTable, ImageNote, VisionDescribeResult
from store_brief.llm import prompts
from store_brief.llm.client import pydantic_json_schema


def describe(image_path: str, source_ref: str, llm) -> tuple[ImageNote, ExtractedTable | None]:
    try:
        schema = pydantic_json_schema(VisionDescribeResult)
        data = llm.describe_image_structured(
            image_path, prompts.VISION_DESCRIBE,
            json_schema=schema, schema_name="vision_describe",
        )
        result = VisionDescribeResult.model_validate(data)
    except Exception:
        return ImageNote(source_ref=source_ref, kind="기타", description="(이미지 처리 불가)"), None
    note = ImageNote(source_ref=source_ref, kind=result.kind, description=result.description)
    table = None
    if result.table and (result.table.columns or result.table.rows):
        table = ExtractedTable(
            source_ref=source_ref,
            title=result.table.title,
            columns=result.table.columns,
            rows=result.table.rows,
        )
    return note, table
