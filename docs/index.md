---
layout: default
title: bbskgagent / store-brief
---

# bbskgagent / store-brief

매장 사내 게시판과 담당 R&R을 바탕으로  
**담당별 업무 브리핑 · llmwiki · QA 검색**을 만드는 프로토타입입니다.

[GitHub 저장소](https://github.com/riosniper87/bbskgagent) · [README](https://github.com/riosniper87/bbskgagent#readme)

---

## 파이프라인

```
ingest → parse → llmwiki(+상품코드 라우팅) → BM25 index
                                        └→ viewer (parse / qa / kg)
```

| 단계 | 역할 |
|------|------|
| **Parse** | Excel / PPTX / PDF 행·슬라이드 정규화 (YAML 프로필) |
| **llmwiki** | 담당자별 카드 corpus |
| **QA** | BM25 검색 + (선택) LLM 답변 |
| **KG** | 출처·담당·테마 그래프 |

날짜·담당 매칭은 **결정적 코드**, LLM은 추출·요약·문장만 담당합니다.

---

## Knowledge Graph 온톨로지

![llmwiki Knowledge Graph Ontology](assets/ontology.svg)

게시글 → 첨부 → 슬라이스 → **WikiCard**, 그리고 Product / Damdang / Keyword로 분기합니다.

---

## Q&A 화면 예시

![Q&A 패널 예시](assets/qa-example.png)

질문 · 담당 · 기준일 입력 후 **질문하기** / **검색만**.  
답변 · 참조 · 검색 카드 · Tool 트레이스가 한 화면에 표시됩니다.

---

## 빠른 시작

```bash
git clone https://github.com/riosniper87/bbskgagent.git
cd bbskgagent
cp config/settings.example.yaml config/settings.yaml
cp .env.example .env
pip install -e ".[viewer]"
python scripts/serve_parse_viewer.py --port 8765
```

- 뷰어: `http://localhost:8765`
- QA: `http://localhost:8765/qa`
- KG: `http://localhost:8765/kg`

실데이터는 Git에 없습니다. 코드만 pull하고 데이터는 PC별로 준비합니다.

---

## 문서

- [진행 정리 (PROGRESS)](PROGRESS.md)
- [Git 설정 · 민감정보](GIT_SETUP.md)
- [Excel 프로필](excel-profiles.md)
- [파싱 품질](parsing-quality.md)
- [QA Eval 자동화](qa-eval-automation.md)

---

## 상태 (요약)

- Excel 행 단위 프로필 ingestion
- BM25 영구 인덱스 + QA retrieval soft-boost
- PDF/PPTX/XLSX 파싱 품질 게이트
- 로컬 FastAPI 뷰어 (parse / qa / kg / quality)
