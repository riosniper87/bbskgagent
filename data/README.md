# Data directory (local only)

This folder holds **runtime artifacts and company-internal content**. It is mostly excluded from git.

## Layout

```
data/
  raw/              # Board posts + attachments (NOT in git)
  parsed/           # Deterministic parse output (NOT in git)
  llmwiki/{as_of}/  # Q&A corpus cards (NOT in git)
  kg/{as_of}/       # Knowledge graph export (NOT in git)
  index/{as_of}/    # BM25 search index (NOT in git)
  cache/            # HISIS lookup cache (NOT in git)
  eval/             # QA eval runs (NOT in git; see *.example.json)
  reports/          # Generated HTML briefings (NOT in git)
  store.sqlite      # Event store (NOT in git)
```

## Bootstrap on a new machine

1. Place posts under `data/raw/{YYYY-MM-DD}/` (see `scripts/prepare_raw.py`).
2. Copy `config/settings.example.yaml` → `config/settings.yaml`.
3. Copy `config/cat.txt.example` → `config/cat.txt` (or export from internal HISIS).
4. Copy `.env.example` → `.env` and set `OPENAI_API_KEY`.
5. Run parse → llmwiki → index build (see `docs/PROGRESS.md`).
