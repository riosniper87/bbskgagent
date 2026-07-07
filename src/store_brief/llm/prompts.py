"""Prompt skeletons.

These are deliberately skeletal — the structure (inputs, required JSON shape, constraints)
matters more than wording at this stage. Tighten with few-shot examples once we see real
gemma-4 outputs. Every JSON-returning prompt must say 'JSON만 출력' explicitly.

{categories} is injected from config/categories.yaml so the model is constrained to the
known product-category vocabulary plus '기타'.
"""

# --- 1. Event extraction (post + parsed attachments -> typed events) -----------------
EXTRACT_EVENTS_SYSTEM = """너는 가전 유통사 사내 게시판을 구조화하는 도우미다.
글과 첨부 요약을 읽고, 매장 직원이 알아야 할 항목을 '이벤트' 단위로 분리해 추출한다.
날짜는 ISO(YYYY-MM-DD) 문자열 또는 null. 카테고리는 아래 목록에서만 고른다(없으면 "기타").
허용 카테고리: {categories}
type은 판촉|이벤트|정책|공지|가격_재고|기타 중 하나.
branches는 "전점" 또는 특정 지점명 배열.
각 event는 게시글 본문 또는 첨부에 실제로 등장하는 주제만 담아라. 첨부에 없는 품목/주제를 추측해 넣지 마라.
events 배열에 결과를 담아 JSON으로 출력한다."""

EXTRACT_EVENTS_USER = """[게시글]
제목: {title}
작성일: {posted_date}
본문:
{body}

[첨부 요약]
{attachments}

예시) 판촉 게시글 → events에 type=판촉, valid_from/valid_to 채움.
예시) 전사 공지 → branches=["전점"].
events 배열을 포함한 JSON만 출력."""

# --- 2. Theme classification (lightweight, anchored to category vocab) ---------------
CLASSIFY_THEME = """다음 항목에 가장 알맞은 짧은 테마 라벨(2~5어절)을 하나 지어라.
가능하면 카테고리({categories}) 흐름과 일관되게. 라벨만 출력.
제목: {title}
요약: {summary}"""

# --- 3. Vision: describe an image; if it is a table, also extract structure ----------
VISION_DESCRIBE = """이 이미지를 한국어로 간결히 설명하라. 종류(kind)를 분류하라
(사진/표/차트/포스터/도식/기타). 표 또는 차트면 table에 columns와 rows를 채워라.
table이 없으면 table은 null."""

TABLE_LAYOUT_FROM_IMAGE = """이 이미지는 Excel 시트 캡처이다. 표 영역의 구조만 JSON으로 추출하라.
값 전체를 복사하지 말고, raw grid 행/열 인덱스(0부터)로 레이아웃을 지정한다.

규칙:
- header_rows: 헤더에 해당하는 행 번호 배열 (다단 헤더면 여러 행)
- data_start_row: 데이터가 시작하는 행 번호
- columns: 논리 컬럼명 (병합 헤더는 "기초 / 3월말" 형태)
- col_indices: 각 논리 컬럼이 가리키는 raw grid 열 인덱스
- 한 시트에 표가 여러 개면 regions에 여러 항목
- 확신이 낮으면 needs_review=true

아래는 같은 시트의 raw grid 상단 스니펫(참고용)이다:
{grid_snippet}

파일명: {filename}
시트명: {sheet_name}
JSON만 출력."""

# --- 6. Report prose (structured section -> Korean HTML-ready prose) -----------------
REPORT_SECTION = """아래 항목들을 담당 품목 직원용 일일 브리핑 문단으로 작성하라.
담당 카테고리와 날짜를 명확히. 과장 없이 간결한 존댓말.
HTML 본문에 들어갈 문장들만 출력(머리말/마크다운 금지).
[섹션] {section_title}
[기준일] {as_of}
[항목]
{items}"""

REPORT_SECTION_MANAGER = """아래 항목들을 매장 점장용 일일 브리핑으로 작성하라.
품목별 세부보다 지점 전체 운영·당일 처리할 일 위주로 쉽게 설명하라.
사실만, 날짜를 명확히. 간결한 존댓말.
HTML 본문에 들어갈 문장들만 출력(머리말/마크다운 금지).
[섹션] {section_title}
[기준일] {as_of}
[항목]
{items}"""

# --- 4. Policy diff (old vs new policy -> what changed) ------------------------------
POLICY_DIFF = """아래 두 정책 내용을 비교해, 무엇이 바뀌었는지 직원 관점에서
핵심만 2~4문장으로 설명하라. 새로 생긴 의무/금지/예외를 우선 짚어라.
[이전]
{old}
[현재]
{new}"""

# --- 5. Rerank (R&R + candidate events -> relevance ranking) -------------------------
RERANK = """직원 R&R과 후보 항목들이 주어진다. 이 직원의 6/17 업무에
실제로 중요한 순서대로 항목 id를 정렬하고, 무관한 것은 제외하라.
[직원] 지점:{branch} / 점장:{is_manager} / 담당:{categories}
[후보]
{candidates}
JSON 배열(id 문자열)만 출력."""
