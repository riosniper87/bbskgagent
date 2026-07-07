# store-brief 진행 정리

> 기준일(as_of): **2026-06-17** · 문서 작성: 2026-07-07  
> 프로토타입: 매장 사내 게시판 + 첨부 → **담당별 llmwiki** + **QA 검색/답변** + (향후) 일일 브리핑 HTML

---

## 1. 프로젝트 목표

| 박스 | 역할 |
|------|------|
| **DGX Spark** | vLLM(gemma-4) — VLM 표/이미지, LLM 추출·리포트 |
| **NPU/CPU** | 결정적 파싱, HISIS 라우팅, BM25 인덱스, FastAPI 뷰어, QA |

핵심 아이디어: 게시글·첨부를 **타입드 시간 엔티티**로 저장하고, 날짜·담당 매칭은 **결정적 코드**, LLM은 추출·요약·최종 문장만 담당.

---

## 2. 완료된 기능 (Phase별)

### Phase 1–2: 파싱 · 저장

- **게시판 ingest** — `posts.json` + `attachments/` (`ingest/`)
- **결정적 파서** — Excel / PPTX / PDF / 이미지 (`parse/`, `ingestion/parse_*.py`)
- **ParsedAttachmentStore** — `data/parsed/{post_id}/` JSON + meta
- **파싱 뷰어** — `scripts/serve_parse_viewer.py` → http://localhost:8765 (LAN `0.0.0.0`)

### Phase 3: llmwiki · HISIS 라우팅

- **llmwiki 빌드** — `scripts/build_llmwiki_from_parsed.py`
  - 슬라이드/시트/행 단위 카드
  - 본문 카드 + **상품코드(PRD_CD)** 추출 → HISIS Oracle → `cat.txt` **분류담당** 라우팅
- **HISIS 모듈** — `hisis/prd_codes.py`, `batch_lookup.py`, `cat_index.py`
  - SSH 터널(15211) + `config/extract_info.sql` (SC011M/SC010C)
  - 캐시: `data/cache/hisis_prd_damdang.json`
- **담당별 export** — `data/llmwiki/{as_of}/by_damdang/`
- 최근 빌드 규모: **~5523 cards** (parsed 슬라이스 4160 + 본문 등)

### Phase 4: Knowledge Graph · 뷰어 확장

- **KG 빌드** — `scripts/build_knowledge_graph.py`, `/kg` UI
- **QA 패널** — `/qa`, OpenAI 기반 질의 (`qa/orchestrator.py`)

### Phase 5–6: 검색 인덱스 · QA v2

| 항목 | 파일 | 설명 |
|------|------|------|
| BM25 인덱스 | `index/build.py`, `index/search.py` | `data/index/{as_of}/search_index.pkl` |
| Corpus | `qa/corpus.py` | `QACorpus` + persistent index |
| Retrieval v2 | `qa/tools/retrieve.py` | soft damdang boost, recency, topic dedup |
| API | `viewer/app.py` | `POST /api/qa/search`, `GET /api/qa/status` |
| UI | `qa-panel.js` | 「검색만」 버튼 |
| 테스트 | `test_search_index.py`, `test_qa_retrieve_v2.py` | |

### Excel 프로필 기반 ingestion (최근)

YAML 프로필(`src/store_brief/ingestion/profiles/`)로 **행 단위** 정규화.  
`header_rows`, `data_start_row`, `merge_fill_cols`, `sheet_include`, `priority` 지원.

| 프로필 | 용도 |
|--------|------|
| 진열소진_노트북 / _식기세척기 / 진열소진 | 지사지점재고확인 시트 |
| 체크리스트_지점 / _isp | SV·ISP 체크리스트 |
| 소진리스트 | 오클린 등 소진 리스트 |
| **점별모델확인** | 지사지점 판매현황 |
| **bcd_모델별 / non_pog_모델별** | BCD·NON POG 모델별 소진 |
| **sv_행사모델** | SV팀 진도율 행사모델 시트 |

도구: `scripts/analyze_excel_profiles.py`, `docs/excel-profiles.md`

### QA Eval · 회귀

- `scripts/run_qa_eval.py` — hit@1/3, attachment match, (선택) LLM judge
- `data/eval/regression_cases.json` — 5건 고정 회귀 (로컬 전용)
- 회귀 최종: **4/5** (체크리스트 vs 광고 PPTX hit@1 경합 1건)

---

## 3. 디렉터리 맵

```
src/store_brief/
  ingest/          게시판·첨부 적재
  parse/           레거시 결정적 파서
  ingestion/       프로필 기반 row-level Excel (+ pptx/pdf)
  hisis/           Oracle PRD_CD → cat.txt 담당
  llmwiki/         카드 빌드·enrichment·export
  index/           BM25 영구 인덱스
  qa/              corpus, retrieve, orchestrator, eval
  kg/              knowledge graph
  viewer/          FastAPI + templates + static
  report/          (향후) Jinja HTML 브리핑

scripts/           CLI (parse, build, eval, serve)
config/            settings, cat.txt, team maps, SQL
tests/             33 test modules
docs/              프로필, QA eval, 본 문서
```

---

## 4. 주요 실행 명령

```bash
pip install -e ".[viewer]"

# 파싱
python scripts/parse_attachments.py --as-of 2026-06-17

# llmwiki (+ HISIS 캐시)
python scripts/build_llmwiki_from_parsed.py --as-of 2026-06-17 --no-vlm-index --cache-only

# QA 회귀 (로컬 corpus 필요)
python scripts/run_qa_eval.py --as-of 2026-06-17 --regression-only --no-judge

# 뷰어
python scripts/serve_parse_viewer.py --port 8765
```

---

## 5. 알려진 이슈 · 미완

| 항목 | 상태 |
|------|------|
| 체크리스트 회귀 hit@1 | 광고 PPTX와 경합 — retrieve boost 조정 여지 |
| `*진열소진*` 중 미프로필 시트 | fallback blob 카드 |
| SV 669열 그리드 | 의도적 skip (요약 시트만 프로필) |
| OCR 교차검증 루프 | 자리만 (`ocr` extra) |
| 벡터 검색 | BM25 primary; embedding optional |
| 일일 HTML 리포트 | pipeline 골격만, 배포 미연동 |
| raw 첨부 일부 | 로컬 경로 없음 → parse skip (정상) |

---

## 6. 테스트

```bash
python -m pytest tests/ -q
# 핵심만 (모델 불필요)
python tests/test_core.py
```

Excel 프로필: `tests/test_ingestion_parse_xlsx.py` (10 cases)

---

## 7. Git 공개 시

민감 데이터·DB는 **커밋하지 않음**. 절차는 `docs/GIT_SETUP.md` 참고.

- 제외: `data/raw`, `parsed`, `llmwiki`, `cache`, `index`, `eval` 실행 결과
- 제외: `config/cat.txt`(전체 품목 마스터), `config/settings.yaml`(내부 IP)
- 제외: `.env` (OpenAI 키, Oracle 자격증명은 `infra/.env` — 별도 repo)

---

## 8. 다음 후보

1. 회귀 5/5 — 체크리스트 retrieval boost
2. 클리어런스 / POG 등 추가 Excel 클러스터 프로필
3. `sheet_exclude` / `max_body_parts` 프로필 스키마 확장
4. llmwiki rebuild CI + eval automation (`docs/qa-eval-automation.md`)
