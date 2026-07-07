"""Mock LLM client — generates prose from structured items without API calls."""
from __future__ import annotations

import json
import re


class MockLLM:
    """Drop-in replacement for LLMClient in sample/mock report runs."""

    def complete(self, prompt: str, system: str | None = None) -> str:
        if "테마 라벨" in prompt or "theme" in prompt.lower():
            m = re.search(r"제목:\s*(.+)", prompt)
            return (m.group(1).strip()[:20] if m else "운영 공지")

        if "정책" in prompt and "[이전]" in prompt:
            return "정책 내용이 개정되었습니다. 첨부 및 본문의 시행일·적용 조건을 확인해 주세요."

        if "[섹션]" in prompt:
            return self._section_prose(prompt)
        return "확인이 필요한 사내 공지입니다."

    def _section_prose(self, prompt: str) -> str:
        is_manager = "점장용" in prompt
        m = re.search(r"\[섹션\]\s*(.+)", prompt)
        section = m.group(1).strip() if m else "브리핑"
        items = []
        for line in prompt.splitlines():
            if line.startswith("- ["):
                items.append(line[2:].strip())
        if not items:
            return f"{section} 관련 특이 사항이 없습니다."

        bullets = []
        for item in items[:6]:
            # "- [공지] title: summary"
            parts = item.split(":", 1)
            head = parts[0].strip("[]")
            tail = parts[1].strip() if len(parts) > 1 else ""
            if is_manager:
                bullets.append(f"• {head} — 당일 확인·현장 공유가 필요합니다. {tail[:80]}")
            else:
                bullets.append(f"• {head}: {tail[:100]}")
        intro = (
            "오늘 지점에서 우선 처리할 일입니다."
            if is_manager
            else "담당 품목과 관련된 주요 공지입니다."
        )
        return intro + " " + " ".join(bullets)

    def complete_json(self, prompt: str, system: str | None = None) -> object:
        return json.loads(self.complete(prompt))

    def complete_structured(self, prompt, *, system=None, json_schema=None, schema_name=""):
        return {"events": []}

    def describe_image(self, image_path: str, prompt: str) -> str:
        return '{"kind": "기타", "description": "(mock)", "table": null}'

    def describe_image_structured(self, image_path, prompt, *, json_schema=None, schema_name=""):
        return {"kind": "기타", "description": "(mock)", "table": None}

    def describe_image_url(self, image_url: str, prompt: str) -> str:
        return "(mock image description)"

    def list_models(self) -> list[str]:
        return ["mock"]
