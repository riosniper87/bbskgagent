#!/usr/bin/env python3
"""Serve the parse result viewer (FastAPI).

  pip install -e ".[viewer]"
  python scripts/serve_parse_viewer.py --port 8765
  # → http://localhost:8765  and LAN http://<your-ip>:8765

  # Windows LAN restart (opens firewall + binds 0.0.0.0):
  .\scripts\serve_viewer_lan.ps1

Can be run from any directory; paths resolve relative to the store-brief project root.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "src"))
os.chdir(_ROOT)


def _latest_as_of(data_dir: Path) -> str | None:
    """Pick newest YYYY-MM-DD folder under data/kg or data/llmwiki."""
    best: str | None = None
    for sub in ("kg", "llmwiki"):
        base = data_dir / sub
        if not base.is_dir():
            continue
        for child in base.iterdir():
            if not child.is_dir():
                continue
            name = child.name
            if len(name) == 10 and name[4] == "-" and name[7] == "-":
                if best is None or name > best:
                    best = name
    return best


def _lan_ipv4() -> str | None:
    """Best-effort primary LAN IPv4 for sharing on the local network."""
    import socket

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser(description="Parse result viewer")
    ap.add_argument(
        "--settings",
        default=str(_ROOT / "config" / "settings.yaml"),
        help="settings.yaml path (default: <project>/config/settings.yaml)",
    )
    ap.add_argument("--as-of", default=None, help="llmwiki date folder YYYY-MM-DD")
    ap.add_argument("--host", default="0.0.0.0", help="bind address (0.0.0.0 = LAN + localhost)")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()

    try:
        import uvicorn
    except ImportError:
        raise SystemExit(
            "FastAPI viewer dependencies missing.\n"
            "  pip install -e \".[viewer]\""
        ) from None

    from store_brief import config
    from store_brief.viewer.app import create_app

    settings_path = Path(args.settings)
    if not settings_path.is_file():
        raise SystemExit(f"Settings not found: {settings_path.resolve()}")

    settings = config.load_settings(str(settings_path))
    data_dir = Path(settings.data_dir)
    if not data_dir.is_absolute():
        data_dir = (_ROOT / data_dir).resolve()

    parsed_dir = data_dir / "parsed"
    if not parsed_dir.is_dir():
        print(f"Warning: {parsed_dir} not found - run parse_attachments.py first.")

    as_of = args.as_of or _latest_as_of(data_dir)
    if as_of is None:
        print("Warning: no --as-of and no data/kg or data/llmwiki date folder - /kg will return 400.")
    elif args.as_of is None:
        print(f"  as_of: {as_of} (auto from latest kg/llmwiki folder)")

    app = create_app(
        data_dir,
        as_of=as_of,
        openai_model=settings.openai_model,
    )
    url = f"http://{args.host}:{args.port}"
    if args.host == "0.0.0.0":
        lan = _lan_ipv4()
        print(f"Parse viewer (all interfaces) at http://localhost:{args.port}")
        if lan:
            print(f"  LAN access:      http://{lan}:{args.port}")
        url = f"http://localhost:{args.port}"
    else:
        print(f"Parse viewer at {url}")
    print(f"  Knowledge graph: {url}/kg")
    print(f"  Q&A panel:       {url}/qa")
    if not os.environ.get("OPENAI_API_KEY"):
        print("  Warning: OPENAI_API_KEY not set - /qa will return 503 until configured.")
    print(f"  data_dir: {data_dir}")
    print("  Press Ctrl+C to stop.")
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
