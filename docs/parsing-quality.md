# Parsing quality (PDF · PPTX · XLSX)

2026-07 개선 사항과 품질 측정 방법.

## 변경 요약

### PDF (`ingestion/parse_pdf.py`)
- **하이브리드 페이지**: 네이티브 텍스트가 얇고(<200자) 이미지가 페이지의
  30% 이상을 덮는 페이지는 이미지 영역만 잘라 OCR(`[이미지 OCR]` 접두)하여
  네이티브 텍스트·표와 **병합**한다 (10% 미만 로고성 이미지는 무시).
  전체 페이지 OCR로 인한 텍스트 중복이 없다. `extraction="ocr"`,
  `raw.hybrid=true`.
- **표 보존**: 스캔 페이지에서 OCR이 동작해도 추출된 표를 버리지 않고 병합.
- **플래그 가시성**: OCR 불가/실패로 본문이 비어도 `review_flag`가 있으면
  레코드를 유지한다 (뷰어·리포트에서 확인 가능, VLM 파이프라인이 source_ref로
  본문을 보강 가능).
- 표 추출 예외는 조용히 삼키지 않고 경고 로그를 남긴다.

### PPTX (`ingestion/parse_pptx.py`)
- **이미지 전용 슬라이드**: 기존에는 보일러플레이트 길이 체크에 걸려 조용히
  누락됐다(`pptx_image_only` 분기는 데드 코드였음). 이제 그림만 있는 슬라이드는
  `review_flag="pptx_image_only"` 레코드로 남는다. 본문은 그림 대체 텍스트
  (descr, 파일명 자동값 제외)이며 없으면 빈 문자열 — 다운스트림 VLM 설명이
  source_ref로 채울 수 있도록 비워 둔다.
- **읽기 순서**: 같은 시각적 행(약 5mm)에 있는 도형은 좌→우로 정렬
  (기존 버킷이 너무 촘촘해 사실상 top 순 정렬이었음).
- 한계: 파일이 없어 `record.pages` 텍스트로만 복원하는 경로에서는 그림 정보가
  없어 이미지 전용 슬라이드를 감지할 수 없다.

### XLSX (`ingestion/parse_xlsx.py`)
- 프로필 미매칭 파일: 블롭 폴백 이전에 **휴리스틱 행 추출**을 시도한다
  (자세한 조건은 `docs/excel-profiles.md` 참고).
- 블롭 폴백은 빈 행/열을 제거해 노이즈를 줄인다.
- 행 수는 테이블당 `_MAX_ROWS_PER_TABLE`(250)로 항상 제한.

## 품질 측정

- `python scripts/parse_quality_report.py` — `data/parsed`를 정규화해
  review_flag / extraction 분포를 `data/parsed/_quality/report.json`에 기록.
- 뷰어 `/quality` 페이지 — 같은 리포트를 웹에서 확인 (플래그된 레코드 목록 포함).

## 개선 전/후 비교 (보류)

이 환경의 `data/`는 비어 있어 실데이터 전/후 비교는 실행하지 못했다.
실데이터가 있는 환경에서:

1. 개선 전 코드로 `python scripts/parse_quality_report.py --out before.json`
2. 개선 후 코드로 다시 실행해 `flagged_ratio` 및 플래그별 분포를 비교

기대 효과: `xlsx_fallback` 감소(휴리스틱 행 승격), `pptx_image_only` 신규 표기
(기존 누락분 가시화 — 플래그 증가는 품질 저하가 아니라 누락 발견), PDF 본문
커버리지 증가(하이브리드 OCR·표 보존).

주의: 프로필 미매칭 엑셀의 source_ref 형태가 `#sheet:이름` → `#row:시트:키`로
바뀌므로, 과거 코퍼스를 재처리하면 `link_card_versions` 시계열 연결과 VLM 인덱스
조회가 새로 시작된다 (전체 파이프라인 재생성 시에만 재처리 권장).
