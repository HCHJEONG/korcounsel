# KorCounsel

전체 import 전 [text 파일 포함 관계 점검](docs/legacy-text-coverage-audit.md)을 완료했습니다. 8,482개 파일을 대조했으며 2029039 재결의 기존 행 연결·종류 표기는 별도 검토 대상입니다.

기존 pickle의 DataFrame을 재사용하는 FULL_ROW importer를 구현했습니다. 본문·보강 HTML을 포함한 전체 컬럼을 행 파일로 export하고 단일 worker가 보존·격리·재개합니다. [실행 안내와 실제 표본 검증](docs/legacy-full-row-import.md)을 참고하세요.

현재 재판결과 키(법원 명칭+사건번호+재판 종류), 출처 독립 canonical 등록, legacy mapper 0.2.0과 로컬 migration 0007을 구현했습니다. [사용 계약·검증·다음 단계](docs/decision-identity-implementation.md)를 참고하세요. 전체 corpus import와 자동 동일성 판정은 후속입니다.

공개 한국 판례를 출처·원본·변경 이력까지 추적 가능한 쟁점 데이터로 생산하고 검수하는 비공개 웹 앱입니다.

현재 **Step 1·Step 2 데이터 계약·Step 2A 로컬 저장/worker 검증 완료** 상태입니다. 프런트 개발 화면, FastAPI health, 설정 검증 CLI, PostgreSQL 연결 및 Compose 구성이 동작합니다. PostgreSQL migration, 기록 저장, 식별 연결 이력과 단일 worker가 동작합니다. 로그인·실제 판례 수집·자동 canonical 매칭·gold 생산은 아직 구현하지 않았습니다. AWS 배포·도메인·운영 예약도 아직 적용하지 않았습니다.

legacy 보존 모델은 과거 취득시각·HTTP hash를 만들지 않고 기존 필드와 행 locator를 유지합니다. 실제 metadata 15행과 저장 HTML 4개를 검증했으며 전체 corpus/DB import는 후속입니다. [import 계약과 표본 재현](docs/legacy-import-contract.md)을 참고하세요.

저장·작업 실행·재시작 복구와 검증 범위는 [Step 2A 운영 안내](docs/persistence-and-jobs.md)에 있습니다.

## 폴더 원칙

README는 루트에 하나만 둡니다. 루트 React 프로젝트, backend/의 Python 프로젝트, 루트 compose.yaml, docs/와 .fordeploy/ 경계는 확정했습니다. 내부 모듈명·세분화는 변경 가능한 설계이며 필요한 단계에 추가합니다.

| 위치 | 역할 |
| --- | --- |
| src/ | React 19 + Vite + TypeScript |
| backend/src/klegal_gold/ | FastAPI·CLI·설정·DB, 후속 pipeline |
| backend/tests/ | Python 테스트와 기존 합성 fixture 53건 |
| tests/e2e/ | 실제 API 연동 desktop/mobile 브라우저 테스트 |
| docs/ | 설계·조사·개발 안내 |
| .fordeploy/ | Dockerfile·Nginx·배포 설정 |
| data/ | 로컬 원본·결과 파일, Git 제외 |

## 빠른 시작 — WSL/Linux

Node 24.16.0, pnpm 11.23.0, uv 0.12.5, Docker Compose가 필요합니다. Python 3.12는 uv로 준비합니다. Windows 작업 경로는 WSL의 `/home/hchjeong/IntelliJProjects/korcounsel`에 대응합니다.

```bash
pnpm install --frozen-lockfile
cd backend
uv sync --locked
cd ..
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml up -d --wait postgres
```

별도 터미널에서 백엔드와 프런트를 실행합니다.

```bash
# 터미널 1, 레포 루트
cd backend
uv run uvicorn klegal_gold.web.app:app --host 127.0.0.1 --port 8000 --reload
```

```bash
# 터미널 2, 레포 루트
pnpm dev
```

브라우저에서 http://127.0.0.1:5173 에 접속해 연결 확인을 누릅니다. Vite가 /api를 로컬 FastAPI로 전달합니다. 현재 개발 화면에는 실제 판례·인증 기능이 없습니다.

## Compose 전체 실행

```bash
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml build api web
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml run --rm migrate
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml up -d --wait api worker web
```

http://127.0.0.1:8080 에서 Nginx→FastAPI 연결을 확인합니다. api는 PostgreSQL 준비 후 시작하며 health는 API 생존 여부만 뜻합니다. postgres는 named volume, API/worker의 파일은 별도 case_data named volume을 사용합니다. 로컬 data/와 컨테이너 /data 볼륨은 별개의 저장소입니다.

```bash
# 실제 worker의 생존 확인
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml exec worker klegal ops worker-health
# 컨테이너 정리, DB·판례 볼륨은 보존
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml down
```

compose.env.example의 비밀번호는 폐기 가능한 로컬 개발 전용입니다. 운영에 사용하지 않습니다. 현재 포트는 localhost에만 열려 있으며 TLS·운영 secret·백업·자동 재시작과 배포 절차는 Step 11B에서 완성합니다. migration은 Step 2A에서 추가했으며 운영 DB 역할 분리·TLS는 후속입니다.

## 설정과 CLI

기본적으로 프로세스 환경변수만 읽습니다. `.env`를 자동 탐색하지 않습니다. 필요하면 절대 경로의 `KLEGAL_ENV_FILE`로 파일을 명시하고, 같은 이름의 프로세스 환경변수가 우선합니다.

```bash
cd backend
uv run klegal version
uv run klegal check-config
DATABASE_URL='postgresql://korcounsel:korcounsel_local_only@127.0.0.1:55432/korcounsel_dev' uv run klegal check-db
```

- LAW_OPEN_API_OC와 LAW_GO_KR_OC는 alias이며 값이 다르면 오류입니다. 실제 값은 출력하지 않습니다.
- 사용자가 제공한 .fordeploy/aws-backup/.env는 그대로 보존하며 이번 scaffold 검증에 로드하지 않았습니다.
- DATA_DIR은 절대 경로입니다. 로컬 기본값은 레포 data/이며 작업 디렉터리 변경에 영향받지 않습니다. 설정을 읽는 것만으로 파일을 생성하지 않습니다.
- DATABASE_URL은 PostgreSQL 연결 문자열입니다. 미설정이면 health는 응답하지만 check-db는 실패합니다.
- root .env.example은 공개 프런트 설정 안내, backend/.env.example은 백엔드 설정 예시입니다. 프런트에 DB·API secret을 넣지 않습니다.

fetch/normalize/structure/build-gold/validate/stats는 후속 구현 명령입니다. 현재 CLI에 존재하지 않습니다.

## 검증

```bash
pnpm typecheck
pnpm lint
pnpm build
pnpm exec playwright install chromium
pnpm test:e2e
cd backend
uv run ruff check .
uv run ruff format --check .
uv run mypy
uv run pytest
```

기본 pytest는 local DB integration 1건을 건너뜁니다. 개발 PostgreSQL 실행 후 아래 명령은 실제 DB 테스트를 포함합니다.

```bash
KLEGAL_TEST_DATABASE_URL='postgresql://korcounsel:korcounsel_local_only@127.0.0.1:55432/korcounsel_dev' uv run pytest --cov=klegal_gold
```

최신 Python 검증: pytest 84건(로컬 PostgreSQL 포함), ruff·mypy 통과. Step 1 당시 UI 검증: desktop/mobile E2E 6건, 타입·lint·빌드·Compose 실행 통과. 기존 합성 fixture 53건 중 optional editorial 3종을 domain 테스트에 연결했습니다. 전체 parser/resolver 검증을 완료했다는 뜻은 아닙니다. 테스트 의존성의 upstream deprecation warning 2건이 관찰됐습니다.

## 설계·조사 문서

| 문서 | 내용 |
| --- | --- |
| [PLAN.md](PLAN.md) | 전체 단계·진행·완료 기준 |
| [AGENTS.md](AGENTS.md) | 작업 규칙 |
| [DESIGN.md](DESIGN.md) | 문서 중심 검수 UX |
| [architecture](docs/architecture.md) | 계층·폴더 경계 |
| [dataset schema](docs/dataset-schema.md) | 모델·결측·gold 계약 |
| [provenance](docs/provenance.md) | 원본·버전·evidence |
| [보강·증분 계승](docs/legacy-enrichment-and-incremental.md) | scourt 본문·이미지 주소·lawgo 조문 보강 및 미완료 재개 |
| [기존 corpus 조사](docs/legacy-corpus-bootstrap.md) | 89,130행·195행 층화 표본, 공식 ID·업무키 및 bootstrap 계획 |
| [identity](docs/case-identity.md) | source/canonical 식별과 연결 이력 |
| [incremental ingestion](docs/incremental-ingestion.md) | inventory·delta·refresh·재개 |
| [source fidelity](docs/source-fidelity.md) | 이미지·scan 탐지와 보존 단계 |
| [공식 API 계약](docs/law-open-api-contract.md) | 인증 alias·공식 자료·Step 0 실측 |
| [레거시 이전](docs/migration-from-legacy.md) | 규칙별 재사용·수정·폐기 |
| [identity·asset 조사](docs/legacy-case-identity-and-assets.md) | 실제 레거시 코드·8,482개 파일 관찰 |
| [개발 안내](docs/development.md) | 도구 선택·Compose 범위·후속 과제 |

Step 0의 네 API 요청 기록과 소스·표본 해시는 docs/step0/에 보존합니다. 실제 source 간 이미지 손실 비교와 PDF/scan 실물 검증은 아직 남아 있습니다.

## 목표 운영과 데이터 원칙

운영 대상은 기존 aws-bastion 한 대이며 micro→호환 small, 필요 시 medium을 검토합니다. korcounsel.com에서 인증된 소수 사용자가 접근하고 같은 EC2에 API·worker·PostgreSQL·정적 웹을 둡니다. 월~금 한국 시간 10시 기동, 17시 작업 접수 중단·checkpoint 후 중지를 구현할 예정입니다. 평일 공휴일은 운영하며 주말은 자동 시작하지 않습니다.

기존 약 9만 건을 초기 corpus로 계승하고 신규·변경분을 확장합니다. **contId·serialno는 출처 ID로 보존하고 신규 canonical ID는 출처와 독립적으로 발급합니다.** 기존 번호 미조회와 다른 번호 후보가 발견되어 공식 ID의 영구 안정성을 전제하지 않습니다. [정책 및 구현 대기 사항](docs/case-identity.md)을 따르며 UUID를 강제하지 않습니다. **법원명+사건번호**를 고유 업무키로 함께 유지하여 정부 ID 없는 LawnB 보유 판례에도 사용합니다. source ID·내용 버전·연결 revision의 역할과 원본 근거를 보존합니다. 판시사항·요지가 없거나 scan만 있어도 정상 판례로 수용합니다. gold에는 확실한 연결과 유효 evidence가 있는 쟁점만 포함하며 자동 검증과 사람 승인을 구분합니다. 이미지 탐지·참조 보존 뒤 취득·위치 복원·OCR를 순차 확장합니다. LLM·학습·GPU·OCR 해석은 초기 범위 밖입니다.

## 공식 출처 소량 수집 — Step 3

법제처 JSON/XML client와 현재 법원 포털 metadata·본문 수집을 단일 worker에 연결했습니다. klegal ops submit-law-detail / submit-scourt-detail은 request key를 유지해 조회·재시도합니다. 새 migration 0005가 필요합니다. [구현·실측·실행·남은 범위](docs/source-adapters.md)를 확인하세요. 사용자 확정에 따라 법제처 OC는 비밀값이 아니며 응답에 포함돼도 저장을 차단할 필요가 없습니다. OC 차단 제거와 JSON/XML 목록 재검증을 완료했고, 대량 수집은 아직 열지 않았습니다. 사용자 env는 검증에 명시적으로 사용했고 Compose에는 자동 전달하지 않았습니다.

현재 scourt 목록은 klegal ops submit-scourt-inventory로 제한 등록합니다. migration 0006이 필요하며 전체 목록 완전성을 뜻하지 않습니다. [현행 경로 변경·ID 후보·이미지 검증](docs/source-path-validation.md)을 확인하세요.
