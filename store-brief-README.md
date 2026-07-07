# store-brief

매장 사내 게시판(제목·내용·날짜·첨부)과 직원 R&R을 입력받아, **직원별 일일 업무 브리핑(HTML)**을
자동 생성하는 프로토타입. 추론은 DGX Spark의 vLLM(gemma-4-26B-A4B-it)이 담당한다.

## 핵심 아이디어

게시글·첨부를 **타입이 있는 시간 엔티티(typed temporal event)**로 추출해 작은 저장소에 넣는다.
그러면 "오늘 종료되는 판촉 / 이번주 신규 / 정책 변경" 같은 날짜 기준 리포팅이
**전부 결정적 코드**가 되고, LLM은 추출·diff 요약·최종 프로즈만 맡는다(날짜 계산을 LLM이 하지 않음).
R&R이 `(지점 × 카테고리 → 담당자) + 점장` 구조라 연관성 매칭도 대부분 결정적·설명가능하다.

이것이 "정식 온톨로지"가 아니라 **llmwiki(테마별 콘텐츠) + 얇은 타입드-시간-엔티티 계층**을
택한 이유다. 그 얇은 계층이 온톨로지의 알짜(역할→카테고리 매핑, 버전 체인)만 가져온다.

## 두 박스 배포

| 박스 | 역할 | 모듈 |
| --- | --- | --- |
| DGX Spark | vLLM 추론(VLM=이미지·표, LLM=추출·분류·rerank·리포트) | `llm/` |
| NPU/CPU 박스 | 결정적 파싱·임베딩·저장소·오케스트레이션·HTML 렌더링 | 그 외 전부 |

둘은 OpenAI 호환 HTTP로 통신한다.

## 데이터 흐름 (일배치)

```
ingest → parse(결정적) → extract(LLM/VLM) → theme → store(+versioning, 4주 prune)
       → relevance(결정적 매핑 + 선택적 검색·rerank) → temporal(종료·신규·정책diff·타임라인)
       → report(LLM 프로즈 + Jinja) → data/reports/{as_of}/{지점}_{이름}.html
```

## 실행

```bash
# 1) Spark에서 모델 서빙
bash scripts/serve_vllm.sh

# 2) NPU 박스에서 일배치 (프로토타입 기준일 6/17)
pip install -e .
python scripts/run_daily.py --as-of 2026-06-17
```

입력 레이아웃: `data/raw/2026-06-17/posts.json` + `data/raw/2026-06-17/attachments/`.

## 결정적 핵심만 테스트 (모델·pydantic 불필요)

```bash
python tests/test_core.py
```

## 프로토타입 범위에서 의도적으로 비워둔 것

- **표 정확도 검증 루프(OCR↔VLM 교차검증)** — 먼저 gemma-4 자동추출 성능을 확인한 뒤 결정.
  자리만 비워둠: `ExtractedTable.confidence/needs_review`, `parse/image.py`의 OCR 훅.
- **테마 클러스터링** — `theme/cluster.py` (자유 테마를 안정 테마로 승격).
- **벡터 검색 실구현** — `store/index.py` 는 현재 no-op 리콜 부스터.
- **리포트 전달·접근권한** — 현재 파일 출력만. 포털/메일 연동과 권한은 다음 단계.

## 디렉터리

```
src/store_brief/
  ingest/     게시판 글·첨부 적재
  parse/      결정적 파서(excel/pptx/pdf/image) — 모델 불필요
  llm/        vLLM 클라이언트 + 프롬프트 + 비전
  extract/    schema(pydantic) + 글·첨부 → typed event + 표
  theme/      카테고리 앵커 테마 분류 (+ 클러스터 stub)
  store/      SQLite + 버전 체인 + 벡터 인덱스
  relevance/  R&R 결정적 매핑 + 검색 + rerank
  temporal/   종료·신규·정책diff·타임라인 (결정적)
  report/     섹션 조립 + Jinja HTML
  llmwiki/    parsed+상품코드 기반 wiki 카드 (greenfield)
  kg/         WikiCard spine 지식 그래프 (provenance + catalog)
  pipeline.py 일배치 오케스트레이션
```

## llmwiki + 지식 그래프 (greenfield)

VLM 없이 **parsed 첨부 + HISIS 상품코드 + cat.txt 담당**으로 wiki 카드와 지식 그래프를 만든다.

```bash
# 1) llmwiki (WikiCard)
python scripts/build_llmwiki_from_parsed.py --as-of 2026-06-17

# 2) 지식 그래프 (WikiCard spine + 첨부 provenance)
python scripts/build_knowledge_graph.py --as-of 2026-06-17
```

출력:

- `data/llmwiki/{as_of}/llmwiki.json` — 담당별 WikiCard
- `data/kg/{as_of}/graph.json` — 노드(Post, Attachment, ContentSlice, WikiCard, Product, Damdang) + 엣지
- `data/kg/{as_of}/by_damdang/*.json` — 담당별 subgraph

각 WikiCard 노드에는 Q&A용 필드가 포함된다:

- `text_for_retrieval` — headline + body
- `provenance` — post_id, attachment_name, attachment_path, source_ref, viewer_url
- `product_codes`, `damdang_filter`

Parse viewer KG API (`--as-of` 필요):

- `GET /kg` — Obsidian 스타일 지식 그래프 시각화 (vis-network)
- `GET /api/kg/graph` — 시각화용 nodes/edges JSON (`mode`, `damdang`, `include_products`)
- `GET /api/kg` — 그래프 통계
- `GET /api/kg/posts/{post_id}` — 게시물 관련 카드 + 첨부 provenance
- `GET /api/kg/products/{PRD_CD}` — 상품코드 관련 카드

### Phase 2 (Q&A) 로드맵 — **시간 기반 검색** 중심

질의 예: «6월 중순 대형가전 판촉», «지난달 설치 변경 공지», «이번 개정에서 뭐가 바뀌었어?»

1. **WikiCard `temporal` 필드** (빌드 시 자동 추출)
   - `notice_kind` (판촉/정책/공지…), `valid_from`/`valid_to`, `effective_date`
   - `event_windows` — Excel `행사날짜` 등 표 컬럼에서 추출한 복수 구간
   - `topic_key` + `version_of` — 동일 주제 개정 체인
2. **결정적 시간 필터** (`temporal/query.py`) → 후보 카드 축소
   - `active_on` — 특정일 유효한 판촉/행사
   - `posted_between` / `window_around` — 게시일 구간 (한두 달 전 공지)
   - `observable_on` — 그 시점에 이미 게시·적용 중이던 내용
   - `version_pairs` — 이전 버전 대비 변경 (diff 설명은 LLM)
3. 담당·상품코드 필터 + embedding top-k → LLM 답변 + `provenance` 첨부 인용
4. VLM 복구 시 ImageNote → ContentSlice 보강

### Q&A 테스트 패널 (Phase 2a — 구현됨)

```bash
# .env.example → .env 복사 후 OPENAI_API_KEY 설정
python scripts/serve_parse_viewer.py --port 8765 --as-of 2026-06-17
# → http://localhost:8765/qa
```

- `POST /api/qa/ask` — MCP-style 파이프라인: intent → 담당 → 시기 → retrieve → 첨부 → 답변
- `GET /api/qa/damdangs`, `GET /api/qa/status`
- Tool 트레이스 UI (디버그)
- Stdio MCP: `python scripts/run_qa_mcp_server.py --as-of 2026-06-17`
- CLI smoke: `python scripts/test_qa_openai.py --as-of 2026-06-17 "질문..."`
