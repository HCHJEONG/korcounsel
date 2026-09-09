# KorCounsel

공개 한국 판례를 재현 가능하고 원출처까지 추적 가능한 **Legal Issue Unit**으로 만드는 데이터 생산·검수 웹 앱입니다.

국가법령정보 공동활용 OPEN API에서 판례를 수집하고, 판시사항·판결요지·판결이유·인용을 구조화하여 쟁점–답변–근거를 연결합니다. 자동 검증 결과와 사람의 검토 결과를 구분하며 원본과 변경 이력을 보존합니다.

> 현재 상태: 설계 및 문서 준비 단계입니다. 앱, CLI, DB schema, 배포 스크립트와 AWS 예약은 아직 구현하지 않았습니다. 아래 구성과 명령은 구현 목표이며 현재 실행 가능한 기능 목록이 아닙니다.

## 문서 안내

| 문서 | 역할 |
| --- | --- |
| [PLAN.md](PLAN.md) | 확정 범위, 단계별 구현 계획, 검증·완료 기준, AWS 운영 결정 |
| [AGENTS.md](AGENTS.md) | 에이전트 작업 지침, 아키텍처 경계, 데이터·배포·검증 원칙 |
| [DESIGN.md](DESIGN.md) | 화면 구조, 색상, 검색·검수·작업 UX, 접근성과 상태 표현 |

AGENTS.md와 DESIGN.md는 인접 `onju-ai-kr`의 문서를 참고해 이 프로젝트에 맞게 재구성했습니다. 참조 프로젝트의 구현 완료 기록과 운영 환경을 이 프로젝트의 상태로 간주하지 않습니다.

## 제품 범위

Phase 1:

- 공식 API 판례 100건 이상 실제 수집과 원본 JSON/XML 보존
- 사건번호·법원·날짜 정규화, 판례 구조 및 참조조문·참조판례 추출
- 판시사항과 판결요지의 결정론적 alignment
- evidence 위치, provenance 및 검증 결과를 가진 LegalIssueUnit 생성
- JSONL·Parquet export, dataset manifest, 재실행·중복 방지
- 인증된 소수 사용자용 웹 대시보드와 판례·쟁점 검수 화면
- 웹에서 작업 등록·진행 조회, 별도 worker 실행, CLI 재현 경로

Phase 1.5에는 쟁점 연결 수정, 근거 재선택, 승인·반려·보류, 검토 이력 및 실행 간 비교를 추가합니다.

초기 범위에는 LLM 호출, 모델 학습, GPU, RAG, vector database, Elasticsearch, 공개 회원가입, 공개 판례 서비스 및 HTML 페이지 scraping이 포함되지 않습니다. 이 앱은 데이터 생산과 전문 검토를 보조하며 법률 판단을 대신하지 않습니다. 자동 검증 통과는 법률적 정확성 보증이나 사람의 승인이 아닙니다.

## 데이터 흐름

```text
공식 판례 API
  → RAW: 원본 바이트·수집 정보·hash
  → NORMALIZED: 식별자·metadata·텍스트 정규화
  → STRUCTURED: 판시사항·요지·이유·인용 및 원문 위치
  → LegalIssueUnit 후보: 쟁점 / 답변 / evidence / authority / provenance
  → 검증·검토 대상 분류
  → GOLD: 포함 정책을 통과한 JSONL·Parquet + manifest
```

- 원본 바이트 hash와 원문 텍스트 offset을 구분합니다. evidence는 기준 텍스트와 `[start, end)` 구간을 식별합니다.
- `aligned`, `ambiguous`, `unmatched`는 연결 상태입니다. 자동 품질 검증과 사람의 검토 상태는 별도입니다.
- 번호·구조가 모호하면 추측하지 않습니다. 실패·미연결 자료도 보고서와 후보에 남깁니다.
- 판결요지 기반 근거와 판결이유까지 연결한 근거를 구별합니다.
- 반복 실행은 같은 입력·규칙·설정에 대해 안정적인 ID와 결과를 생성해야 합니다.

## 확정 기술 스택

| 계층 | 선택 |
| --- | --- |
| 프런트 | React 19 + Vite + TypeScript, 정적 SPA |
| API | FastAPI + ASGI 서버 |
| 처리 | Python 3.12, 별도 worker 1개부터 시작 |
| Python 패키지 관리 | uv, pyproject.toml, uv.lock |
| DB | 동일 EC2의 PostgreSQL |
| 파일 | 원본 JSON/XML, 단계별 artifact, JSONL·Parquet |
| API 계약 | FastAPI OpenAPI와 명시적 Pydantic schema |
| 검증 | pytest, pytest-cov, ruff, mypy 및 프런트 타입·lint·build·브라우저 검증 |

세부 패키지 버전, Node.js, 프런트 패키지 관리자, 라우터·조회 도구, DB driver·접근 도구·migration 도구, HTTPS 서버는 구현 시 호환성을 확인해 고정합니다. Next.js는 사용하지 않습니다. 프런트는 로컬 또는 CI에서 빌드해 정적 결과를 배포합니다.

## 실행 구조

```text
브라우저 → https://korcounsel.com → HTTPS 웹 서버
  ├─ /       → React 정적 파일
  └─ /api/*  → FastAPI → PostgreSQL ← Python worker
                                        ↓
                                  pipeline core
                                        ↓
                                 원본·dataset 파일

CLI → 동일 core 및 작업 상태 관리
EventBridge Scheduler → EC2 시작 / 종료 준비 제어
```

FastAPI는 인증·조회·작업 등록을 담당합니다. 긴 작업은 HTTP 요청이나 BackgroundTasks에서 실행하지 않고 PostgreSQL에 등록한 뒤 worker가 처리합니다. API 프로세스와 처리 worker는 각각 1개로 시작합니다.

PostgreSQL에는 사용자·세션, 작업 queue·실행 이력, 조회용 판례·쟁점·근거, dataset 참조 및 향후 검토 기록을 저장합니다. 원본과 재현 artifact는 파일로 보존하며 DB에 위치·hash·버전을 연결합니다. DB와 파일을 함께 복구할 수 있도록 백업을 설계합니다.

## 저장소 구조

현재는 루트 문서와 배포용 디렉터리를 준비했으며, 다음 코드 구조를 목표로 합니다.

```text
README.md / AGENTS.md / DESIGN.md / PLAN.md
pyproject.toml / uv.lock / .python-version     # 구현 시 생성
src/klegal_gold/
  domain/ / sources/ / normalize/ / parse/ / segment/
  pipeline/ / validate/ / storage/ / web/ / jobs/ / db/
frontend/                                    # React/Vite 앱
migrations/                                  # PostgreSQL schema 이력
tests/fixtures/ / unit/ / integration/ / regression/
data/raw/ / normalized/ / structured/ / gold/
docs/                                        # 구현·배포·운영 상세 문서
scripts/                                     # 로컬 개발·수집·유지보수
.fordeploy/                                  # 배포 스크립트·설정
  aws-backup/
    .gitkeep
```

`.fordeploy/aws-backup/`은 로컬 배포 자료와 백업 준비 공간입니다. 현재 `.gitkeep`만 만들며 실제 환경파일·DB dump·이미지 archive는 생성하지 않습니다. 해당 폴더 생성은 실제 AWS 백업 구성을 완료했다는 뜻이 아닙니다.

## 로컬 개발 — 구현 후 사용할 경로

현재 `pyproject.toml`, 프런트 package.json, migration 및 CLI가 없으므로 아래 명령은 아직 실행할 수 없습니다.

구현 시 Python 3.12, uv, 고정된 Node.js·프런트 패키지 관리자, 격리된 개발 PostgreSQL을 준비합니다. 환경 설정에는 `LAW_OPEN_API_OC`, `DATABASE_URL`, `DATA_DIR`, `LOG_LEVEL`, 인증·세션 설정이 포함됩니다. `.env.example`에는 비밀값 없는 예시만 작성합니다.

DB 초기화/migration 후 실행할 목표 데모:

```bash
uv sync --locked
uv run klegal fetch --limit 100
uv run klegal normalize
uv run klegal structure
uv run klegal build-gold
uv run klegal validate
uv run klegal stats
```

목표 Python 검증 명령:

```bash
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=klegal_gold
```

unit은 외부 서비스 없이, DB integration은 격리된 실제 PostgreSQL에서 실행합니다. 공식 API live 검증은 별도로 수행합니다. 프런트는 타입·lint·핵심 UI 테스트·production build·로그인부터 원문 검수까지의 브라우저 흐름을 검증하며 구체적 명령은 scaffold 시 문서화합니다.

## 배포·운영 방침

- 도메인: 사용자가 확보한 `korcounsel.com`. DNS·HTTPS 연결과 실제 서비스 배포는 아직 미확인입니다.
- 서버: 기존 `ssh aws-bastion` 대상 EC2. 신규 EC2 증설을 기본안으로 삼지 않습니다.
- 크기: 사용자 설명상 현재 micro. 실제 계열·부하 확인 후 호환되는 small로 변경하고 부족하면 medium을 검토합니다.
- 웹·FastAPI·PostgreSQL·worker를 같은 EC2에서 운영하고 DB/worker 포트는 외부에 공개하지 않습니다.
- 한국 시간 `Asia/Seoul` 월~금 10:00 시작, 17:00 종료 준비. 토·일은 자동 시작하지 않으며 평일 공휴일은 운영합니다.
- 17:00부터 새 작업 접수·대기 작업 실행을 막고 진행 작업 완료 또는 체크포인트 저장 후 중지합니다. 실제 종료는 늦어질 수 있습니다.
- 중지 중에는 웹과 해당 bastion을 경유한 SSH를 사용할 수 없습니다. 기존 서버의 관리 접속·네트워크 역할을 확인한 뒤 예약을 적용합니다.
- 중지 후에도 EBS·보유 Elastic IP·백업 비용이 남습니다. 실제 요금은 배포 시 산정합니다.

배포 자료는 `.fordeploy/`, 설명과 명령 인계는 이 README 및 구현 후 `docs/deployment.md`, `docs/operations.md`에 둡니다. 최초 배포 전 인스턴스 ID·리전·계열, 기존 서비스·포트, DNS·고정 IP, runtime 경로, 데이터 영속 위치, migration·백업·복구 및 인증을 확인합니다.

배포 절차는 준비·검증·적용·health 확인·복구를 구분합니다. API health는 `/api/health`를 기본 목표로 하고 웹 파일 제공, DB 연결, worker 상태도 각각 확인합니다. 재배포 시 DB 볼륨·원본·검토 이력·실제 환경파일을 덮어쓰지 않습니다. 구체적 배포 명령은 스크립트 구현과 로컬 검증 후 추가합니다.

## 참고 저장소와 자료 정책

- `I:\VSCodeBases` 아래 `web2df`, `df2preproc`: 실제 루트 확인 후 식별자·파싱·정규화 규칙을 분석합니다. 신규 core의 import dependency로 연결하지 않습니다.
- 인접 `onju-ai-kr`: AGENTS/DESIGN의 작업·검수·시각·배포 원칙을 참고했습니다. 해당 프로젝트의 계정·도메인·데이터·AI 기능은 이전하지 않습니다.
- 공개 법률 자료도 출처·수집 시각·사용 조건을 기록합니다. 코드 라이선스와 원천 데이터 재배포 조건은 별도 확인하며 현재 임의의 오픈소스 라이선스를 선언하지 않습니다.
- 인증정보·환경파일·DB dump·원본 대량 데이터는 Git과 이미지에 넣지 않습니다. 소규모 fixture는 출처와 사용 가능 범위를 기록합니다.
