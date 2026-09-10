# KorCounsel Agent Instructions

작업 전 루트 PLAN.md를 읽고 현재 범위·순서·완료 기준을 확인한다. UI 작업 전 DESIGN.md를 읽는다. README.md는 사용자 안내와 운영 진입점, PLAN.md는 실행 계획·상태, DESIGN.md는 UX 기준, 이 문서는 작업 규칙이다.

이 문서는 인접 onju-ai-kr/AGENTS.md의 명시적 작업 범위, domain/adapters 경계, immutable evidence, 검수 이력, 배포·비밀정보 관리 및 검증 원칙을 이 프로젝트에 맞게 이전했다. 참조 저장소의 지침을 현재 저장소의 실행 명령이나 구현 완료 사실로 취급하지 않는다. 사용자의 최신 명시적 결정이 과거 문서의 상충하는 전제보다 우선한다.

## 프로젝트 목적과 작업 범위

- 이 프로젝트는 공개 한국 판례를 추적·재현·검증 가능한 LegalIssueUnit으로 생산하는 소수 사용자용 비공개 업무 앱이다. 법률 주석 편집·출판 SaaS나 포트폴리오 사이트가 아니다.
- pipeline은 공식 API → RAW → NORMALIZED → STRUCTURED → 쟁점/답변/evidence → 검증 → GOLD다.
- 초기에는 LLM API, 모델 학습, GPU, RAG, vector database, Elasticsearch, OCR/vision 해석을 구현하지 않는다. scourt identity/inventory 및 fidelity 확보에 필요한 취득 adapter는 초기 확장 범위이며 HTML/browser 사용을 일괄 금지하지 않는다.
- 한 번에 작은 검증 가능한 단계로 진행하고 관련 테스트·문서를 함께 갱신한다. 이미 사용자에게 허용된 범위에서는 불필요한 단계별 재승인을 요구하지 않는다.
- 새 범위, 외부 운영 변경, 파괴적 조작은 현재 사용자의 지시와 작업 범위를 확인한다. 문서 작성 요청은 AWS 배포·리사이즈·DNS·IAM 변경 권한을 뜻하지 않는다.
- 현황을 실제 증거로 기록한다. 참조 프로젝트의 완료 보고서·배포 이력·테스트 수를 현재 상태로 복사하지 않는다.
- 단순하고 명시적인 코드를 선호한다. 큰 재작성, 범용 workflow engine, 멀티테넌트, 복잡한 권한 체계를 기본으로 도입하지 않는다.
- 프런트·Python core·배포 자료·문서를 이 monorepo에서 관리한다. 별도 저장소나 EC2를 임의로 추가하지 않는다.

## 확정 아키텍처

- 프런트: 루트 src/의 React 19 + Vite + TypeScript. Next.js는 도입하지 않는다. 프런트는 레포 루트, Python 프로젝트는 backend/를 사용한다.
- Python: backend/src/klegal_gold/의 Python 3.12, uv와 pyproject.toml/uv.lock. requires-python은 >=3.12,<3.13이다.
- API: FastAPI. Pydantic request/response schema와 OpenAPI가 프런트/API 계약의 기준이다. 외부 법률 데이터 API 명세와 혼동하지 않는다.
- DB: PostgreSQL. SQLite를 운영 DB 또는 PostgreSQL integration 대체물로 사용하지 않는다.
- 처리: 별도 Python worker. 초기 API 프로세스 1개, 처리 worker 1개로 시작하며 각자의 역할을 구분한다.
- 프런트는 /api를 통해 API에 접근한다. 인증·권한·업무 검증을 React 화면 표시 조건만으로 처리하지 않는다.
- core는 FastAPI, React, ORM, HTTP 응답 형식에 종속시키지 않는다. source client, DB persistence, 파일 저장은 경계 뒤에 둔다.
- frontend API wrapper는 명시적 타입을 사용한다. API 안정화 후 client 생성은 검토할 수 있지만 기본 요구로 확장하지 않는다.
- Python DB driver·접근 도구·migration 도구, Node.js·프런트 패키지 관리자·routing·조회 도구, HTTPS 서버는 구현 시 호환성 확인 후 선택·고정한다. 참조 저장소의 pnpm, SQLAlchemy/Alembic, async driver를 이미 확정된 것으로 취급하지 않는다.
- 참고 가능한 구현 선택은 명확한 이점이 있을 때 사용하고 PLAN.md와 lockfile에 기록한다. 실제 필요 없이 라이브러리를 일괄 설치하지 않는다.

## 저장소 경계

- 루트 src/: React 페이지·컴포넌트·API client·브라우저 상태.
- backend/src/klegal_gold/domain/: 명시적 판례·쟁점·evidence·authority·provenance 모델.
- sources/: CaseSource protocol과 공식 API adapter.
- normalize/, parse/, segment/: 결정론적 규칙과 문장 분리 interface.
- pipeline/: 단계별 유스케이스, 웹/CLI 공용 core.
- web/: FastAPI app·인증·router·HTTP schema.
- jobs/: 작업 등록·claim·상태 전이·worker·종료 준비·재개.
- db/: PostgreSQL 연결·persistence model·repository. migration은 backend/migrations/에 둔다.
- storage/, validate/: artifact 저장과 데이터 검증.
- tests/fixtures/, unit/, integration/, regression/: 테스트 자료와 검증.
- scripts/: 로컬 수집·개발·유지보수 도구.
- .fordeploy/: 배포 스크립트와 설정. 배포 설명은 README.md와 docs/에 둔다.
- .fordeploy/aws-backup/: 로컬 배포 자료 staging 공간. 사용자가 제공한 .env가 있으며 Git에서 제외한다. .gitkeep만 기본 추적한다.
- ops/를 별도 배포 루트로 만들지 않는다. 기존 PLAN의 ops 개념은 .fordeploy로 통합한다.

## 레거시와 외부 자료

- web2df와 df2preproc는 I:\VSCodeBases 아래에서 실제 루트를 확인한 뒤 읽는다. 해당 경로를 앱 런타임 필수값으로 hard-code하지 않는다.
- 레거시 분석과 docs/migration-from-legacy.md 작성 후 구현한다. legacy field 의미, 재사용/수정/폐기 규칙, 경로·pickle·DataFrame 결합·취약 regex·호환성을 기록한다.
- 발견한 버그와 edge case를 회귀 fixture로 만든다. 참조 저장소를 수정하거나 새 프로젝트에서 import하지 않는다.
- 기본 corpus는 scourt 본문과 lawgo 보강을 계승한다. 국가법령정보 공동활용 OPEN API client의 초기 개발과 scourt snapshot/identity/fidelity adapter 검증을 진행한다. 실제 명세·인증·pagination·응답·호출 제한·이용 조건을 공식 문서로 확인한다.
- timeout, 제한된 retry/backoff, API 오류와 부분 수집을 명시적으로 처리한다. API credential을 코드·로그·URL 출력에 노출하지 않는다.
- 공개 자료라는 이유로 재배포 조건을 추정하지 않는다. 출처·수집 정보·사용 범위를 기록한다.

## RAW, hash와 provenance

- 원본 응답 바이트를 변형 없이 보존하고 SHA-256 raw_content_hash를 계산한다. 정규화 후 hash로 원본 hash를 대체하지 않는다.
- source_system, source_document_id, source_url, retrieved_at, raw_content_hash, parser_version, normalizer_version, dataset_version을 유지한다.
- 동일 문서의 같은 내용은 재사용하고 변경된 내용은 별도 원본 버전으로 보존한다. 수집 시도·시각과 문서 내용 버전을 구분한다.
- 기준 원본 텍스트를 재구성하는 디코딩·필드 추출 규칙 및 버전을 보존한다. JSON/XML 바이트 offset과 source text offset을 혼용하지 않는다.
- 변환·필터는 원본을 덮어쓰지 않으며 적용 규칙과 제외 사유를 기록한다. 원문 및 실패 후보를 검증 통과율을 높이기 위해 삭제하지 않는다.
- 원자적 파일 저장과 DB 반영 사이의 실패를 복구할 수 있게 설계한다. 완료 artifact를 가리키기 전 저장 완료와 hash를 확인한다.

## 판례·쟁점·evidence 규칙

- LegalCase와 LegalIssueUnit을 명시적 모델로 정의한다. DataFrame이나 parser의 임시 구조를 도메인 계약으로 사용하지 않는다.
- 법원, 사건번호 및 병합 번호, 선고일, 판결/결정, 사건명, 판시사항·요지·이유, 조문·판례 인용을 보존한다.
- regex 하나로 모든 파싱을 처리하지 않는다. 작은 함수와 input→expected output 테스트로 조합한다.
- 판사 표시·별지·heading·번호·숫자 fragment 정리 시 의미 있는 법률 조항·날짜·금액을 보존한다. 구조 파싱에 필요한 번호를 미리 지우지 않는다.
- SentenceSplitter protocol과 외부 NLP 의존성이 없는 기본 splitter를 유지한다. Kiwi/KSS는 PLAN에 명시한 후속 범위다.
- 항목 수가 같다는 이유만으로 쟁점과 답변을 zip하지 않는다. 명시적 번호·검증된 구조를 사용하고 모호하면 ambiguous/unmatched 및 사유를 남긴다.
- issue_original/answer_original은 원문 발췌를 보존한다. normalized는 결정론적 변환이며 의미를 생성하거나 보충하지 않는다.
- EvidenceSpan은 기준 artifact·필드·text·start/end·유형을 가진다. Python Unicode code point와 [start,end) 계약을 따른다.
- source_text[start:end] == evidence.text를 검증한다. 유일한 정확 일치나 보존된 위치 매핑 없이 offset을 추정하지 않는다.
- 판결요지 발췌와 판결이유 근거, case 범위 authority와 issue 직접 연결 authority를 구분한다.
- alignment_status, 자동 quality_status, 사람의 review_status는 서로 다르다. 자동 통과를 인간 승인·법률 정확성으로 표시하지 않는다.
- gold 포함 정책은 PLAN과 schema를 따른다. 사람이 검토한 자료와 자동 통과 자료, 요지 기반 자료와 이유 근거 자료를 구분해서 내보낸다.

## PostgreSQL과 작업 실행

- 사용자·권한·세션, 작업·실행 이력, 향후 검토 결정은 PostgreSQL의 운영 데이터다. 조회용 판례·쟁점 정보는 버전 있는 artifact에 연결한다.
- 조회 projection은 재구성할 수 있어야 하지만 사용자·검토·작업 기록은 재수집이나 seed로 덮어쓰지 않는다.
- 원본 JSON/XML/HTML 및 관찰된 source artifact, inventory·asset manifest, 중간 artifact, JSONL·Parquet export는 파일로 보존한다. DB 도입으로 immutable 파일 정책을 없애지 않는다.
- 긴 작업을 API 요청이나 FastAPI BackgroundTasks로 실행하지 않는다. job을 영속 등록하고 단일 worker가 claim한다.
- 중복 제출 방지, 트랜잭션 상태 전이, worker 생존 확인·lease 또는 동등한 복구 규칙을 구현한다. 실제 실행이 중복될 수 있는 실패 상황도 idempotency로 처리한다.
- 브라우저 응답 유실을 작업 실패로 단정하지 않는다. request identity를 유지하고 상태를 조회한 후 동일 요청 재시도 여부를 판단한다.
- CLI도 작업 상태와 종료 준비 정책을 공유한다. 웹을 우회해 중복 실행하거나 종료 준비 중 새 작업을 시작하지 않는다.
- migration은 버전 관리하고 실제 PostgreSQL에서 제약·동시성·복구를 테스트한다. 운영 DB를 개발 테스트·reset 대상으로 사용하지 않는다.
- run_id와 dataset_version을 분리하고 입력 snapshot, 코드·규칙·설정 버전, 건수, checksum을 남긴다.
- 작은 connection pool, batch 처리와 낮은 동시성으로 시작한다. DB 전용 서버의 메모리 설정을 공유 bastion에 그대로 적용하지 않는다.

## 검토 이력과 Phase 1.5

- Phase 1은 조회 중심 검수와 표본 품질 평가다. 검토 작업을 실제로 구현하지 않은 상태에서 승인된 것처럼 표시하지 않는다.
- Phase 1.5 수정·승인·반려·보류는 정확한 record revision과 원본 hash에 연결한다. 검토자·시각·사유를 서버에서 기록한다.
- 자동 결과와 사람의 수정을 별도 저장하며 이전 evidence·검토 이력을 보존한다. 원본·규칙 변경 후 과거 승인을 자동 승계하지 않는다.
- 검토 요청, 검토 결정, dataset export는 별개다. 조회·댓글·파일 다운로드를 승인으로 취급하지 않는다.
- onju의 AI draft, commentary publication, editor roster, 채팅·SES·원고 업로드 기능은 현재 범위에 포함되지 않는다.

## 인증과 UI 작업

- DESIGN.md의 문서 중심·차분한 3단 검수 화면을 따른다. 마케팅 hero나 과도한 장식·nested cards를 만들지 않는다.
- 최초 접속은 인증 진입점이며 로그인 후 실제 대시보드로 이동한다. 공개 guest 데이터 preview나 자체 회원가입을 만들지 않는다.
- 소수의 허용된 계정을 운영하고 모든 비공개 조회·다운로드·변경을 FastAPI에서 인증·권한 확인한다.
- 비밀번호는 안전한 password hash로만 저장한다. cookie 세션을 사용하면 HttpOnly/Secure와 적절한 SameSite·상태 변경 보호를 적용한다. 세부 방식은 구현 시 문서화한다.
- secret과 인증 token을 frontend build 변수·browser 영속 저장소·로그에 넣지 않는다. 로그아웃/계정 변경 시 private client state를 비운다.
- API의 느린 이전 응답이 새 선택을 덮어쓰지 않게 한다. 진행 중 변경·불확실한 저장은 동일 요청 식별자를 보존하고 사용자에게 확인 경로를 제공한다.
- 원문은 안전하게 렌더링한다. HTML을 신뢰하지 않으며 evidence offset의 Python/JavaScript 인덱스 차이를 테스트한다.
- UI의 로딩·빈 목록·오류·권한 없음·운영 종료 준비를 구분한다. 중요한 상태는 색만으로 표현하지 않는다.

## 로컬 실행과 검증

- 초기 scaffold와 함께 개발·테스트 DB 준비, 환경 설정, migration, frontend/backend/worker 실행 순서를 문서화한다.
- Docker Compose로 로컬 DB·전체 환경을 구성한다. API·worker·DB 역할과 영속 위치를 분리하고 로컬 검증을 AWS 운영 완료로 취급하지 않는다.
- 개발 fixture와 계정을 운영 seed로 자동 주입하지 않는다. source 및 synthetic fixture를 구분하고 사용자·비밀번호를 소스에 넣지 않는다.
- Python 변경은 ruff check/format, mypy, pytest와 해당 단계 전체 회귀 검증을 수행한다.
- frontend 변경은 타입·lint·build 및 영향받는 브라우저 흐름을 검증한다. UI만 바꾼 경우에도 직접 URL·로그인 만료·빈 상태를 필요한 범위에서 확인한다.
- DB 변경은 실제 테스트 PostgreSQL의 migration·제약·job claim·재시작 복구를 확인한다.
- data 변경은 provenance, duplicate, encoding, evidence 범위와 텍스트 일치, JSONL/Parquet round-trip을 검증한다.
- 배포 스크립트는 shell syntax, dry-run 가능한 준비 단계, 경로·secret 출력·데이터 보존·실패 종료를 확인한다. Compose를 채택하면 config 및 startup/health도 검증한다.
- live API 호출·AWS 운영 검증과 로컬 테스트를 구분해 보고한다. 미실행을 통과로 기록하지 않는다.

## AWS 운영 및 배포

- 운영 대상은 기존 aws-bastion, 도메인은 korcounsel.com이다. 실제 인스턴스 ID·리전·계열·OS·포트·서비스·SSH/NAT 역할·DNS를 먼저 확인한다.
- micro→호환 small로 시작하고 부하 측정 후 medium을 검토한다. 현재 타입이나 변경 완료를 확인 없이 단정하지 않는다.
- 프런트 정적 파일, FastAPI, PostgreSQL, worker를 같은 EC2에서 운영한다. 별도 Node.js frontend runtime, RDS, ALB, NAT Gateway, Redis를 기본 요구로 추가하지 않는다.
- 빌드·검증은 로컬 또는 선택된 CI에서 수행하고 배포 결과를 대상에 옮긴다. CI 가능성을 자동 배포 파이프라인 설치 요구로 해석하지 않는다.
- 배포 준비와 실제 운영 변경을 분리한다. 실행 권한이 있는 범위에서 진행하고 구체적 대상·변경·migration·복구 절차를 제시한다. onju 사용자에게만 적용된 수동 실행 제한을 현재 사용자의 추가 제한으로 복사하지 않는다.
- shell 스크립트는 읽기 쉽고 보수적이며 가능한 범위에서 idempotent하게 작성한다. Bash에는 set -euo pipefail을 사용한다.
- 이미지/빌드 식별자, 포트, remote/runtime 경로와 health 경로를 명시적으로 설정한다. 임의의 /home/ubuntu 경로를 확인 없이 적용하지 않는다.
- release/현재 코드와 DB·원본·artifact·환경파일 저장 위치를 분리한다. 재배포·cleanup에서 DB 볼륨이나 영속 데이터를 삭제하지 않는다.
- 실제 환경파일 transfer/overwrite는 명시적 작업 범위와 대상 확인 후 수행한다. 재배포마다 자동 복사하지 않으며 파일 내용은 출력하지 않는다.
- Docker 구성에서는 app build context에서 .fordeploy와 secret·dump·artifact를 제외한다. image archive는 transfer 자료이며 Git에 넣지 않는다. 배포 방식은 구현 시 고정한다.
- /api/health, frontend HTTP, DB 및 worker 상태를 개별 검증한다. 실패 시 원인과 복구 경로를 남기고 부분 성공을 전체 배포 성공으로 표시하지 않는다.
- DB와 artifact의 일관된 백업·복원을 검증한다. 폴더나 script 존재만으로 백업 완료라고 보고하지 않는다.

## 평일 가동과 종료 보호

- Asia/Seoul 월~금 10:00 시작, 17:00 종료 준비. 토·일 자동 시작 없음, 평일 공휴일은 운영한다.
- 기동/종료 제어는 EC2 외부의 AWS 예약 기능을 이용한다. 이 계획만으로 실제 Scheduler를 생성하지 않는다.
- 17:00부터 새 작업 등록 및 대기 작업 claim을 막고 진행 작업 완료 또는 checkpoint 저장 후 중지한다. 최대 유예·고장난 worker 처리 기준을 구현 시 정한다.
- 중지 중 해당 웹과 bastion 경유 SSH가 끊긴다는 점을 운영 문서에 명시한다. 다른 서버의 시간 외 관리 필요와 대체·수동 시작 경로를 확인한다.
- 단순 예약 StopInstances로 진행 작업을 끊지 않는다. 종료 준비와 job claim의 경쟁 및 재시작 복구를 검증한다.

## Secret 및 배포 staging

- .fordeploy/aws-backup/은 .gitkeep만 기본 추적한다. 실제 env, private key, DB dump, image archive, 배포 backup은 Git에서 제외한다.
- 사용자가 제공한 .fordeploy/aws-backup/.env를 명시적 로컬 설정 경로로 사용할 수 있다. 값을 출력하거나 임의로 변경하지 않는다. LAW_OPEN_API_OC와 LAW_GO_KR_OC alias 계약은 docs/law-open-api-contract.md를 따른다. 운영자가 선택한 명시적 환경파일 경로를 사용하고 참조 저장소의 ONJU_* 값·계정·환경파일을 읽거나 가져오지 않는다.
- .env.example에는 비밀값 없는 설명·예시만 둔다. runtime secret을 정적 번들·이미지·빌드 로그·manifest에 포함하지 않는다.
- Docker 구성에서 .dockerignore를 유지하고 context가 달라지면 해당 경계에도 동등한 제외 규칙을 적용한다.
- 실제 dump나 local DB를 AWS로 자동 이전하지 않는다. migration·seed·운영 import는 각각 별도 작업으로 구분한다.

## 참조 문서에서 변경한 사항

- docs/PLAN.md → 루트 PLAN.md, Next.js 루트 앱/backend/ → 루트 React src/와 backend/src/klegal_gold/.
- 주석 생성·출판 및 guest reader → 판례 데이터 생산·인증 검수 앱.
- AI 실행·주석 편집·SES·editor roster → 현재 제외 또는 별도 미래 범위.
- 원문 정규화 후 checksum → 원본 바이트 hash와 별도 변환 기록.
- 날짜별 강제 중복 archive → 문서 ID+내용 hash 기반 원본 재사용 및 수집 이력.
- ALB·별도 target host → 기존 bastion 한 대의 직접 HTTPS 서비스.
- 참조 프로젝트 전용 단계 승인·수동 배포·backup 비활성 기본값·Compose 고정 버전·secret 경로는 그대로 이식하지 않는다. 현재 PLAN과 실제 사용자 지시를 따른다.

## 추가 identity·incremental·fidelity 지침

- 구현 전 docs/legacy-case-identity-and-assets.md와 architecture.md, case-identity.md, incremental-ingestion.md, source-fidelity.md, dataset-schema.md, provenance.md를 읽는다. 추가 지시가 기존 단일-source/text 전제보다 우선한다.
- contId와 serialno는 별도 namespace의 source IDs다. canonical ID와 source version·issue revision을 분리한다. canonical_id를 UUID로 강제하지 않는다. 기존 약 9만 건의 실제 대표/정부 ID를 조사해 우선 계승하고, 발급 정책은 조사 후 결정한다.
- identity/는 후보·전체 번호·법원/지원·날짜·disposition·점수/사유를 다룬다. 첫 후보·substring·fuzzy 점수만으로 확정하지 않는다. EXACT/HIGH_CONFIDENCE/AMBIGUOUS/UNMATCHED/CONFLICT와 연결 revision을 보존한다.
- ingestion/는 inventory·delta·fetch ledger·refresh, documents/는 artifact/blocks, assets/는 탐지·참조/후속 취득, enrichment/는 초기 확장 Step 5B의 조문 보강을 담당한다. shared metadata normalization을 중복 작성하지 않는다.
- snapshot은 범위·완전성·per-ID metadata hash를 보존한다. 선고일만으로 신규를 판단하거나 부분 목록에서 삭제를 추정하지 않는다. UNCHANGED metadata는 unchanged body 보장이 아니다. 상세 실패 ID도 재시도한다.
- issues/summaries 빈 배열·reasoning/full_text null은 정상 LegalCase에서 허용한다. field 부재와 취득/parse 실패를 구분하고 없는 editorial 내용을 생성하지 않는다.
- fidelity tier는 처리 분류다. has_visual_assets/count/requires_ocr의 UNKNOWN을 false/0으로 덮지 않는다. img 부재·PDF URL만으로 원문 완전성이나 scan 여부를 단정하지 않는다.
- Detect→Preserve Reference→Acquire→Reconstruct→Interpret를 분리한다. original src·부모 artifact·위치/order·alt·전후 문맥을 보존하며 첫 단계에 OCR를 추가하지 않는다.
- case 성공, asset 부분 실패, OCR 미처리와 gold 적합성을 구분한다. 시각 evidence를 text offset으로 위조하거나 source 간 내용/이미지를 출처 없이 합치지 않는다.
- Selenium에는 DOM·세션·popup·iframe 책임이 있었다. 실제 source 검증 후 API/HTTP/세션/browser 전략을 선택하고 필요한 경우 Selenium/Playwright를 명시 기준으로 비교한다. 자동 패키지 교체·다중 browser 기본 실행을 피한다.
- merge/split/relink는 이력을 남기고 기존 release·검토를 덮어쓰지 않는다. registry/link snapshot과 asset manifest도 재현·백업 대상이다.
- 문서의 실제 레거시 관찰과 합성 fixture, offline 테스트와 live 검증을 구분한다. 추가 최소 15종을 포함한 fixture를 해당 구현 단계의 테스트에 연결한다.


## 폴더 체계와 README — 2026-09-10

- README.md는 레포 루트에 하나만 관리한다. backend/docs 등 하위 README를 추가하지 않는다. 의존성 설치물이 포함하는 README는 관리 대상 소스에 해당하지 않는다.
- 확정 경계: 루트 React 프로젝트, backend/의 독립 uv Python 프로젝트, 루트 compose.yaml, 공통 docs/와 .fordeploy/.
- 내부 파일명·폴더 세분화는 변경 가능한 설계다. 구현 필요에 따라 조정하고 PLAN/architecture/README와 연결 경로를 함께 갱신한다. 미래 모듈을 빈 파일로 생성하지 않는다.
- Python 품질 명령은 backend/에서 uv로 실행하고 프런트 명령은 루트에서 pnpm으로 실행한다. Python fixture는 backend/tests/fixtures, 브라우저 테스트는 tests/e2e에 둔다.
- Compose와 Nginx를 채택했다. 현재 Compose는 로컬 HTTP 검증용이며 외부 포트를 loopback에만 바인딩한다. TLS·운영 secret·배포 자동화는 Step 11B다.
- Step 1 당시 worker는 일회성 DB 연결 점검이었다. Step 2A부터 기본 worker 서비스는 영속 queue의 artifact 검증·projection 재생성을 실행한다. migration은 tools profile의 명시적 일회성 서비스다. 실행·복구 계약은 docs/persistence-and-jobs.md를 따른다.


## 기존 corpus 우선 계승 — 2026-09-10 사용자 결정

- 기존 약 9만 건을 bootstrap corpus로 활용하고 이후 신규·변경분을 확장한다. ID 정책보다 실제 저장본의 전수 프로파일·층화 표본 분석을 먼저 수행한다. 전체 재수집·일괄 재번호를 기본안으로 삼지 않는다.
- **법원명 + 사건번호는 고유 업무 식별키**이며 canonical ID 및 출처 ID와 함께 유지한다. 정부 ID 없는 LawnB 보유 판례 등록에도 사용한다. 지원·지부와 모든 병합 사건번호를 보존한다.
- 극히 드문 과거 수작업 오류는 충돌/예외 이력으로 관리한다. 여러 source representation을 고유성 예외로 오인하거나, 조합의 고유성을 포기하거나, 임의 삭제·병합하지 않는다.
- 기존 공식 ID가 대표 ID 역할을 했다면 그대로 활용할 수 있다. canonical과 source의 논리적 역할 분리가 반드시 새로운 UUID를 요구하지 않는다.
- legacy row locator(snapshot hash + 원래 index/position), 기존 필드·sentinel·추출 원문을 보존한다. 저장 문자열을 과거 HTTP 응답 원본 바이트라고 부르거나 과거 수집 시각·hash를 만들어 채우지 않는다.
- LawnB의 기존 자료 식별/등록 계약과 새로운 LawnB 수집은 별개다. 분석용 pandas/NumPy는 별도 일회성 런타임으로 사용하며 앱 domain/runtime 의존성으로 추가하지 않는다.

- 실제 보존 공식 metadata에 한 법원명+사건번호 아래 판결·결정/중간판결의 여러 문서가 존재한다. 사건 업무키와 개별 결정 문서·source representation을 구분한다. 업무키 고유성을 없애거나 문서들을 강제 병합하지 않으며, 정상 다문서 관계를 수작업 오류 예외로 세지 않는다.

## 본문 보강·증분 전략 계승 — 2026-09-10

- 기존 scourt 기본 본문 + scourt 이미지 참조 주소 보완 + lawgo 조문 내용 보강을 계승한다. 기존 89,130행과 확보한 보강 HTML·두 공식 ID를 초기 자산으로 가져온다. 상세 계약은 docs/legacy-enrichment-and-incremental.md를 따른다.
- 이미지 URL 해석과 binary 취득은 별개다. 원래 src와 base·resolved URL을 보존한다. 조문 링크가 있다는 사실과 조문 상세 내용이 보존됐다는 사실도 구분한다.
- 신규 scourt contId 차집합, 기존 lawgo 연결, 미완료 보강만 처리하는 전략을 계승하되 항목별 ledger·hash/규칙 version·재시도를 구현한다. HTML success 표시는 전체 보강 성공 근거로 쓰지 않는다.
- 보강 HTML을 raw로 덮어쓰지 않고 부모 원문과 조문 artifact·출처·버전·위치에 연결한다. 과거 법령 버전 미확인을 최신 법령으로 조용히 대체하지 않는다.


## 보강 범위 제한과 현행 호환성 — 2026-09-10 사용자 확정

- 확실한 인용도 앱이 독자 해석하여 법령 API로 직접 보강하지 않는다. 법원·법제처가 해당 판례에 제공한 정보·연결의 합을 보존하는 범위를 지켜 기존/신규 자료의 일관성을 유지한다.
- scourt 본문 확보·기본 검증 후 먼저 등록하고 lawgo 보강은 별도 대기/부분 완료/실패 상태로 처리한다. 미보강 자체를 판례 실패로 만들지 않는다.
- 수년 전 HTML/내부 endpoint/세션/popup/iframe/이미지 경로가 현재도 같다고 가정하지 않는다. scourt와 lawgo 양쪽 취득·보강 경로의 현행 표본 검증을 대량 작업의 선행 조건으로 둔다.
- API HTTP 200만으로 browser/HTML 보강 성공을 주장하지 않는다. selector 부재·빈 추출·오류 페이지를 source 필드 부재로 덮지 않고 구조 변경 의심/실패로 기록한다. 상세 기준은 docs/legacy-enrichment-and-incremental.md를 따른다.
