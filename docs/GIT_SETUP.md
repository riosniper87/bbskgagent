# Git 업로드 가이드 (민감정보 제외)

store-brief는 **코드·프로필·테스트·문서**만 Git에 올리고, **회사 데이터·DB·키**는 로컬에만 둡니다.

---

## 1. 커밋해도 되는 것

- `src/` — 전체 애플리케이션 코드
- `scripts/` — CLI
- `tests/` — pytest (일부는 `data/parsed` 샘플 필요 → skip 처리됨)
- `config/*.example.*`, `config/categories.yaml`, `config/team_damdang_map.yaml`, `config/extract_info.sql`
- `src/store_brief/ingestion/profiles/*.yaml` — Excel 레이아웃 (파일명 패턴만, 실제 파일 없음)
- `docs/` — PROGRESS, excel-profiles, qa-eval 등
- `pyproject.toml`, `README.md`, `.gitignore`, `.env.example`

## 2. 절대 커밋하면 안 되는 것

| 경로 | 이유 |
|------|------|
| `.env` | OpenAI API 키 |
| `config/settings.yaml` | 내부 vLLM IP (`10.x.x.x`) |
| `config/cat.txt` | HISIS 품목·팀·분류담당 전체 마스터 (~4800행) |
| `data/raw/` | 게시판 원본·첨부 (사내 공문) |
| `data/parsed/` | 파싱 결과 (상품명·가격·지점) |
| `data/llmwiki/` | QA corpus 본문 |
| `data/cache/hisis_*.json` | DB 조회 캐시 |
| `data/index/` | 검색 인덱스 |
| `data/eval/` (실행 결과) | 실제 게시글 제목·질문이 포함된 report |
| `../AS/`, `../infra/.env` | Oracle DB 자격증명 (별도 프로젝트) |

> **주의:** 이전 `.env.example`에 실 API 키가 들어가 있었음 → placeholder로 교체함.  
> 이미 외부에 push한 적이 있다면 **OpenAI 키 즉시 rotate** 필요.

---

## 3. 새 PC / clone 후 설정

```powershell
cd store-brief
copy config\settings.example.yaml config\settings.yaml
copy config\cat.txt.example config\cat.txt    # 또는 사내 export로 교체
copy .env.example .env                       # OPENAI_API_KEY 입력

pip install -e ".[viewer]"
# data/raw 는 별도 준비 (scripts/prepare_raw.py)
```

HISIS Oracle (선택):

- SSH 터널 → `127.0.0.1:15211`
- `../infra/.env` 에 Oracle user/password (store-brief repo 밖)
- `python scripts/hisis_connect.py --ping`

---

## 4. Git 초기화 · push (최초 1회)

```powershell
cd c:\Users\4250090\Documents\anaylsis\store-brief

git init
git add .
git status   # cat.txt, data/raw, .env 가 없는지 확인!

git commit -m "Initial commit: store-brief prototype (no internal data)"

# GitHub/GitLab 원격 생성 후
git remote add origin https://github.com/YOUR_ORG/store-brief.git
git branch -M main
git push -u origin main
```

`git status`에서 아래가 **untracked 또는 ignored** 여야 안전합니다:

- `config/cat.txt`
- `config/settings.yaml`
- `data/`
- `.env`

---

## 5. push 전 체크리스트

- [ ] `git status`에 `.env`, `cat.txt`, `data/raw` 없음
- [ ] `config/settings.yaml` 대신 `settings.example.yaml`만 staged
- [ ] OpenAI / Oracle 키가 코드·문서·example에 없음
- [ ] `grep -r "10\.154\." .` 내부 IP 잔존 확인 (settings.yaml은 ignore)

```powershell
git check-ignore -v config/cat.txt data/raw .env
```

---

## 6. Private vs Public repo

| | Private repo | Public repo |
|--|--------------|-------------|
| team_damdang_map.yaml | 보통 OK | 팀명 일반화 검토 |
| extract_info.sql (SC011M) | OK | 테이블명 노출 주의 |
| ingestion profiles | OK | 파일명 패턴에 업무 힌트 |
| docs/ocr-parse-samples.json | real post_id 있음 — 검토 | sanitize 권장 |

**권장:** 사내 GitLab **Private** repository.

---

## 7. 관련 문서

- [PROGRESS.md](./PROGRESS.md) — 기능·Phase 진행 상황
- [excel-profiles.md](./excel-profiles.md) — Excel YAML 카탈로그
- [../data/README.md](../data/README.md) — data 폴더 구조
