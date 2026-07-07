#!/usr/bin/env python3
"""Convenience entry point. Equivalent to: python -m store_brief.pipeline --as-of ..."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from store_brief.pipeline import main  # noqa: E402

if __name__ == "__main__":
    main()
