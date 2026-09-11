# 관리자·편집자 두 계정 로그인 — 2026-09-11

**DB 설정 정리 완료 — 2026-09-11:** 사용자의 선택에 따라 실제 .env의 로컬 PostgreSQL 5개 항목만 기존 DB에 맞췄다. 이전의 포트·DB명 불일치는 해결됐으며 DATABASE_URL을 별도로 덮어쓸 필요가 없다. 지정 .env만으로 DB 접속과 두 계정 로그인을 확인했다. AWS 설정과 관리자·편집자 설정은 변경하지 않았다.

환경변수로 지정한 관리자 1개·편집자 1개 계정만 웹에 접근한다.

| 변수 | 용도 |
| --- | --- |
| KORCOUNSEL_ADMIN_ID | 관리자 아이디 |
| KORCOUNSEL_ADMIN_PASSWORD | 관리자 비밀번호 |
| KORCOUNSEL_DEV_EDITOR_ID | 편집자 아이디 |
| KORCOUNSEL_DEV_EDITOR_PASSWORD | 편집자 비밀번호 |

기존 DEV_EDITOR 변수명을 그대로 따른다. 두 아이디는 서로 달라야 하며 비밀번호는 기존 scrypt 정책에 따라 12~1024자다. 네 값 중 하나라도 누락·유효하지 않으면 로그인 경로를 닫는다. 루트 [.env.example](../.env.example)은 플레이스홀더 예제이며 실제 .env는 수정하지 않았다.

## 계정과 세션

- 웹의 SiteAccounts는 두 설정 아이디만 허용한다. 일반 Accounts/CLI로 만든 다른 DB 계정과 그 과거 세션은 웹 접근 권한을 얻지 못한다.
- 올바른 설정 비밀번호로 처음 로그인할 때 DB 계정을 만들고 scrypt hash만 저장한다. 기존 같은 아이디의 user_id와 이력을 유지하고 비활성 계정을 자동으로 되살리지 않는다.
- 설정 비밀번호 변경 시 기존 비밀번호와 세션을 거절한다. 새 비밀번호로 로그인하면 기존 세션을 폐기하고 DB hash를 갱신한다. 설정에서 빠진 아이디의 세션도 거절한다.
- 서버가 현재 설정에서 관리자/admin 또는 편집자/editor 역할을 결정한다. 현재 판례 조회는 두 역할이 함께 사용하며, 미래 편집·관리 권한을 구현했다고 주장하지 않는다.
- HttpOnly/SameSite=Strict cookie·Origin 확인·8시간 만료·logout·인증된 본문/이미지 제공을 유지한다. 비밀번호를 URL·브라우저 영속 저장소·정적 번들에 넣지 않는다.

## 실행 설정

Python은 지정한 환경파일만 읽는다. 저장 위치가 .fordeploy/aws-backup/.env이면 저장소 루트에서 아래처럼 명시한다. DATABASE_URL은 정리된 환경파일에서 읽는다. 아래 WEB_ORIGIN은 로컬 Vite 검증용 값이다.

```bash
export KLEGAL_ENV_FILE="$PWD/.fordeploy/aws-backup/.env"
export UV_PROJECT_ENVIRONMENT="$PWD/backend/.venv-reader"
export DATA_DIR="$PWD/data"
export LEGACY_PARQUET_PATH="$PWD/data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet"
export WEB_ORIGIN='http://127.0.0.1:5173'
uv run --directory backend uvicorn klegal_gold.web.app:app --host 127.0.0.1 --port 8000
# 별도 터미널에서 pnpm dev
```

초기 .env의 DB 주소/포트 불일치는 사용자의 선택에 따라 기존 DB를 유지하고 로컬 환경항목을 수정해 해결했다. 다른 DB에 migration하거나 기존 데이터베이스를 재생성하지 않았다. postgresql+psycopg:// 형식은 adapter에서 psycopg용 postgresql:// 형식으로 변환한다.

Compose는 --env-file로 입력한 네 계정 변수를 API 컨테이너에만 전달한다. worker·frontend build에는 넣지 않는다. WEB_ORIGIN은 정확한 브라우저 origin이며 Vite는 5173, 현재 Compose는 8080, 운영 HTTPS는 https://korcounsel.com이다. 새 코드·설정을 Compose에 반영하려면 API/web 재빌드·재기동이 필요하다. 이번 작업에서 AWS 배포는 하지 않았다.

첫 화면은 로그인 폼과 입력 플레이스홀더다. 미인증 상태에서는 검색·본문·이미지 목록을 불러오지 않는다. 로그인 후 서버가 확인한 역할과 기존 검수 화면을 보여준다. 직접 본문 링크도 먼저 로그인하며 logout 후 private 화면을 비운다.

## 검증

실제 .env의 관리자·편집자 계정으로 기존 로컬 개발 DB에서 로그인·역할·로그아웃을 확인했고 검증 세션은 폐기했다. 두 비밀번호가 프런트 build에 포함되지 않았음을 확인했다. 값은 보고서에 기록하지 않는다.

격리 PostgreSQL 테스트는 다른 계정·과거 세션 차단, 두 역할, 잘못된 비밀번호, 비밀번호/아이디 변경, 비활성 계정, 동시 첫 로그인, 설정 누락·중복을 검사한다. 브라우저는 desktop/mobile에서 랜딩·플레이스홀더·검색 숨김·두 역할 로그인·다른 계정 거절·logout 후 API 차단 및 기존 reader 흐름을 검사한다. 최종 Python/PostgreSQL 회귀 321개, desktop/mobile 브라우저 검사 6개가 통과했다. ruff·mypy·프런트 typecheck/lint/build와 플레이스홀더 기반 Compose config 검증도 통과했다.

