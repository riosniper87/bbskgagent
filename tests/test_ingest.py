"""Tests for data ingest and R&R loading (no LLM required)."""

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from store_brief import config  # noqa: E402
from store_brief.ingest import board  # noqa: E402
from store_brief.parse.board_pdf import parse_board_pdf  # noqa: E402


ROOT = Path(__file__).resolve().parents[1]
RNR = ROOT / "data" / "rnr.txt"
RAW = ROOT / "data" / "raw"
STAGING = ROOT / "data" / "staging" / "sv"


def test_rnr_loader_excludes_empty_rnr():
    employees = config.load_roster_rnr_txt(str(RNR))
    assert len(employees) > 2000
    assert all(e.branch for e in employees)


def test_rnr_branch_filter():
    all_emps = config.load_roster_rnr_txt(str(RNR))
    code = all_emps[0].branch_code
    assert code
    filtered = config.load_roster(str(RNR), branch=code)
    assert filtered
    assert all(e.branch_code == code for e in filtered)


def test_rnr_manager_mapping():
    managers = [e for e in config.load_roster_rnr_txt(str(RNR)) if e.is_store_manager]
    assert len(managers) > 100
    assert all(not e.categories for e in managers)


def test_rnr_category_mapping():
    owners = [e for e in config.load_roster_rnr_txt(str(RNR)) if not e.is_store_manager]
    assert owners
    assert all(e.categories for e in owners)


def test_load_posts_backfill():
    posts = board.load_posts_backfill(str(RAW), date(2026, 6, 17))
    assert len(posts) >= 50
    assert all(p.posted_date <= date(2026, 6, 17) for p in posts)


def test_board_pdf_parsing():
  if not STAGING.exists():
      return  # skip if prepare_raw not run
  pdfs = list(STAGING.rglob("*.pdf"))
  pdfs = [p for p in pdfs if "출력" in p.stem or p.name.startswith("게시물")]
  assert pdfs
  draft = parse_board_pdf(pdfs[0], folder_name=pdfs[0].parent.name)
  assert draft.title
  assert draft.posted_date.year == 2026
  assert draft.posted_date.month == 6


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed.")
