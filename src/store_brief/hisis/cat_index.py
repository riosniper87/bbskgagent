"""Load cat.txt and resolve Oracle item codes to 분류담당."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CatRecord:
    item_id: str
    item_cd: str
    team_cd: str
    team_nm: str
    dtl_type_nm: str
    cf_nm: str
    damdang: tuple[str, ...]


def load_cat_index(path: str | Path) -> dict[str, CatRecord]:
    """Index by ITEM_CD (5-char keys in cat.txt)."""
    p = Path(path)
    index: dict[str, CatRecord] = {}
    with p.open(encoding="utf-8") as f:
        header = f.readline().rstrip("\n").split("\t")
        col = {name: i for i, name in enumerate(header)}
        for line in f:
            if not line.strip():
                continue
            cols = line.rstrip("\n").split("\t")
            item_cd = cols[col["ITEM_CD"]].strip()
            damdang_raw = cols[col.get("분류담당", -1)] if "분류담당" in col else ""
            damdang = tuple(d for d in damdang_raw.split("|") if d)
            index[item_cd] = CatRecord(
                item_id=cols[col["ITEM_ID"]].strip(),
                item_cd=item_cd,
                team_cd=cols[col["ITEM_GRP_TEAM_CD"]].strip(),
                team_nm=cols[col["ITEM_GRP_TEAM_NM"]].strip(),
                dtl_type_nm=cols[col["ITEM_GRP_DTL_TYPE_NM"]].strip(),
                cf_nm=cols[col["ITEM_GRP_CF_NM"]].strip(),
                damdang=damdang,
            )
    return index


def resolve_cat_record(
    *,
    item_cd: str | None,
    item_id: str | None,
    index: dict[str, CatRecord],
) -> CatRecord | None:
    """Match HISIS 품목코드 / ITEM_ID to a cat.txt row."""
    if item_id:
        for rec in index.values():
            if rec.item_id == item_id.strip():
                return rec

    code = (item_cd or "").strip().upper()
    if not code:
        return None

    if code in index:
        return index[code]

    prefix5 = code[:5]
    if prefix5 in index:
        return index[prefix5]

    # SC010C may use 3-char family codes; pick first cat row with same prefix.
    for key, rec in index.items():
        if key.startswith(code[:3]):
            return rec

    return None
