"""Config loading: runtime settings, the seed category vocabulary, and the R&R roster."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

import yaml


@dataclass
class Settings:
    vllm_base_url: str
    model: str
    data_dir: str
    store_path: str
    reports_dir: str
    retention_weeks: int = 4
    embed_model: str | None = None
    use_rerank: bool = False
    review_fixed_layer: bool = True
    auto_adopt_proposals: bool = True
    openai_model: str = "gpt-4o-mini"


def load_dotenv(path: str | Path | None = None) -> None:
    """Load KEY=VALUE lines from .env into os.environ (does not override existing)."""
    import os

    if path is None:
        path = Path(__file__).resolve().parents[2] / ".env"
    p = Path(path)
    if not p.is_file():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = val


def load_settings(path: str) -> Settings:
    load_dotenv()
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return Settings(**raw)


def load_categories(path: str) -> list[str]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return list(raw["categories"])


def apply_vocab_proposals(categories_path: str, proposals: list[str]) -> list[str]:
    """Append proposed categories to categories.yaml. Returns newly added names."""
    if not proposals:
        return []
    p = Path(categories_path)
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    cats: list[str] = list(raw.get("categories", []))
    added = []
    for name in proposals:
        if name and name not in cats:
            cats.append(name)
            added.append(name)
    if added:
        raw["categories"] = cats
        p.write_text(
            yaml.dump(raw, allow_unicode=True, default_flow_style=False, sort_keys=False),
            encoding="utf-8",
        )
    return added


def load_rnr_category_map(path: str = "config/rnr_category_map.yaml") -> dict:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    managers = set(raw.get("managers", []))
    mappings = raw.get("mappings", {})
    return {"managers": managers, "mappings": mappings}


def load_roster(path: str, *, branch: str | None = None):
    """Load roster from CSV or rnr.txt (auto-detected by extension)."""
    p = Path(path)
    if p.suffix.lower() == ".txt":
        return load_roster_rnr_txt(path, branch=branch)
    return load_roster_csv(path, branch=branch)


def load_roster_csv(path: str, *, branch: str | None = None):
    """Read config/rnr.csv into Employee objects."""
    from store_brief.extract.schema import Employee

    employees = []
    with open(path, encoding="utf-8") as f:
        for row in csv.DictReader(f):
            emp = Employee(
                id=row["id"], name=row["name"], branch=row["branch"],
                is_store_manager=row["is_store_manager"].strip().lower() in ("1", "true", "y"),
                categories=[c for c in row["categories"].split("|") if c],
            )
            if branch and not _branch_matches(emp, branch):
                continue
            employees.append(emp)
    return employees


def load_roster_rnr_txt(
    path: str,
    *,
    branch: str | None = None,
    map_path: str = "config/rnr_category_map.yaml",
):
    """Read rnr.txt tab export into Employee objects.

  Columns used: 지점코드(3), 지점명칭(4), 사원(5), 성명(6), 분류담당(7).
  Rows with empty 분류담당 are excluded.
    """
    from store_brief.extract.schema import Employee

    rnr_map = load_rnr_category_map(map_path)
    managers = rnr_map["managers"]
    mappings = rnr_map["mappings"]

    text = Path(path).read_text(encoding="utf-8")
    lines = [ln for ln in text.replace("\r\n", "\n").replace("\r", "\n").split("\n") if ln.strip()]

    employees = []
    for line in lines[2:]:  # skip two header rows
        cols = line.split("\t")
        if len(cols) < 8:
            continue
        branch_code = cols[3].strip()
        branch_name = cols[4].strip()
        emp_id = cols[5].strip()
        name = cols[6].strip()
        rnr = cols[7].strip()

        if not rnr or not branch_name:
            continue

        is_manager = rnr in managers
        categories: list[str] = []
        if not is_manager:
            entry = mappings.get(rnr)
            if entry:
                categories = list(entry.get("categories", []))
            else:
                categories = [rnr]

        emp = Employee(
            id=emp_id,
            name=name,
            branch=branch_name,
            branch_code=branch_code or None,
            is_store_manager=is_manager,
            categories=categories,
        )
        if branch and not _branch_matches(emp, branch):
            continue
        employees.append(emp)
    return employees


def _branch_matches(emp, branch: str) -> bool:
    b = branch.strip()
    if emp.branch_code and emp.branch_code == b:
        return True
    return emp.branch == b
