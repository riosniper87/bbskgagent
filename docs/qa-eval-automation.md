# QA Eval Loop — Cursor Automation

이 문서는 **Cursor Automations**에서 주기적으로 QA eval을 실행하고, 실패 시 수정 PR을 생성하는 설정 가이드입니다.

## 선행 조건

1. `store-brief` 변경사항을 **git commit & push** (Automation은 committed 파일만 참조)
2. `OPENAI_API_KEY`가 Automation 실행 환경에 설정
3. `data/llmwiki/{as_of}/llmwiki.json` 빌드 완료
4. Agents Window에서 Automation 생성

## Trigger

| 항목 | 값 |
|------|-----|
| 유형 | Cron |
| 스케줄 | 평일 09:00 (또는 llmwiki rebuild 직후) |
| Repo | store-brief |

## Tools

- git (checkout, branch, commit, push)
- PR create
- (선택) Slack 알림

## Automation Instructions (프롬프트)

아래를 Automation instructions에 붙여넣으세요.

```
당신은 store-brief QA eval 루프를 실행하는 에이전트입니다.

1. 저장소 루트에서 eval 실행:
   python scripts/run_qa_eval.py --as-of 2026-06-17 -n 30 --seed 42 --threshold 0.85

2. data/eval/2026-06-17/*/report.json 중 최신 run의 overall_pass_rate 확인.

3. pass rate >= 85%:
   - PR comment 또는 Slack으로 요약만 보고 (pass rate, hit@1, attachment, answer rates)
   - 종료

4. pass rate < 85%:
   - data/eval/*/failures.jsonl 및 report.json의 failure_type별 top 3 분석
   - 각 실패의 suggested_prompt 참고
   - 최소 수정만 적용 (해당 파일만):
     * corpus_gap → src/store_brief/llmwiki/from_parsed.py
     * retrieval_miss → src/store_brief/qa/tools/retrieve.py, intent.py, routing.py
     * attachment_mismatch → retrieve.py anchor_source_ref, citations
     * answer_quality → src/store_brief/qa/tools/answer.py
   - pytest tests/test_qa_*.py 실행
   - python scripts/run_qa_eval.py --as-of 2026-06-17 -n 10 --seed 42 재실행
   - 개선되면 fix/qa-eval-{날짜} 브랜치에 커밋 후 PR 생성

5. PR 제목: fix(qa): eval regression — {주요 failure_type}
   PR 본문:
   - Before/after pass rate
   - 실패 케이스 2~3개 요약
   - 수정 rationale
   - Test plan: pytest + run_qa_eval -n 10

6. 자동 머지하지 말 것 — 사용자 검토 대기.
```

## 검색 인덱스 버전 (INDEX_VERSION=2)

BM25 검색 인덱스가 v2로 올라갔습니다 (한국어 조사 제거 + 원형/변형 dual-emit 토큰화).
저장된 v1 인덱스는 로드 시 자동으로 거부되고 corpus에서 재빌드되므로 별도 마이그레이션은
필요 없지만, 디스크에 캐시된 인덱스를 쓰는 파이프라인이라면 첫 실행에서 재빌드 비용이
한 번 발생합니다. 강제 재빌드하려면 기존 `data/index/{as_of}/search_index.pkl` 파일을 삭제하면 됩니다.

## 로컬 수동 실행

```bash
cd store-brief
# 일괄 실행 (eval + summary + canvas)
python scripts/qa_loop.py --as-of 2026-06-17 -n 30

# llmwiki/KG 재빌드 후 eval
python scripts/qa_loop.py --as-of 2026-06-17 --rebuild-llmwiki --rebuild-kg -n 30

# PowerShell
.\scripts\qa_loop.ps1 -AsOf 2026-06-17 -NCases 30

# eval만 (기존)
python scripts/run_qa_eval.py --as-of 2026-06-17 -n 10 --seed 42
python scripts/run_qa_eval.py --as-of 2026-06-17 -n 30 --promote  # 회귀 케이스 승격
pytest tests/test_qa_eval.py tests/test_qa_intent.py tests/test_qa_eval_regression.py -q
```

## 대시보드

eval 실행 후 `data/eval/summary.json`이 갱신되고 Canvas가 자동 재생성됩니다:

`C:\Users\4250090\.cursor\projects\c-Users-4250090-Documents-anaylsis\canvases\qa-eval-dashboard.canvas.tsx`

## Troubleshooting 프롬프트

실패 케이스의 `suggested_prompt` 필드를 Cursor 채팅에 붙여넣으면 수동 디버깅도 가능합니다.

report.json 경로 예:
`data/eval/2026-06-17/{run_id}/report.json`
