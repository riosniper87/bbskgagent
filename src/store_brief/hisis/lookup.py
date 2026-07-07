"""Query HISIS for PRD_CD and map to 분류담당 via cat.txt."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from store_brief.hisis.cat_index import CatRecord, load_cat_index, resolve_cat_record
from store_brief.hisis.oracle_env import configure_oracle_env, sql_in_list


@dataclass
class DamdangLookupResult:
    prd_cd: str
    prd_nm: str | None
    item_id: str | None
    item_cd: str | None
    cat: CatRecord | None
    damdang: tuple[str, ...]
    matched: bool

    def format_lines(self) -> list[str]:
        lines = [f"상품코드: {self.prd_cd}"]
        if self.prd_nm:
            lines.append(f"상품명: {self.prd_nm}")
        if self.item_cd:
            lines.append(f"품목코드: {self.item_cd}")
        if self.cat:
            lines.append(f"팀: {self.cat.team_nm} ({self.cat.team_cd})")
            lines.append(f"세부: {self.cat.dtl_type_nm} / {self.cat.cf_nm}")
        if self.damdang:
            lines.append(f"분류담당: {', '.join(self.damdang)}")
        else:
            lines.append("분류담당: (매칭 없음)")
        return lines


def render_extract_sql(
    prd_codes: list[str],
    sql_path: str | Path | None = None,
) -> str:
    root = Path(__file__).resolve().parents[3]
    path = Path(sql_path) if sql_path else root / "config" / "extract_info.sql"
    template = path.read_text(encoding="utf-8")
    if not prd_codes:
        raise ValueError("At least one product code (PRD_CD) is required")
    return template.format(prd_codes=sql_in_list(prd_codes))


def lookup_damdang_by_prd_codes(
    prd_codes: list[str],
    *,
    cat_path: str | Path | None = None,
    sql_path: str | Path | None = None,
    dry_run: bool = False,
) -> list[DamdangLookupResult]:
    root = Path(__file__).resolve().parents[3]
    cat_file = Path(cat_path) if cat_path else root / "config" / "cat.txt"
    cat_index = load_cat_index(cat_file)
    sql = render_extract_sql(prd_codes, sql_path=sql_path)

    if dry_run:
        print(sql)
        return [
            DamdangLookupResult(
                prd_cd=code,
                prd_nm=None,
                item_id=None,
                item_cd=None,
                cat=None,
                damdang=(),
                matched=False,
            )
            for code in prd_codes
        ]

    configure_oracle_env(project_root=root)
    from as_analysis.io.oracle_extract import extract_sql_to_polars

    frame = extract_sql_to_polars(sql)
    rows = frame.to_dicts()

    by_prd: dict[str, dict] = {}
    for row in rows:
        key = str(row.get("상품코드") or row.get("PRD_CD") or "").strip()
        if key and key not in by_prd:
            by_prd[key] = row

    results: list[DamdangLookupResult] = []
    for code in prd_codes:
        row = by_prd.get(code)
        if row is None:
            results.append(
                DamdangLookupResult(
                    prd_cd=code,
                    prd_nm=None,
                    item_id=None,
                    item_cd=None,
                    cat=None,
                    damdang=(),
                    matched=False,
                )
            )
            continue

        item_cd = row.get("품목코드") or row.get("ITEM_CD")
        item_id = row.get("ITEM_ID")
        if item_id is not None:
            item_id = str(item_id).strip()
        cat = resolve_cat_record(
            item_cd=str(item_cd).strip() if item_cd else None,
            item_id=item_id,
            index=cat_index,
        )
        damdang = cat.damdang if cat else ()
        results.append(
            DamdangLookupResult(
                prd_cd=code,
                prd_nm=row.get("상품명") or row.get("PRD_NM"),
                item_id=item_id,
                item_cd=str(item_cd).strip() if item_cd else None,
                cat=cat,
                damdang=damdang,
                matched=bool(damdang),
            )
        )
    return results
