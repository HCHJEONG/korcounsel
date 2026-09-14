# KorCounsel

공개 한국 판례를 출처·원본·변경 이력까지 추적하며 검색하고 검수하는 비공개 업무 앱입니다. React·FastAPI·PostgreSQL·별도 worker를 한 저장소에서 관리합니다.

기존 **89,130행 전체**에 일반 검색의 보강 reader를 적용하고 전수 검증했습니다. scourt의 보존 HTML 구조에 본문 이미지 실물 **7,561위치**, lawgo 조문 내부 이미지 **4,698위치**를 연결했습니다. 저장된 조문 내용과 미취득·미연결·과거 보강 실패·적용 법령 버전 미확인 상태를 함께 표시합니다. [전수 결과와 남은 항목](docs/legacy-reader-scale.md), [화면·회귀 검증](docs/legacy-reader-scale-qa.md), [배치와 재개](docs/legacy-reader-batches.md)를 참고하세요. 모든 이미지 취득이나 법령 버전 확인이 완료됐다는 뜻은 아닙니다.

pickle은 동결 원본으로 유지하고, 전체 60컬럼 corrected Parquet과 기존 PostgreSQL FULL_ROW 보존 import를 계승합니다. 현재 검색은 `LEGACY_PARQUET_PATH`와 일치하는 완료된 PostgreSQL 검색 색인을 우선 사용하고, 준비되지 않은 경우 Parquet을 직접 읽으며, 이미지·보강 이력은 PostgreSQL과 공통 `data/`의 불변 파일에 연결됩니다. [보존·검색 계약](docs/legacy-full-row-import.md), [저장 루트 복구](docs/exact-blob-store-recovery.md)를 따릅니다.

환경변수로 지정한 관리자 1개·편집자 1개만 로그인할 수 있습니다. 첫 로그인에서 안전한 비밀번호 해시를 등록하며 자체 회원가입은 제공하지 않습니다. [.env.example](.env.example)과 [계정 설정](docs/site-login.md)을 참고하세요. 같은 DB를 사용하는 호스트와 Compose는 같은 파일 저장소를 사용해야 합니다. 호스트 연결은 `127.0.0.1:55432/korcounsel_dev`, Compose 내부 연결은 `postgres:5432`이며 [저장·worker 운영 계약](docs/persistence-and-jobs.md)에 설명합니다.

재판결과 업무키와 출처 독립 canonical 등록 모델은 구현했지만, 전체 corpus의 canonical 연결 확정·신규/변경 수집 자동 운영·쟁점/답변/근거 구조화와 검수/GOLD 생산은 후속입니다. AWS 배포·도메인·운영 예약은 이번 로컬 확장에 포함하지 않았습니다. 전체 실행 순서는 [PLAN.md](PLAN.md), UX 기준은 [DESIGN.md](DESIGN.md)를 따릅니다.

## 폴더 원칙

README는 루트에 하나만 둡니다. 루트 React 프로젝트, backend/의 Python 프로젝트, 루트 compose.yaml, docs/와 .fordeploy/ 경계는 확정했습니다. 내부 모듈명·세분화는 변경 가능한 설계이며 필요한 단계에 추가합니다.

| 위치 | 역할 |
| --- | --- |
| src/ | React 19 + Vite + TypeScript |
| backend/src/klegal_gold/ | FastAPI·CLI·설정·DB, 후속 pipeline |
| backend/tests/ | Python 단위·통합·회귀 테스트와 fixture |
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

브라우저에서 http://127.0.0.1:5173 에 접속해 허용된 계정으로 로그인합니다. Vite가 /api를 로컬 FastAPI로 전달합니다. corrected Parquet 검색을 쓰려면 백엔드 실행 전에 LEGACY_PARQUET_PATH를 절대경로로 지정합니다. 예: LEGACY_PARQUET_PATH=/home/hchjeong/IntelliJProjects/korcounsel/data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet. 관리자의 ‘검색 색인 관리’에서 색인을 구축하면 전체 컬럼 문자열 검색에 PostgreSQL trigram 색인을 사용합니다. 구축 전이나 파일 변경 후에는 Parquet 스캔으로 돌아가므로 검색이 느릴 수 있습니다. [검색 색인·이미지 재취득](docs/search-index-and-image-retry.md)를 참고하세요.

## Parquet 검증 검색

프론트의 판례 검색 화면은 FastAPI의 /api/cases/search를 호출합니다. 현재 endpoint는 LEGACY_PARQUET_PATH에 연결된 완료 검색 색인을 우선 조회하며, 없으면 corrected Parquet snapshot을 pyarrow로 직접 읽습니다. 이 검색은 snapshot 검증을 위한 것이며 결과에는 row_position, original_index, 법원, 사건번호, 선고일, 매칭 컬럼명이 포함됩니다.

```bash
cd backend
LEGACY_PARQUET_PATH=/home/hchjeong/IntelliJProjects/korcounsel/data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet \
  uv run uvicorn klegal_gold.web.app:app --host 127.0.0.1 --port 8000 --reload
```

DuckDB와 Polars는 아직 채택하지 않았습니다. 문자열 검색은 pyarrow 스캔과 PostgreSQL의 재생성 가능한 trigram projection을 사용합니다. 별도 분석 도구 도입은 필요할 때 검토합니다. 운영 배포에서도 Parquet 파일을 배치하고 LEGACY_PARQUET_PATH만 지정하면 같은 UI를 사용할 수 있습니다.

## 이미지 취득 ledger

이미지 참조와 실제 bytes 취득은 PostgreSQL job으로 처리한다. `scripts/stage_image_acquisition_manifest.py`는 기존 8,418개 레거시 glaw URL을 직접 취득 URL로 넣지 않고 원참조·파일명·legacy contId를 보존한다. 현재 portal provider mapping을 재관찰해 취득 URL이 생긴 항목만 `klegal ops submit-image-batch`와 worker가 다운로드한다. 수정된 50개 제한 job은 NAME_ONLY 50건을 저장하고 다운로드 시도 0건으로 통과했다. name-only와 ID 불일치 참조는 별도 상태로 보존한다. 자세한 내용은 [이미지 보존 검토](docs/image-preservation-review.md#영속-ledger와-worker-취득-경로--2026-09-11)를 참고하세요.

## Compose 전체 실행

현재 corpus를 가진 로컬 DB와 제공된 계정을 사용하려면 명시적인 환경파일로 실행합니다. 이 명령은 기존 DB·파일을 초기화하거나 migration을 재실행하지 않습니다.

```bash
WEB_ORIGIN=http://127.0.0.1:8080 \
  docker compose --env-file .fordeploy/aws-backup/.env -f compose.yaml -f compose.dev.yaml up -d --wait api worker web
```

검증된 로컬 앱은 [http://127.0.0.1:8080](http://127.0.0.1:8080)에서 열 수 있습니다. 아래 예제 환경파일은 새 폐기용 개발 환경을 준비할 때 사용하며, 기존 DB의 계정 설정과 섞지 않습니다.

```bash
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml build api web
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml run --rm migrate
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml up -d --wait api worker web
```

http://127.0.0.1:8080 에서 Nginx→FastAPI 연결을 확인합니다. api는 PostgreSQL 준비 후 시작하며 health는 API 생존 여부만 뜻합니다. Compose에서 API를 명시적으로 갱신·재시작하면 web도 재시작해 Nginx가 현재 API 주소를 다시 읽도록 `depends_on.api.restart`를 지정했습니다. PostgreSQL은 기존 named volume을 유지하고, API/worker는 호스트 `./data`를 컨테이너 `/data`에 함께 연결합니다. 같은 DB를 쓰는 호스트 API/CLI도 레포 `data/`를 `DATA_DIR`로 지정해야 합니다. 기존 `korcounsel_case_data` 볼륨은 원본 보존용으로 남겨 두며 삭제하지 않습니다.

```bash
# 실제 worker의 생존 확인
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml exec worker klegal ops worker-health
# 컨테이너 정리, DB·판례 볼륨은 보존
docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml down
```

compose.env.example의 비밀번호는 폐기 가능한 로컬 개발 전용입니다. 운영에 사용하지 않습니다. 현재 포트는 localhost에만 열려 있으며 TLS·운영 secret·백업·자동 재시작과 배포 절차는 Step 11B에서 완성합니다. migration은 Step 2A에서 추가했으며 운영 DB 역할 분리·TLS는 후속입니다.

Compose의 `LOCAL_DATA_DIR`은 기본 `./data`이며 필요한 경우 실제 공통 저장소의 절대 경로로 지정합니다. `LOCAL_UID`/`LOCAL_GID`는 그 폴더 소유자의 `id -u`/`id -g` 값으로 맞춥니다(기본 1000:1000). 컨테이너는 해당 비-root 사용자로 실행하며 기존 파일 소유자를 일괄 변경하지 않습니다. `LEGACY_PARQUET_CONTAINER_PATH`는 컨테이너 내부 경로로 기본 `/data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet`입니다. 호스트용 `LEGACY_PARQUET_PATH`와 구분합니다. 로그인 검증 시 `WEB_ORIGIN`은 실제 접속 주소인 `http://127.0.0.1:8080`에 맞춥니다.

## 설정과 CLI

기본적으로 프로세스 환경변수만 읽습니다. `.env`를 자동 탐색하지 않습니다. 필요하면 절대 경로의 `KLEGAL_ENV_FILE`로 파일을 명시하고, 같은 이름의 프로세스 환경변수가 우선합니다.

```bash
cd backend
uv run klegal version
uv run klegal check-config
DATABASE_URL='postgresql://korcounsel:korcounsel_local_only@127.0.0.1:55432/korcounsel_dev' uv run klegal check-db
```

- LAW_OPEN_API_OC와 LAW_GO_KR_OC는 alias이며 값이 다르면 오류입니다. 실제 값은 출력하지 않습니다.
- 사용자가 제공한 `.fordeploy/aws-backup/.env`는 명시적으로 로컬 검증에 사용할 수 있습니다. 값은 출력하지 않으며 이번 보강 확대에서 변경하지 않았습니다.
- DATA_DIR은 절대 경로입니다. 로컬 기본값은 레포 data/이며 작업 디렉터리 변경에 영향받지 않습니다. 설정을 읽는 것만으로 파일을 생성하지 않습니다.
- DATABASE_URL은 PostgreSQL 연결 문자열입니다. 미설정이면 health는 응답하지만 check-db는 실패합니다.
- LEGACY_PARQUET_PATH는 corrected Parquet 검증 검색에 사용할 절대 경로입니다. 미설정이면 검색 endpoint는 빈 결과와 source=UNCONFIGURED를 반환합니다.
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

최신 Python 검증: Parquet 검색 unit 12건과 DB 검색 integration 1건 통과, ruff·프론트 typecheck/build 통과. 과거 전체 검증 이력: pytest 84건(로컬 PostgreSQL 포함), ruff·mypy 통과. Step 1 당시 UI 검증: desktop/mobile E2E 6건, 타입·lint·빌드·Compose 실행 통과. 기존 합성 fixture 53건 중 optional editorial 3종을 domain 테스트에 연결했습니다. 전체 parser/resolver 검증을 완료했다는 뜻은 아닙니다. 테스트 의존성의 upstream deprecation warning 2건이 관찰됐습니다.

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
