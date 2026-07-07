"""Thin client over the vLLM OpenAI-compatible server running on DGX Spark.

vLLM exposes /v1/chat/completions; gemma-4-26B-A4B-it accepts interleaved text + images,
so the same client serves both text tasks and vision (image/table) tasks. We use the
`openai` SDK pointed at the local base_url. JSON-returning calls request structured output
and strip code fences defensively.
"""

from __future__ import annotations

import base64
import json
import logging
import mimetypes
import os
from pathlib import Path
from typing import Any

try:
    from openai import OpenAI
except ImportError:  # keep import-time soft so the rest of the repo loads without the dep
    OpenAI = None

log = logging.getLogger(__name__)


def _image_data_url(path: str) -> str:
    mime = mimetypes.guess_type(path)[0] or "image/png"
    b64 = base64.b64encode(Path(path).read_bytes()).decode()
    return f"data:{mime};base64,{b64}"


def _strip_fences(text: str) -> str:
    t = text.strip()
    if t.startswith("```"):
        t = t.split("\n", 1)[-1].rsplit("```", 1)[0]
    return t.strip()


def pydantic_json_schema(model: type) -> dict[str, Any]:
  """Build JSON schema dict for vLLM response_format from a Pydantic model."""
  return model.model_json_schema()


_OPENAI_DEFAULT_BASE = "https://api.openai.com/v1"


class LLMClient:
    def __init__(self, base_url: str, model: str, api_key: str = "EMPTY", temperature: float = 0.2):
        if OpenAI is None:
            raise RuntimeError("openai package not installed; `pip install openai`")
        self.client = OpenAI(base_url=base_url, api_key=api_key)
        self.model = model
        self.temperature = temperature

    @classmethod
    def openai(
        cls,
        *,
        api_key: str | None = None,
        model: str = "gpt-4o-mini",
        temperature: float = 0.2,
    ) -> LLMClient:
        key = api_key or os.environ.get("OPENAI_API_KEY")
        if not key:
            raise RuntimeError(
                "OPENAI_API_KEY not set — export it or add to store-brief/.env"
            )
        return cls(
            base_url=_OPENAI_DEFAULT_BASE,
            model=model,
            api_key=key,
            temperature=temperature,
        )

    def list_models(self) -> list[str]:
        return [m.id for m in self.client.models.list().data]

    def complete(self, prompt: str, system: str | None = None) -> str:
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        resp = self.client.chat.completions.create(
            model=self.model, messages=msgs, temperature=self.temperature
        )
        return resp.choices[0].message.content or ""

    def complete_json(self, prompt: str, system: str | None = None) -> object:
        """Prompt must instruct the model to return JSON only. Returns parsed object."""
        raw = self.complete(prompt, system=system)
        return json.loads(_strip_fences(raw))

    def complete_structured(
        self,
        prompt: str,
        *,
        system: str | None = None,
        json_schema: dict[str, Any],
        schema_name: str,
    ) -> dict[str, Any]:
        """Guided JSON via response_format; falls back to complete_json on error."""
        msgs = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=msgs,
                temperature=self.temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": json_schema,
                        "strict": False,
                    },
                },
            )
            raw = resp.choices[0].message.content or "{}"
            return json.loads(_strip_fences(raw))
        except Exception as exc:
            log.warning("structured output failed (%s); falling back to complete_json", exc)
            max_chars = 400_000  # ~16k token safety margin for gemma-4 16k ctx
            if len(prompt) > max_chars:
                prompt = prompt[:max_chars] + "\n…(프롬프트 잘림)"
            if system and len(system) > 8_000:
                system = system[:8_000]
            result = self.complete_json(prompt, system=system)
            if isinstance(result, dict):
                return result
            return {"events": result} if schema_name == "event_extraction" else {"data": result}

    def describe_image(self, image_path: str, prompt: str) -> str:
        """Single-image vision call (description / table extraction)."""
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
        ]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            temperature=self.temperature,
        )
        return resp.choices[0].message.content or ""

    def describe_image_structured(
        self,
        image_path: str,
        prompt: str,
        *,
        json_schema: dict[str, Any],
        schema_name: str = "vision_describe",
    ) -> dict[str, Any]:
        """Vision call with guided JSON when supported."""
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": _image_data_url(image_path)}},
        ]
        try:
            resp = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": content}],
                temperature=self.temperature,
                response_format={
                    "type": "json_schema",
                    "json_schema": {
                        "name": schema_name,
                        "schema": json_schema,
                        "strict": False,
                    },
                },
            )
            raw = resp.choices[0].message.content or "{}"
            return json.loads(_strip_fences(raw))
        except Exception as exc:
            log.warning("vision structured failed (%s); falling back", exc)
            try:
                raw = self.describe_image(image_path, prompt)
            except Exception as exc2:
                log.warning("vision fallback failed (%s); skipping image", exc2)
                return {"kind": "기타", "description": "(이미지 처리 불가)", "table": None}
            start, end = raw.find("{"), raw.rfind("}")
            if start >= 0 and end > start:
                return json.loads(raw[start: end + 1])
            return {"kind": "기타", "description": raw, "table": None}

    def describe_image_url(self, image_url: str, prompt: str) -> str:
        content = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": image_url}},
        ]
        resp = self.client.chat.completions.create(
            model=self.model,
            messages=[{"role": "user", "content": content}],
            temperature=self.temperature,
        )
        return resp.choices[0].message.content or ""
