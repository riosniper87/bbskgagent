# store-brief

## Overview
Python prototype that generates daily per-employee store briefings (HTML) from internal board posts and R&R data. LLM inference (vLLM/gemma) runs on an external box; this repo handles deterministic parsing, storage, orchestration, and a FastAPI parse-result viewer.

## Project setup on Replit
- Python 3.11; dependencies from `pyproject.toml` installed to `.pythonlibs` (core + viewer + dev extras).
- `config/settings.yaml` was created from `config/settings.example.yaml` (default values).
- Workflow "Parse Viewer" runs `python scripts/serve_parse_viewer.py --port 5000` (binds 0.0.0.0:5000, webview).
- Deployment: autoscale, same run command.
- `data/` is mostly empty in a fresh clone — the viewer shows no posts until pipeline scripts (e.g. `parse_attachments.py`, `run_daily.py`) produce data.
- Optional: `OPENAI_API_KEY` secret enables the /qa panel; external vLLM endpoint is configured in `config/settings.yaml`.

## Code notes
- `src/store_brief/viewer/app.py` template calls were updated to the new Starlette `TemplateResponse(request, name, context)` signature (old signature removed in current Starlette).

## User preferences
(none recorded yet)
