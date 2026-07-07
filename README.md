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

### 파싱 결과 뷰어 (로컬 웹)

```bash
cd store-brief
pip install -e ".[viewer]"
python scripts/serve_parse_viewer.py --port 8765
# → http://localhost:8765  (서버를 켠 상태에서 브라우저 접속)
```

`scripts/serve_parse_viewer.py`는 프로젝트 루트(`store-brief`) 기준으로 경로를 잡으므로, 위처럼 `store-brief`에서 실행하는 것을 권장합니다. 터미널에 `Uvicorn running on http://127.0.0.1:8765`가 보여야 정상입니다.

게시글 본문 + 첨부별 split-panel(슬라이드/시트 이미지 ↔ 파싱 텍스트·표·VLM 설명)을 브라우저에서 확인한다.

## 문서

- [docs/PROGRESS.md](docs/PROGRESS.md) — Phase별 진행 정리
- [docs/GIT_SETUP.md](docs/GIT_SETUP.md) — Git 업로드 시 민감정보 제외 가이드
- [docs/excel-profiles.md](docs/excel-profiles.md) — Excel ingestion YAML

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
  pipeline.py 일배치 오케스트레이션
  viewer/     파싱 결과 FastAPI 뷰어
```
