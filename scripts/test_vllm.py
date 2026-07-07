#!/usr/bin/env python3
"""vLLM connectivity and structuring smoke tests for gemma-4-26B-A4B-it."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config  # noqa: E402
from store_brief.extract.schema import EventExtractionResult  # noqa: E402
from store_brief.llm import prompts  # noqa: E402
from store_brief.llm.client import LLMClient, pydantic_json_schema  # noqa: E402

HIMART_IMAGE = (
    "https://static1.e-himart.co.kr/contents/goods/00/61/65/10/75/"
    "0061651075__SC5GMR81S.AKOR__M_640_640.jpg"
)


def _record(results: list, name: str, ok: bool, detail: str = ""):
    results.append({"test": name, "ok": ok, "detail": detail[:500]})
    status = "PASS" if ok else "FAIL"
    print(f"[{status}] {name}" + (f": {detail[:120]}" if detail else ""))


def main():
    root = Path(__file__).resolve().parents[1]
    settings = config.load_settings(str(root / "config" / "settings.yaml"))
    llm = LLMClient(base_url=settings.vllm_base_url, model=settings.model)
    results: list[dict] = []

    # 1. models list
    try:
        models = llm.list_models()
        ok = settings.model in models or any(settings.model in m for m in models)
        _record(results, "list_models", ok, f"found={models[:3]}...")
    except Exception as exc:
        _record(results, "list_models", False, str(exc))

    # 2. text completion
    try:
        text = llm.complete("한 문장으로 인사해 주세요.")
        _record(results, "text_completion", bool(text.strip()), text[:100])
    except Exception as exc:
        _record(results, "text_completion", False, str(exc))

    # 3. remote image URL
    try:
        desc = llm.describe_image_url(HIMART_IMAGE, "Describe this image in detail.")
        _record(results, "remote_image", bool(desc.strip()), desc[:100])
    except Exception as exc:
        _record(results, "remote_image", False, str(exc))

    # 4. local image (from raw attachments if available)
    local_img = None
    raw = root / "data" / "raw"
    for ext in ("*.png", "*.jpg", "*.jpeg"):
        found = list(raw.rglob(ext))
        if found:
            local_img = found[0]
            break
    if local_img:
        try:
            desc = llm.describe_image(str(local_img), "이 이미지를 한국어로 간략히 설명하라.")
            _record(results, "local_image", bool(desc.strip()), desc[:100])
        except Exception as exc:
            _record(results, "local_image", False, str(exc))
    else:
        _record(results, "local_image", True, "skipped (no local images)")

    # 5. structured event extraction
    try:
        categories = config.load_categories(str(root / "config" / "categories.yaml"))
        system = prompts.EXTRACT_EVENTS_SYSTEM.format(categories=", ".join(categories))
        user = prompts.EXTRACT_EVENTS_USER.format(
            title="[전점] 반품 정책 개정 안내",
            posted_date="2026-06-16",
            body="반품 가능 기간이 14일에서 7일로 변경됩니다.",
            attachments="(없음)",
        )
        schema = pydantic_json_schema(EventExtractionResult)
        data = llm.complete_structured(
            user, system=system, json_schema=schema, schema_name="event_extraction",
        )
        parsed = EventExtractionResult.model_validate(data)
        ok = len(parsed.events) >= 1
        sample = parsed.model_dump()
        _record(results, "structured_extraction", ok, json.dumps(sample, ensure_ascii=False)[:200])
    except Exception as exc:
        _record(results, "structured_extraction", False, str(exc))
        sample = {}

    report = {
        "base_url": settings.vllm_base_url,
        "model": settings.model,
        "results": results,
        "structured_sample": sample if results[-1].get("ok") else None,
        "all_passed": all(r["ok"] for r in results),
    }
    out_path = root / "data" / "vllm_test_report.json"
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nReport written to {out_path}")
    if not report["all_passed"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
