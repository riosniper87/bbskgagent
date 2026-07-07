# Excel ingestion profiles

YAML files in `src/store_brief/ingestion/profiles/` drive row-level normalization.
Run `python scripts/analyze_excel_profiles.py` to refresh cluster analysis from `data/parsed/`.

## Matching

- Profiles are sorted by `priority` (desc), then `match` pattern length.
- First glob match with highest priority wins.
- `sheet_include` limits which sheets become row records.
- `header_rows` + `data_start_row` override heuristic table detection.

## Profile catalog (2026-06 corpus)

| Profile | Match | Sheets | Layout | Files (approx) |
|---------|-------|--------|--------|----------------|
| **진열소진_노트북** | `*노트북*진열소진*.xlsx` | 지사지점재고확인 | hdr [5,6], data@8, 42 cols | 4 |
| **진열소진_식기세척기** | `*진열소진*vf.xlsx` | 지사지점재고확인 | hdr [5,6], data@8, 43 cols | 2 |
| **진열소진** | `*진열소진*.xlsx` (fallback) | 지사지점재고확인 | same as notebook | rare |
| **체크리스트_지점** | `*지점 체크리스트*.xlsx` | 체크리스트 | hdr [3,4], data@5 | 1+ |
| **체크리스트_isp** | `*ISP*체크리스트*.xlsx` | 체크리스트 | hdr [1], data@2 | 1 |
| **소진리스트** | `*소진현황*.xlsx` | 소진 리스트 | hdr [2], data@3 | 오클린 등 |
| **점별모델확인** | `*지사지점*판매현황*.xlsx` | 점별모델확인 | hdr [6,7], data@9 | 선풍기 등 |
| **bcd_모델별** | `*BCD*소진현황*.xlsx` | 모델별 | hdr [3,4], data@7 | BCD 재고 |
| **non_pog_모델별** | `*NON POG*소진현황*.xlsx` | 모델별 | hdr [3,4], data@7 | NON POG 소진 |
| **sv_행사모델** | `SV팀_*진도율*.xlsx` | 행사모델_모델별, 하이라이트_모델별 | hdr [2,3], data@7 | SV 행사 진도 |

## Shared product-table layout (priority 28)

`점별모델확인`, `bcd_모델별`, `non_pog_모델별`, `sv_행사모델` share the same profile fields:

- `sheet_include` — target sheet only (skip wide pivot / 요약 grids)
- `header_rows` + `data_start_row` — skip 합계·빈 행
- `merge_fill_cols` — merged 대분류/메이커 (BCD·점별)
- `category_col` + `damdang_from: product`

## Not covered (→ heuristic / fallback)

Files matching `*진열소진*` without `지사지점재고확인` still use fallback unless a BCD/NON POG
profile applies. Wide SV sheets (`행사가산출표`, `(요약)모델별진도율`) are intentionally skipped.

## Example: 진열소진_노트북

```yaml
name: 진열소진_노트북
priority: 30
match: "*노트북*진열소진*.xlsx"
sheet_include: [지사지점재고확인]
header_rows: [5, 6]
data_start_row: 8
merge_fill_cols: [메이커]
category_col: "메이커"
damdang_from: product
```

Row body includes merged branch column names, e.g.
`강남지점 재고현황 / 재고수량: 5`.
