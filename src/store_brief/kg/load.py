"""Load persisted knowledge graph."""
from __future__ import annotations

import json
from pathlib import Path

from store_brief.kg.schema import KnowledgeGraph


def load_knowledge_graph(path: str | Path) -> KnowledgeGraph:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    return KnowledgeGraph.model_validate(data)


def default_graph_path(data_dir: str, as_of: str) -> Path:
    return Path(data_dir) / "kg" / as_of / "graph.json"
