#!/usr/bin/env python3
"""Replace data/raw attachments with decrypted copies from ingest.zip."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief.ingest.sv_board import remap_raw_attachments_from_ingest


def main():
    root = Path(__file__).resolve().parents[1]
    stats = remap_raw_attachments_from_ingest(
        root / "data" / "raw",
        root / "data" / "ingest.zip",
    )
    print(json.dumps(stats, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
