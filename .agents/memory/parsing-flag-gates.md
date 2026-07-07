---
name: Parsing review_flag noise gates
description: Downstream llmwiki noise filters key on review_flag, not source_type — constraints when promoting fallback records to unflagged rows.
---

The llmwiki card builder's noise gate (`_skip_noisy_slice`) only applies to records whose `review_flag` is `xlsx_fallback`/`fallback_content`. Promoting excel fallback blobs to unflagged `excel_row` records bypasses that gate entirely.

**Why:** during the parsing-quality work we added a heuristic row-extraction path for unmatched Excel profiles; the architect flagged that inventory grids with meaningful headers would flood WikiCards (hundreds of rows per damdang) if only a headers-are-meaningful gate was used.

**How to apply:** any new unflagged record path in `ingestion/parse_*` must apply its own noise gate (inventory-sheet regex mirroring `_INVENTORY_SHEET_RE` in `llmwiki/from_parsed.py`) and a per-table row cap. Keep the two regexes in sync.

Related gotchas from the same work:
- `effective_text = body or vlm_text` in the card builder: records meant to be filled by VLM descriptions (e.g. image-only PPTX slides) must keep an EMPTY body — any placeholder text suppresses the VLM lookup.
- python-pptx/PowerPoint auto-fill picture `descr` (alt text) with the image filename ("image.png") — filter filename-like descr values before treating them as meaningful alt text.
- Changing source_ref shapes (e.g. `#sheet:name` → `#row:sheet:key`) resets `link_card_versions` temporal linking and VLM index lookups on reprocessed corpora — acceptable only with full-pipeline regeneration.
