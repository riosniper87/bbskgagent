---
name: QA test baseline
description: Which pytest failures are expected in a fresh clone of store-brief and why.
---

In a fresh clone (empty `data/`), the full pytest suite has ~10 pre-existing failures that are data-fixture gaps, NOT code regressions: `test_enrichment`, `test_hisis_cat`, `test_ingest` (×5), `test_ingestion_parse_xlsx`, `test_llmwiki_from_parsed`. They fail with `FileNotFoundError`/`KeyError` on missing files under `data/`.

**Why:** the pipeline scripts that produce `data/` inputs (board posts, R&R xlsx) can't run in this env — the source systems and vLLM endpoint are external.

**How to apply:** when judging whether a change regressed the suite, compare against this baseline instead of expecting all-green. QA-related suites (`tests/test_qa_*.py`, `test_search_index.py`, `test_kg_validate.py`) should be fully green.
