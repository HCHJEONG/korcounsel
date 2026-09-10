# Korean Legal Golden Dataset Factory — 구현 계획

## 재판결과 식별 규칙 반영 — 2026-09-10

- [x] 사용자 도메인 규칙인 **법원 명칭 + 사건번호 + 재판 종류 = 특정 재판결과의 업무 식별키**를 작업 규칙과 identity·schema·import 계약에 기록했다.
- [ ] 사건 CourtCaseKey와 별도로 재판결과 세 요소 키를 모델링하고, 재판 종류의 원표기·정규화·결측·충돌 처리 및 독립 canonical 연결을 구현한다.
- [ ] 실제 PostgreSQL 제약과 같은 사건의 판결/결정·중간판결 구별, 동일 재판결과의 복수 출처, 잘못된 metadata 충돌을 검증한다.

상세 정책은 [identity](docs/case-identity.md)를 따른다. 선고일은 대조 정보이며 필수 키 구성요소가 아니다. 이번 기록은 코드·DB 반영 완료를 뜻하지 않는다.

## 우선 반영할 설계 결정 — 출처 ID 안정성

**2026-09-10 사용자 결정:** contId/serialno를 신규 canonical ID로 사용하지 않는다. 출처별 관찰·재조회 키와 내부 개별 결정 문서 ID를 분리한다. [정책](docs/case-identity.md), [실측 근거](docs/source-path-validation.md).

- [x] 작업 규칙·identity·legacy import 계약에 기존 공식 ID 우선 정책의 대체 및 실측 한계를 기록한다.
- [ ] 전체 corpus 등록 전에 독립 canonical ID 발급과 동일 import 재실행 시 ID 재사용을 구현한다.
- [ ] legacy mapper의 source 기반 document_id_proposal을 새 정책에 맞추고 fixture·registry 호환성을 검증한다.
- [ ] 옛/새 출처 번호 후보의 문서 동일성 및 연결 revision을 검토한다. 기존 source ID·원본·release·검토 기록은 덮어쓰지 않는다.

이번 변경은 문서 정책이며 ID 발급 코드·DB migration·registry 변경 완료를 뜻하지 않는다.


> 상태: Step 1 완료 / Step 2 데이터·legacy 보존 계약 및 표본 검증 완료 / Step 2A 로컬 persistence·worker 구현 및 검증 / Step 3 client·양 출처 상세 구현 / Step 3A 확대 검증·목록 보존 후속
> 기준: 사용자 제공 작업지시서, 레거시 경로 및 2026-09-09 웹 앱·AWS 운영·기술 스택 결정
> 최신 작업: 2026-09-10 OC 차단 제거·목록 재검증, scourt bounded inventory/worker, 12개 기존 ID 확대 조사 및 34개 이미지 참조 매핑 검증. 새 ID 후보는 검토 대상으로 보존하며 registry를 변경하지 않았다. docs/source-path-validation.md 참조. 이전 기록: 2026-09-10 사용자 결정 기록: LAW_GO_KR_OC/LAW_OPEN_API_OC는 비밀값이 아니며 응답 내 OC 포함으로 저장을 차단하지 않는다. 기존 차단 제거·목록 재검증은 후속 구현이다. 이전 기록: 2026-09-10 Step 3 JSON/XML client·현재 scourt 상세 adapter·worker 연결과 대표 2건 live 검증. 목록 credential 반사로 저장 차단; Step 3A 전체 inventory/fidelity 미완료. docs/source-adapters.md 참조. 이전 기록: 2026-09-10 Step 2A PostgreSQL SQL migration·불변 파일/DB 연결·registry/ledger·단일 worker·CLI·중단 복구 구현. 로컬 테스트·Compose 검증, 전체 corpus import·AWS 변경 없음. 이전 기록: 2026-09-10 개별 결정 문서 canonical 정책, legacy staging/provenance 및 실제 metadata 15행·저장 HTML 4개 보존 검증 완료. 전체 corpus import·DB registry·현행 사이트 검증은 미실행. 이전 기록: scourt 기본 본문·lawgo 조문 보강·증분 축적 계승 및 Step 5B 기록. 이전 작업: 2026-09-10 Step 2 모델 초안 구현 중, 기존 약 9만 건 우선 계승·법원명+사건번호 업무키 결정에 따라 ID 확정 전 전수/표본 분석을 추가했다. AWS·source 재수집은 하지 않았다.

## 1. 목적과 성공 기준

공개 한국 법률 데이터를 원출처까지 추적 가능한 `LegalIssueUnit`으로 변환하는 결정론적 Python 파이프라인을 구축한다. 데이터 품질, provenance, 재현성, 구조화, 테스트 가능성을 우선한다.

```text
공식 공개 법률 데이터
  → SOURCE INVENTORIES / 증분 취득 / refresh
  → RAW 원본 보존
  → NORMALIZED 식별자·텍스트 정규화
  → CANONICAL IDENTITY / source별 버전·연결 결정
  → STRUCTURED / FULL TEXT / SCAN·ASSET 분기
  → 판례 구조·인용 및 이미지 참조 보존
  → 쟁점 / 답변 / 근거 연결
  → 검증
  → GOLD 데이터셋 및 manifest
```

Phase 1은 공식 API에서 공개 판례 100건 이상을 실제 수집하고, CLI로 전 단계를 실행하여 검증된 쟁점 단위를 JSONL과 Parquet으로 생성하는 것을 목표로 한다. 수집 판례 수와 gold 쟁점 수는 구분한다. 작업지시서의 예시 출력 숫자는 성능 목표로 사용하지 않는다.

## 2. 현재 상태와 작업 범위

- 현재 프로젝트는 Step 1 scaffold를 구현했다. 도메인 모델과 legacy staging 계약은 Step 2 범위에서 검증했으며 인증·수집은 아직 없으며 Step 2A의 영속 worker는 artifact 검증·조회 projection 재생성을 실행한다.
- 배포 이름은 `korean-legal-gold`, Python 패키지는 `klegal_gold`, CLI는 `klegal`을 잠정 사용한다. 현재 폴더나 Git 저장소 이름은 자동 변경하지 않는다.
- 사용자가 안내한 레거시 저장소 탐색 기준 경로는 **`I:\VSCodeBases`**다.
- 이 경로 아래에서 `web2df`, `df2preproc`의 실제 저장소 루트를 확인한 뒤 읽는다. 실제 두 레포의 경로와 관련 코드를 확인했으며 docs의 두 레거시 조사 문서에 근거를 기록했다.
- 레거시는 reference implementation으로만 활용한다. 새 프로젝트에서 import하거나 런타임 의존성으로 연결하지 않으며, 분석 대상 저장소는 수정하지 않는다.
- `I:\VSCodeBases`는 개발 시 참고 경로다. 애플리케이션 코드나 실행 설정에 필수 절대경로로 넣지 않는다.
- 공식 API 명세, 인증·호출 제한·이용 조건 및 실제 응답은 구현 전 공식 자료로 확인한다. Step 0의 확인 결과와 미확인 범위는 docs/law-open-api-contract.md에 기록했다.

### Phase 1에 포함

공식 판례 API adapter, 원본 저장, domain model, metadata 및 법률 텍스트 정규화, 구조 파싱, 판시사항·요지 alignment, evidence/provenance, 검증 보고서, 버전·manifest, JSONL·Parquet, 단계별 CLI, 테스트와 재현 문서를 구현한다. 처음부터 korcounsel.com에서 일반 브라우저로 접속하는 소수 사용자용 인증 웹 앱을 제공하고, 운영 환경의 수집·가공·검증·export 로직은 기존 aws-bastion EC2에서 실행한다. 실행 요약 대시보드, 원문·쟁점 검수 화면, 작업 등록·진행 조회 및 평일 가동 자동화를 포함한다. 프런트는 React 19 + Vite + TypeScript, 백엔드는 FastAPI, 운영 DB는 같은 EC2의 PostgreSQL로 확정한다.

추가 초기 범위: 독립 canonical identity와 source별 ID, scourt/law_go_kr inventory·증분/refresh, optional editorial fields, source artifact 분류 및 Stage A/B 탐지·참조 보존. 기존 100건 API 데모와 아래 identity/incremental·fidelity 완료 기준을 각각 검증한다.

### Phase 1에서 제외

LLM API와 annotation 구현, fine-tuning, BERT/KoELECTRA 및 embedding 학습, GPU 의존성, vector database, RAG, LangChain, LlamaIndex, agent framework, Elasticsearch, 마이크로서비스 분리는 제외한다. PostgreSQL은 사용자 후속 결정에 따라 Phase 1에 포함하며 초기 운영 DB로 사용한다. 사용자 후속 결정에 따라 웹 UI와 이를 제공하는 웹 서버 및 필요한 내부 HTTP endpoint는 포함한다. 범용 공개 API 서비스와 독립적인 다중 서버 구성은 초기 범위에서 제외한다. scourt identity/inventory 및 fidelity 확보에 필요한 source adapter는 초기 확장 milestone에 포함한다. 공식 API→direct HTTP→세션 보조 HTTP→browser 순으로 검증하고 필요한 browser automation을 일괄 배제하지 않는다. LawnB·기타 source 수집, OCR·vision·LLM 해석과 완전한 layout engine은 후속 범위다.

## 3. 기술 및 데이터 원칙

### 환경과 의존성

- Python `>=3.12,<3.13`, `.python-version`은 `3.12`로 고정한다. 이후 minor 버전 확대는 호환성 검증 후 진행한다.
- `uv`를 사용하고 `pyproject.toml`, `uv.lock`, `.python-version`을 버전 관리한다. requirements.txt를 주 의존성 명세로 사용하지 않는다.
- Python core는 표준 라이브러리를 우선한다. 기본 후보는 `httpx`, `pydantic`, `pydantic-settings`, `typer`, `rich`, Parquet 지원용 `pyarrow`다. 웹 API에는 `fastapi`와 ASGI 실행 서버를 추가하고 PostgreSQL driver, DB 접근 및 migration 도구는 호환성 확인 후 선택·고정한다.
- `pandas`, `beautifulsoup4`, `lxml`은 필요가 확인된 기능에만 추가한다. API 응답 내부 markup 처리와 웹페이지 scraping을 구분한다.
- Python 개발 도구는 `pytest`, `pytest-cov`, `ruff`, `mypy`다. 모든 public 함수와 메서드에 타입 힌트를 작성한다. 프런트는 React 19 + Vite + TypeScript를 사용하고 타입 검사·lint·핵심 UI 테스트·production build 검증을 별도로 구성한다. Node.js와 프런트 패키지 관리자는 구현 시 호환 버전을 고정하고 lockfile을 버전 관리한다. uv는 Python 의존성을 관리한다.
- 기본 문장 분리는 외부 NLP 라이브러리 없이 동작한다. Kiwi는 후속 optional adapter, KSS는 호환성 확인 후 실험 대상으로 둔다.
- 환경설정은 `LAW_OPEN_API_OC`(호환 alias `LAW_GO_KR_OC`; 둘이 다르면 오류), `DATA_DIR`, `LOG_LEVEL`, `DATABASE_URL`, 인증·세션 설정 등으로 관리한다. DB 비밀번호와 API credential을 프런트 환경변수나 정적 번들에 넣지 않는다. 애플리케이션 로그는 `logging`, CLI 출력은 필요시 `rich`를 사용한다.

### 원본과 provenance

- RAW에는 API 목록·본문 응답 원본 바이트와 수집 metadata를 보존한다. 원본 JSON/XML을 JSONL 변환 결과로 대체하지 않는다.
- 원본 바이트 SHA-256을 `raw_content_hash`로 사용하며 수집 시각은 시간대가 있는 UTC로 기록한다.
- RAW → NORMALIZED → STRUCTURED → GOLD를 별도 artifact로 유지하고 각 결과에서 상위 artifact를 추적할 수 있게 한다.
- 최소 provenance는 `source_system`, `source_document_id`, `source_url`, `retrieved_at`, `raw_content_hash`, `parser_version`, `normalizer_version`, `dataset_version`이다.
- source URL 부재 시 원본 문서 ID와 저장 artifact를 통한 추적 방법 및 결측 사유를 정의한다.
- 판사 표시, 별지, heading, numbering, 짧은 문장, 숫자 fragment 정리로 원문을 덮어쓰지 않는다. 적용 규칙·변환 결과·제외 사유를 보존한다.
- 금액, 날짜, 사건번호, 조문 번호처럼 의미 있는 정보를 formatting noise로 삭제하지 않도록 회귀 테스트한다.

### Evidence 위치 계약

- offset 기준은 정규화 전 보존한 source text의 Python Unicode code point 인덱스이며 구간은 `[start, end)`다.
- EvidenceSpan에는 기준 원본 artifact, 텍스트/필드 식별자, 발췌문, start/end, 근거 유형을 둔다.
- API 원본 바이트와 디코딩·필드 추출 후 텍스트의 offset은 구분한다. 원본에서 기준 텍스트를 재구성하는 추출 규칙과 버전을 기록한다.
- offset이 있으면 `source_text[start:end] == evidence.text`를 반드시 검증한다.
- 변환 중 위치 매핑을 보존하거나 원문에서 유일한 정확 일치를 확인한 경우에만 offset을 부여한다. 중복 일치나 연결 불가 시 임의 위치를 만들지 않는다.
- 판결요지 근거와 판결이유 근거를 구분한다. 요지를 판결이유에서 찾은 근거로 표시하지 않는다. 요지 기반 데이터와 이유까지 연결된 데이터의 범위를 manifest와 UI에 표시한다. offset 일치는 인용 위치의 정확성을 검증하며, 해당 구절이 답변을 뒷받침하는지에 대한 의미 검증을 대신하지 않는다.

### Alignment 및 gold 포함 정책

- `alignment_status`는 `aligned`, `ambiguous`, `unmatched`로 두고 `quality_status`와 분리한다.
- 명시적 번호가 유일하게 대응하면 우선 연결한다. 번호 없는 단일 쟁점·단일 요지는 구조를 확인한 뒤 연결한다.
- 다중 항목의 개수가 같다는 이유만으로 순서대로 zip하지 않는다. 순서 규칙은 검증된 일대일 대응 조건이 있을 때만 적용한다.
- 반복·누락 번호, 개수 불일치, 병합 쟁점, 일대다 대응은 추측하지 않고 판단 사유를 기록한다.
- 쟁점·답변의 original은 원문 발췌를 유지하고 normalized에는 결정론적 변환만 적용한다.
- 판례 전체 참조조문·참조판례와 쟁점에 직접 연결된 authority의 범위를 구분한다.
- 잠정 quality 상태는 `passed`, `needs_review`, `failed`다. 이는 자동 검증 결과이며 사람의 검수 결과인 `review_status`와 분리한다. 자동 통과를 법률적 의미의 정확성이나 사람의 승인으로 간주하지 않는다. 구체적 오류 코드와 포함 계약은 domain model 단계에서 고정한다.
- LegalCase 저장 유효성과 gold LegalIssueUnit 자격은 분리한다. issues/summaries가 비거나 reasoning/full_text가 없어도 관찰한 artifact와 유효한 식별/provenance가 있으면 정상 판례다. 없는 editorial 데이터를 생성하지 않는다.
- 기본 gold에는 schema/provenance/중복/encoding, 확실한 issue-answer alignment, 유효 evidence 및 필요한 source fidelity를 통과한 record만 포함한다. 불확실한 cross-source 결합이나 필요한 visual evidence 미확보는 후보로 남긴다. source 간 UNMATCHED 자체가 정상 source-local 쟁점의 자동 탈락 사유는 아니다.
- 빈 답변, evidence 미확보, 모호한 alignment는 후보와 검토 보고서에 보존한다. 검증 실패도 원본이나 후보를 삭제하지 않고 오류 보고서에 남긴다.

### 중복, 버전 및 보안

- 원본 버전은 `source_system + source_document_id + raw_content_hash`로 식별한다. 같은 내용은 재사용하고 변경된 내용은 새 버전으로 보존한다.
- 재다운로드 생략과 원문 변경을 확인하기 위한 refresh를 구분한다. 서버에 요청하지 않고 내용 변경 여부를 알 수 있다고 가정하지 않는다.
- 처리 키에는 입력 hash, parser/normalizer/schema 버전과 관련 설정을 포함한다. 규칙이 바뀌면 필요한 단계부터 재처리한다.
- source key, source content version, 독립 canonical ID와 쟁점 revision을 구분한다. 신규 canonical ID는 출처 ID와 독립적으로 발급한다. 현행 조사에서 기존 번호 미조회·다른 번호 후보가 확인되어 공식 ID 대표값 우선 정책을 대체했다. 기존 공식 ID·확정 연결·release는 보존하며 UUID를 강제하지 않는다. 법원명+사건번호는 별도 고유 업무키다. 쟁점 revision은 실제 source version·위치·규칙에 기반한다.
- 실행마다 `run_id`를 부여하고 dataset release의 `dataset_version`과 구분한다. 실행 이력에는 입력 snapshot, 설정, 단계별 상태·건수·오류를 기록한다. manifest에는 dataset/schema/parser/normalizer 버전, 고정된 입력 목록·hash, 코드 버전, 설정, 건수와 출력 checksum을 기록한다.
- 같은 입력 snapshot·코드·설정에서는 record ID·내용·순서가 같아야 한다. 실행 시각 등 run metadata는 재현성 비교에서 분리한다.
- private repository를 전제로 `.env`, 인증정보, 대규모 raw/artifact는 commit하지 않는다. 요청 로그와 manifest에도 credential을 넣지 않는다.
- 코드 라이선스와 공개 데이터의 이용·재배포 조건은 별도 확인한다. proprietary/licensed 데이터는 MVP에 추가하지 않는다.

## 4. 현재 구조와 변경 가능한 확장안

확정 경계는 루트 프런트, backend Python 프로젝트, 루트 Compose, 단일 루트 README다. 내부 폴더·파일 세분화는 구현에 따라 조정한다. 아래는 현재 생성한 주요 파일이며 미래 업무 모듈·migration·worker 코드는 해당 단계에 추가한다.

```text
README.md / AGENTS.md / DESIGN.md / PLAN.md
package.json / pnpm-lock.yaml / pnpm-workspace.yaml / .node-version
index.html / vite.config.ts / tsconfig.json / eslint.config.js
src/                  # React App, main, styles
backend/
  pyproject.toml / uv.lock / .python-version / .env.example
  Dockerfile / .dockerignore
  src/klegal_gold/     # config, cli, web/app, db/connection
  tests/              # unit, integration, fixtures/legacy
compose.yaml / compose.dev.yaml
.fordeploy/frontend/Dockerfile
.fordeploy/nginx/default.conf
.fordeploy/compose.env.example
.fordeploy/aws-backup/.env   # 사용자 제공, Git 제외
playwright.config.ts / tests/e2e/
docs/                 # 설계·조사·개발 문서, README 없음
data/                 # runtime 데이터, Git 제외
```

후속 Python 업무 모듈과 backend/migrations/는 필요 시 생성한다. data/는 개발 기본 경로이며 운영 DATA_DIR은 배포 코드 외부의 영속 경로로 지정한다. public/에는 private 판례·이미지를 넣지 않는다.

## 5. 구현 순서와 단계별 완료 기준

작은 commit 가능한 단위로 구현하되 실제 commit 여부는 별도 작업 지시에 따른다. 기능별 테스트를 각 단계에서 추가하고 단계 완료 시 기존 전체 테스트와 적용 가능한 품질 검사를 실행한다. CLI 골격은 Step 1부터 준비하고 Step 2~9에서 소량의 대표 fixture로 전 단계 연결을 점진적으로 검증한다. Step 11은 첫 연결 시점이 아니라 CLI 완성과 실제 데모 단계로 삼는다.

### Step 0 — 레거시 분석 및 API 계약 확인

- [x] `I:\VSCodeBases` 아래에서 `web2df`, `df2preproc`의 실제 저장소 루트를 확인한다. Windows/WSL 경로 매핑은 필요한 경우 확인하며 임의로 가정하지 않는다.
- [x] `web2df`의 식별자·중복 제거·metadata/원문 연결과 `case_full_no`, `decision_items`, `decision_gists`, `reasoning`, `applicable_acts`, `applicable_precedents` 의미를 분석한다.
- [x] `df2preproc`의 판사 표시, 별지·heading, 번호체계, whitespace, 문장 분리, 짧은 문장·숫자 fragment 규칙을 분석한다.
- [x] 규칙을 A 재사용 / B 수정 / C 폐기로 분류하고 `docs/migration-from-legacy.md`에 `Legacy Rule | Current Meaning | Decision | Replacement | Test` 표를 작성한다.
- [x] 제거할 dependency, hard-coded path, pickle 저장, DataFrame 결합, 중복·취약 regex, Python 호환성 문제 및 새 모듈 이동 위치를 기록한다.
- [x] 실제 발견한 버그·edge case를 회귀 fixture로 기록한다. 접근 불가나 미확인 내용은 추정하지 않고 명시한다.
- [x] 공식 자료로 API 인증, 목록·상세 조회, pagination, 응답 형식, 오류·호출 제한 및 이용 조건을 확인하고 출처와 확인일을 기록한다.

완료 기준: 실제 코드에 근거한 레거시 분석 문서와 API 계약 메모가 존재한다. 레거시 분석 후 구현을 시작한다. live API 접근 여부는 오프라인 개발 가능 여부와 분리한다.

2026-09-09 완료 기록: docs/migration-from-legacy.md, docs/law-open-api-contract.md, docs/step0/의 비밀값 없는 실측·소스 해시 기록 및 합성 회귀 fixture 23건을 작성했다. 사용자 제공 LAW_GO_KR_OC로 공식 API 네 요청이 성공했다. 고정 quota·전체 오류 schema·계정별 운영 승인 범위는 확인되지 않아 Step 3/운영 전 확인 항목으로 명시했다. 앱 구현·pytest·AWS 변경은 수행하지 않았다.

### Step 0A — 추가 identity·asset 조사와 설계 반영

- [x] `_01`~`_07`의 source IDs·복합 매칭·뒤 숫자 prefix 보호·증분·이미지/조문 보강 책임을 조사한다.
- [x] `docs/legacy-case-identity-and-assets.md`에 A–G 결과와 실제 저장 파일의 표식·이미지 경로 관찰을 기록한다.
- [x] identity/incremental/fidelity, architecture/schema/provenance 계약과 추가 합성 fixture 30건을 작성한다.
- [x] 기존 문서의 source ID=canonical 오해, Selenium 일괄 폐기, 필수 editorial 구조 전제를 수정한다.

문서 조사 완료. 실제 1:1 source 대조, 양 source 이미지 손실 비교 및 PDF/scan 실물은 미검증이며 아래 구현 milestone에서 검증한다. 합성 fixture 존재를 구현 테스트 통과로 세지 않는다.

### Step 1 — 프로젝트 scaffold와 품질 도구

- [x] uv 기반 src-layout, Python 3.12 제한, dependency/lockfile, ruff/mypy/pytest 설정을 구성한다.
- [x] `.gitignore`, `.env.example`, 데이터 경로와 logging/config 정책을 추가한다.
- [x] 레포 루트에 React 19 + Vite + TypeScript scaffold와 lockfile, 타입 검사·lint·build 설정을 구성한다. Python core와 프런트 의존성을 분리한다.
- [x] FastAPI app 및 CLI의 최소 진입점을 준비하고 PostgreSQL 개발·테스트 환경과 연결 설정을 문서화한다.

완료 기준: `uv sync --locked`, 패키지 import 및 초기 품질 검사 구성이 실행된다.

2026-09-10 검증: uv locked sync, Python lint/format/mypy, PostgreSQL 연결 포함 pytest 10건, 프런트 타입/lint/build, desktop/mobile E2E 6건, Compose 이미지 빌드·기동을 확인했다. 기존 합성 53건은 backend/tests/fixtures로 이동했으며 신규 domain 회귀 테스트가 실행된 것은 아니다. 테스트 라이브러리의 upstream deprecation warning 2건은 남아 있다.

### Step 1B — 기존 corpus bootstrap 조사 (Step 2 ID 확정의 선행 조건)

- [x] 최종 pickle 실제 행·컬럼·공식 ID 분포·중복·출처 연결을 전수 조사하고 CSV와 교차 확인한다.
- [x] 법원명+사건번호 업무키의 coverage·중복 representation·충돌을 분리하고 결측·타입·이미지·editorial 층화 표본을 읽는다.
- [x] 기존 ID·원문·행 locator 보존 및 재실행 가능한 초기 import, 이후 delta/refresh 계획을 기록한다.
- [x] 공식 ID를 대표값으로 계승할지 기존 별도 ID가 있는지 확인한 뒤 canonical 정책을 확정한다. 단순히 새 UUID를 부여하지 않는다.

이 단계는 기존 89,130건을 신규 수집으로 대체하는 작업이 아니다. LawnB 등 정부 ID 없는 자료에도 법원명+사건번호 업무키를 사용하며 극소수 역사적 오류는 예외 이력으로 다룬다.

2026-09-10 조사 기록: 최종 corpus 89,130행·60컬럼, 층화 195행, 두 metadata catalog와 대표 12행 대조 완료. [조사 보고서](docs/legacy-corpus-bootstrap.md)에 ID 재사용·다문서 관계·날짜 객체·bootstrap 계획을 기록했다. 후속으로 개별 결정 문서 대표값·legacy provenance 계약을 확정했다. docs/legacy-import-contract.md 참조.

### Step 2 — Domain model과 데이터 계약

- [x] Pydantic LegalCase/LegalIssueUnit/LegalAuthority/EvidenceSpan/Provenance와 SourceCaseIdentifier/CanonicalCaseIdentity/IdentityResolution/InventorySnapshot/SourceArtifact/VisualAssetReference/DocumentBlock을 정의한다.
- [x] canonical ID 생성·registry 재현·merge/split 정책을 검토해 기록하고 nullable editorial/full_text·field availability·fidelity 상태를 구현한다.
- [x] `CaseReference`, `RawLegalCase`와 구조 파싱용 번호·계층·원문 위치 정보를 정의한다.
- [x] 사건번호, 법원, 날짜, 사건명, 판시사항, 요지, 이유, 인용, URL, 원본 hash의 타입과 결측 정책을 정한다.
- [x] ID 생성, provenance, offset, alignment/quality 상태, 오류 코드, gold 포함 기준과 schema 버전을 문서화한다.

현재: 개발 중 domain schema 0.1.0에 legacy 보존 계약을 추가했다. canonical은 개별 결정 문서 단위이며 기존 registry 우선 재사용·공식 ID 우선 후보 정책을 기록했다. LegacyCaseRecord는 과거 HTTP provenance를 강제하지 않는 별도 staging이다. 실제 metadata 15행·저장 HTML 4개와 JSONL/재실행을 검증했다. 전체 corpus import, legacy→LegalCase/Issue 구조화, DB registry 트랜잭션 및 Parquet은 후속이다. Step 2 완료는 계약·표본 검증 범위이며 운영 import 완료가 아니다. 상세: docs/legacy-import-contract.md.

완료 기준: 유효·결측·잘못된 타입·offset 사례를 구분하고 직렬화 round-trip 테스트를 통과한다. `docs/dataset-schema.md`, `docs/provenance.md`에 계약이 기록된다.

### Step 2A — PostgreSQL persistence 및 migration

- [x] 도메인/DB를 분리하고 사용자·세션·작업·판례 projection 외 source-key unique·canonical registry/link revisions·inventory·fetch/asset ledger·manifest 참조를 설계한다. registry와 연결 이력을 보존 대상으로 둔다.
- [x] PostgreSQL driver·접근 도구·migration 도구를 선택하고 버전을 고정한다. Pydantic domain model을 ORM 모델에 종속시키지 않는다.
- [x] 최초 schema migration, 빈 DB 초기화 및 기존 버전에서의 업그레이드를 검증한다.
- [x] job claim, 중복 제출 방지, 상태 전이, heartbeat/lease 또는 동등한 복구 규칙을 정의하고 트랜잭션으로 구현한다.
- [x] 파일 artifact의 위치·hash·버전과 DB record 연결을 정의하고 파일 저장/DB 반영 사이의 중단을 복구할 수 있게 한다.
- [x] 조회용 projection은 artifact에서 재구성 가능하게 하고 사용자·세션·작업 상태·향후 사람의 검토 기록은 운영 DB의 보존 대상으로 구분한다.
- [x] unit 테스트는 외부 서비스 없이 실행하고 DB integration 테스트는 격리된 실제 PostgreSQL에서 실행한다. SQLite로 PostgreSQL의 트랜잭션·제약·동시성을 대신 검증하지 않는다.

완료 기준: migration으로 DB를 재현할 수 있고 중복 방지·job claim·재시작 복구와 artifact 참조 일관성 테스트를 통과한다. 운영 DB에 테스트나 초기화 작업이 실행되지 않도록 설정을 분리한다.

2026-09-10 구현: Psycopg 3.3.5 유지, numbered-sql-1 실행기와 migration 0001~0004. HTTP 내용 버전/취득 이력, legacy 표본 persistence, canonical revision·snapshot restore, item ledger, 고정된 입력의 job/attempt/checkpoint, worker heartbeat·120초 drain 및 실제 SIGTERM 복구를 구현했다. 운영 명령은 klegal ops이며 새 비공개 HTTP route는 없다. 상세 및 미실행 범위: docs/persistence-and-jobs.md. 전체 corpus import·source handler·로그인 HTTP·전체 DB/artifact 재해복구는 후속이다.


2026-09-10 최종 검증: uv locked sync·ruff check/format·mypy, pytest **140건**(실제 PostgreSQL integration **30건**) 통과. 기존 upstream warning 2건. wheel 설치본의 migration SQL 4개, Compose build/config·migration 적용/재실행·API/worker health·frontend/API HTTP 200·합성 작업 처리·drain 차단을 확인했다. [검증 기록](docs/step2a-verification.json). 로컬 runtime은 resume 상태로 worker가 가동 중이며 AWS 변경·전체 corpus import는 하지 않았다.

### Step 3 — LAW OPEN API client

- [x] `CaseSource` protocol과 `LawOpenApiCaseSource`의 목록·상세 조회를 구현한다.
- [x] pagination, limit, timeout, 제한된 retry/backoff, 호출 간격과 오류 처리를 구현한다.
- [x] transport 응답 모델과 domain mapper를 분리한다.
- [x] 정상·빈 목록·오류·pagination 종료·limit을 mock integration test로 검증한다.

완료 기준: credential 없는 테스트가 통과하며 실제 인증 설정이 있으면 소량의 API 응답을 검증한다. live 미실행은 명시한다.

### Step 3A — scourt·lawgo 현행 취득/보강 경로 검증

2026-09-10 후속: 승인한 소량 검증·목록 구현 완료. OC 포함 목록 보존, scourt 페이지 snapshot·단일 worker, 12개 legacy 표본·새 ID 후보·이미지 34곳 브라우저 대조를 수행했다. 전체 completeness·PDF/scan·운영 자원 측정은 별도 미완료다. [기록](docs/source-path-validation.md).

- [ ] 양쪽 사이트의 현행 endpoint·응답 schema·세션·DOM·popup·iframe·조문 링크·원문/asset 경로를 확인한다. 수년 전 selector·URL·형식의 호환성을 가정하지 않고 제공 정보 보존 범위에서 HTTP/세션/browser 전략을 비교한다.
- [ ] 기존 ID의 대표 표본으로 본문·조문·이미지 참조를 대조하고 구조 변경/빈 추출/오류 페이지 탐지 fixture를 만든다. 미검증 adapter의 대량 수집·보강을 시작하지 않는다.
- [ ] browser가 필요하면 Python 3.12/uv·headless·download/popup/iframe·network/DOM·Windows/Linux·testability로 Selenium/Playwright를 비교해 결정한다.
- [x] scourt metadata snapshot·기존 ID 본문 취득 adapter를 구현하고 소량 live와 offline fixture를 구분해 검증한다. 현재 jisCntntsSrno와 old contId의 일괄 동일성은 가정하지 않는다.

완료 기준: 선택 근거와 접근 조건, 동일 표본의 metadata·원문 충실도·자원 사용을 기록한다. 단순 패키지 교체나 과거 URL 재사용만으로 완료하지 않는다.

2026-09-10 부분 구현: 현재 portal.scourt.go.kr metadata·본문과 lawgo 조문 popup을 검증했다. 상세 adapter·worker 및 2쌍의 실제 표본을 보존했다. 전체 inventory·넓은 fidelity/자원 측정·목록 민감 원본 보존은 미완료다. [상세 기록](docs/source-adapters.md).

### Step 4 — Raw persistence 및 ingest

- [ ] 목록·본문 원본 바이트, hash, 수집 metadata 및 비밀값을 제외한 요청 정보를 저장한다.
- [ ] 동일 원본 재사용, 변경 버전 보존, 실패 재시도·중단 후 재개와 원자적 저장을 구현한다.

완료 기준: 동일 응답 재실행 시 중복이 없고 원본 변경 시 이전 버전이 남으며 저장한 원본만으로 다음 단계를 재실행할 수 있다.

### Step 4A — Inventory 기반 incremental ingestion

- [ ] source/retrieved_at/total_count/source_ids/metadata_hash/collector_version과 per-ID hash·범위·완전성·실패 page를 snapshot으로 보존한다.
- [ ] NEW/UNCHANGED/CHANGED/MISSING 비교, source availability, fetch ledger·실패 재시도·checkpoint를 구현한다.
- [ ] 신규 ID 취득과 기존 ID refresh를 분리하고 SOURCE_UPDATED를 실제 재조회 hash로 검증한다. 부분 snapshot으로 삭제·철회를 추론하지 않는다.

완료 기준: 오래된 선고일의 신규 ID, 재실행·중복, 같은 ID 수정, source disappearance/복귀, 범위 변화, 중단 후 미완료 fetch 재개를 검증한다.

### Step 5 — 판례 metadata 정규화

- [ ] 사건번호, 법원명, 선고일, 판결/결정 구분을 작은 parser 함수로 조합한다.
- [ ] 병합 사건번호의 전체값을 보존하고 대표값 정책을 정한다.
- [ ] encoding, whitespace, 식별자 정규화와 원문 연결 정보를 기록한다.

완료 기준: `대법원 2017. 4. 13. 선고 2017도953 판결`, 병합 사건, 법원명 변형, 날짜 오류·결측 fixture를 검증하고 실패 사유를 보존한다.

### Step 5A — Cross-source identity resolution

- [ ] 후보 생성과 전체 사건번호·법원 계층·날짜·disposition 기반 결정론적 matcher를 분리한다.
- [ ] EXACT/HIGH_CONFIDENCE/AMBIGUOUS/UNMATCHED/CONFLICT, score·signals·reason·resolver version을 저장한다.
- [ ] 복수 후보·약한 fuzzy·결측·모순을 자동 확정하지 않고 canonical link revision과 source별 provenance를 보존한다.

완료 기준: scourt snapshot→신규 contId 취득→lawgo 후보 매칭→독립 canonical 생성·source IDs 유지→confidence/reason 및 미연결 출력이 가능하다. source 추가·relink에도 과거 dataset/검토가 바뀌지 않음을 검증한다.

### Step 5B — scourt 본문·lawgo 조문 보강 계승

- [ ] 기존 보강 HTML/jtable·두 공식 ID·미확인 provenance를 보존 import한다.
- [ ] scourt 기본 본문과 lawgo가 해당 판례에 제공한 조문 연결을 보존하고 조문 artifact·보강 결과를 별도 저장한다. 독자적인 인용 해석→법령 API 직접 보강은 제외하며 법령 버전 미확인을 숨기지 않는다.
- [ ] 기본 검증된 scourt 판례를 먼저 등록하고 lawgo 보강을 비동기로 추가한다. 대기·부분 완료·실패를 분리하고 미보강 판례도 정상 보존한다.
- [ ] 이미지 original src/base/해석 URL을 보존한다. 경로 보완과 실제 binary 취득을 구분한다.
- [ ] 원문·연결·조문/규칙 version별 항목 ledger를 두고 신규/미완료만 처리한다. 부분 실패·재시작·원문 변경 후 보강 재평가를 검증한다.

근거·완료 기준: docs/legacy-enrichment-and-incremental.md. 기존 contId 차집합과 lawgo 보강 재개를 계승하며 HTML 덮어쓰기·success 문자열·행번호 단독 반영은 교체한다. 기존 Step 3의 API client 개발은 기술 검증 순서로 유지하며 corpus를 lawgo 단일 출처로 재구축하지 않는다.

### Step 6 — 판례 구조 파싱

- [ ] 판시사항, 판결요지, 판결이유, 참조조문, 참조판례를 추출한다.
- [ ] 번호·계층·원문 순서·source text 위치를 유지한다.
- [ ] 빈 section, 다중 항목, 중첩 번호, 응답 markup 변형을 테스트한다.

완료 기준: fixture에서 구조화된 LegalCase를 만들고 각 결과를 원문으로 추적할 수 있다.

### Step 6A — Source Fidelity 1: Detect / Preserve Reference

- [ ] structured/full-text/scan 처리 유형과 optional issues/summaries/reasoning을 지원한다. field 부재·미취득·parse 실패를 구분한다.
- [ ] image/PDF reference, nullable has_visual_assets/count/requires_ocr와 탐지 범위를 기록한다. URL 확장자만으로 scan 판정하지 않는다.
- [ ] original src·source page·locator·order·alt·전후 문맥·부모 artifact와 asset manifest를 보존한다. ordered blocks schema를 수용한다.

완료 기준: 추가 지시 최소 15종 fixture와 실제 표본으로 정상 full-text only, 이미지 참조, PDF_TEXT/SCAN·미확인 상태를 검증한다. binary 미취득을 성공으로 표시하지 않고 raw를 보존한다.

### Step 7 — 전처리 규칙 이전과 문장 분리

- [ ] 채택 규칙을 `input → transformation → expected output`의 독립 함수와 테스트로 재작성한다.
- [ ] 판사 표시, 별지/heading, `가.`, `(가)`, `1.`, `(1)`, 특수 번호와 formatting noise를 처리한다.
- [ ] 짧은 문장·숫자 fragment 제외 사유를 기록하고 의미 있는 숫자·법률 정보를 보존한다.
- [ ] `SentenceSplitter` protocol과 `RegexSentenceSplitter`를 구현하고 날짜·조문·괄호·인용문 분리를 검증한다.

완료 기준: 모든 이전 규칙에 테스트가 있고 Kiwi/KSS 없이 동작한다. 구조 파싱 전 최소 정리와 파싱 후 정리를 구분하여 번호 정보를 보존한다.

### Step 8 — 판시사항·판결요지 alignment

- [ ] 번호·구조 기반 연결, aligned/ambiguous/unmatched 상태, 적용 규칙과 판단 사유를 구현한다.
- [ ] 중복·누락 번호, 개수 불일치, 번호 없는 다중 항목, 일대다 사례를 테스트한다.

완료 기준: 확실한 쌍만 aligned이며 불확실한 항목도 결과와 보고서에 보존된다.

### Step 9 — LegalIssueUnit 생성과 evidence 연결

- [ ] 안정적 ID, source case 참조, original/normalized 쟁점·답변을 생성한다.
- [ ] 추적 가능한 요지·이유 evidence와 원문 위치를 연결하고 authority의 case/issue 범위를 표시한다.
- [ ] provenance와 alignment 상태를 포함한 후보 JSONL을 생성한다.

완료 기준: 후보에서 원본까지 추적되며 연결 불명확·근거 없는 record가 통과 record로 표시되지 않는다.

### Step 10 — 검증, export 및 manifest

- [ ] 사건번호, provenance, 중복 ID, 빈 쟁점·답변, evidence offset, authority 타입, encoding, 원문 연결을 검증한다.
- [ ] 통과·검토·실패 후보와 stage/record ID/오류 코드/사유를 보고서에 남긴다.
- [ ] gold 포함 정책을 적용하고 JSONL과 Parquet으로 export한다.
- [ ] dataset `0.1.0` manifest에 inventory·identity registry/link snapshot·source versions·asset manifest·규칙·설정·건수·출력 checksum을 고정한다.
- [ ] nested evidence/authority/provenance, null, 날짜의 round-trip 및 두 포맷의 의미적 동등성을 검증한다.

완료 기준: gold에 중복 ID나 잘못된 evidence가 없고 실패 후보가 추적되며 동일 입력 재실행 결과가 일치한다.

### Step 11 — CLI와 end-to-end 실행

- [ ] Typer `fetch`, `normalize`, `structure`, `build-gold`, `validate`, `stats`를 제공한다.
- [ ] 입력·출력 경로, dataset 버전, refresh·재실행 정책, 종료 코드와 보고서 경로를 명확히 한다.
- [ ] `build-gold`에서 후보 검증 후 통과 record만 발행하고 `validate`로 저장 결과를 다시 검증한다.
- [ ] fixture 기반 오프라인 전 단계 실행과 실제 공개 판례 100건 이상 수집 데모를 각각 수행한다.

완료 기준: 단계별 재실행과 전체 CLI 실행이 가능하고 수집·gold·탈락 건수를 구분해 보고한다.

### Step 11A — 일반 웹 앱과 검수 UI

- [ ] React 19 + Vite + TypeScript 프런트와 FastAPI API를 구현한다. routing과 데이터 조회 도구를 선택하고 핵심 pipeline, API, 프런트 계층을 분리한다.
- [ ] 로그인·로그아웃, 제한된 사용자 계정, 세션 보호 및 작업 실행 권한을 구현한다. 공개 회원가입은 제공하지 않는다.
- [ ] 실행별 source record/canonical/issue/asset 수, snapshot 범위·완전성·delta, identity·fidelity·asset 부분 실패를 별도로 표시한다.
- [ ] 판례 원문/정규화 결과 비교, 쟁점/답변 비교, evidence 원문 강조 및 alignment 사유를 표시한다.
- [ ] FastAPI가 웹 작업을 PostgreSQL에 등록하고 별도 Python worker가 실행한다. 긴 pipeline을 HTTP 요청이나 FastAPI BackgroundTasks에 맡기지 않는다.
- [ ] 중복 제출 방지, 진행·실패 상태 조회, 브라우저 종료 후 작업 지속 및 서버 재시작 후 복구를 검증한다.
- [ ] 같은 origin의 `/api/*`로 API를 연결하고 프런트 페이지 새로고침·직접 URL 접근, 로그인 만료, 오류·빈 상태 및 evidence 강조를 브라우저에서 검증한다.
- [ ] Python code point offset과 브라우저 문자열 인덱스 차이를 처리하고 비BMP 문자 등에서도 원문 강조가 정확한지 검증한다.
- [ ] 자동 aligned 표본과 ambiguous/unmatched 표본을 유형별로 대조하고 오류를 회귀 fixture로 기록한다.

완료 기준: 브라우저에서 인증 후 작업 실행·상태 조회·원문 검수가 가능하고 CLI와 같은 core 및 artifact를 사용한다. Phase 1의 내용 검수 UI는 조회 중심이며, 쟁점 수정·승인 기능은 Phase 1.5로 분리한다.

### Step 11B — 기존 bastion 배포와 평일 운영 자동화

- [ ] `ssh aws-bastion`의 실제 인스턴스 ID·리전·계열·OS·디스크·기존 서비스·SSH 경유 및 NAT 등 네트워크 역할을 확인한다.
- [ ] 기존 서비스와의 충돌 및 재시작 영향을 확인한 뒤 호환되는 small로 변경한다. 변경 전후 부팅·접속·기존 역할을 검증한다.
- [ ] 사용자가 보유한 korcounsel.com의 DNS 관리 위치와 기존 레코드를 확인하고 HTTPS 접속을 구성한다. 재시작 후에도 도메인 연결이 유지되도록 기존 Elastic IP 유무 등을 확인한다.
- [ ] 웹 서버는 `/`에서 React 정적 빌드 결과를 제공하고 `/api/*`를 FastAPI로 전달한다. 프런트 빌드는 로컬 또는 CI에서 수행해 운영 bastion에는 결과를 배포한다.
- [ ] API 프로세스 1개, 처리 worker 1개와 PostgreSQL로 시작한다. DB 준비·migration·서비스 시작 순서를 정의하고 상태 확인 후 요청을 받는다.
- [ ] API·worker·PostgreSQL의 자동 시작과 장애 복구, worker 자원 제한, 원본·결과·DB의 영속 저장 및 백업·복구를 구성한다.
- [ ] PostgreSQL 연결 pool, 최대 연결 수와 메모리 설정을 small의 전체 프로세스 예산에 맞춰 조정하고 DB 포트는 외부에 공개하지 않는다.
- [ ] DB 및 참조 artifact를 함께 복구할 수 있는 백업 지점·보관 정책을 정하고 격리된 환경에서 실제 복원을 검증한다.
- [ ] AWS EventBridge Scheduler 기반 평일 10시 시작, 17시 종료 준비를 구성한다. Scheduler의 기동 제어는 EC2 외부에서 실행한다.
- [ ] bastion 중지에 따른 다른 서버의 관리 접속 영향을 확인한다. 시간 외 접속이 필요하면 운영 시간 또는 수동 시작·대체 접속 경로를 확정한 뒤 중지 예약을 적용한다.
- [ ] 새 작업 접수 중단, 실행 중 작업 완료/체크포인트 저장, 중지 및 다음 시작 시 재개 흐름을 검증한다.
- [ ] 실제 small에서 대표 데이터 처리 시 최대 메모리, swap/OOM, CPU 크레딧, 디스크 증가량, 처리 시간, 웹·SSH 응답을 측정한다.

완료 기준: 운영 시간에 https://korcounsel.com에서 인증된 사용자가 접속하며 모든 운영 pipeline 로직이 해당 EC2에서 실행된다. 재시작·예약 종료·진행 작업 보호·복구와 bastion 기존 역할을 검증하고 측정 결과로 medium 증설 필요성을 판단한다.

### Step 12 — 문서와 최종 회귀 검증

- [ ] README에 환경 준비, 인증 설정, 실행 순서, 출력 위치, 재실행·실패 복구 방법을 작성한다.
- [ ] architecture/schema/provenance/migration 문서를 구현과 일치시키고 deployment/operations 문서에 도메인·인증·서비스 시작·작업 복구·가동 일정·수동 시작 절차를 기록한다.
- [ ] 대법원·헌법재판소 사건, 병합 번호, 중첩 번호, 괄호, 판사명, 숫자 많은 문장, 다중 쟁점·요지와 개수 불일치 fixture를 점검한다.
- [ ] 새 환경에서 lockfile로 재현하고 전체 품질 검사를 실행한다.

완료 기준: 아래 Definition of Done을 충족하며 실제 수행한 검증과 미수행 외부 검증을 구분해 기록한다.

## 6. 검증과 첫 데모

각 구현 단계의 기본 검증:

```bash
uv sync --locked
uv run ruff check .
uv run ruff format --check .
uv run mypy src
uv run pytest --cov=klegal_gold
```

unit은 모델·parser·변환 규칙, integration은 mock API/저장/CLI/FastAPI 및 실제 테스트 PostgreSQL 연결, regression은 레거시 및 새 edge case를 검증한다. unit suite는 외부 서비스 없이 실행하고 전체 integration에는 격리된 테스트 DB를 준비한다. 공식 API credential과 외부 인터넷 호출은 기본 suite에 요구하지 않으며 실제 API smoke test는 별도 실행한다. coverage는 기록하되 근거 없는 수치 목표를 설정하지 않는다. 프런트는 lockfile 기반 설치 후 TypeScript 검사, lint, 핵심 UI 테스트, production build와 로그인→작업 등록→진행 조회→원문 검수의 브라우저 end-to-end를 검증한다. 구체적 명령은 도구 선택 시 package.json과 README에 고정한다.

Python 3.12, `LAW_OPEN_API_OC`, `DATABASE_URL` 및 migration이 적용된 PostgreSQL을 준비한 뒤 실행할 목표 데모:

```bash
cd backend
uv sync --locked
uv run klegal fetch --limit 100
uv run klegal normalize
uv run klegal structure
uv run klegal build-gold
uv run klegal validate
uv run klegal stats
```

stats에는 단계별 판례 수, 쟁점 수, alignment 상태, 검증 통과·검토·실패 및 최종 gold 수를 표시한다.

## 7. Phase 1 Definition of Done

- [ ] uv 프로젝트, Python 3.12 제한, lockfile 및 품질 도구 구성
- [ ] 공식 OPEN API adapter로 공개 판례 100건 이상 실제 수집 검증
- [ ] raw JSON/XML 및 hash·수집 metadata 보존
- [ ] LegalCase 변환과 사건번호·법원·날짜 정규화
- [ ] 판시사항·판결요지·판결이유·참조조문·참조판례 추출
- [ ] 판시사항↔판결요지 기본 alignment 및 모호성 기록
- [ ] evidence·provenance를 포함한 LegalIssueUnit 생성
- [ ] 후보/gold 구분 및 실패·검토 보고서 보존
- [ ] JSONL·Parquet export와 타입·값 동등성 검증
- [ ] dataset 버전·manifest, 중복 방지와 재실행 검증
- [ ] unit/integration/regression 및 ruff/mypy/pytest 통과
- [ ] CLI end-to-end와 README 재현 검증
- [ ] React 19 + Vite + TypeScript production build·타입 검사·lint 및 핵심 UI/E2E 검증
- [ ] FastAPI 및 별도 Python worker, PostgreSQL 작업 상태·조회 데이터 연결
- [ ] PostgreSQL migration·실제 DB integration 테스트와 DB/artifact 백업 복원 검증
- [ ] korcounsel.com 일반 HTTPS 접속·인증 및 비인가 사용자 접근 차단
- [ ] 대시보드·원문/쟁점/evidence 검수와 표본 오류의 회귀 fixture 반영
- [ ] 웹 작업 등록·단일 worker·영속 상태·중복 제출 방지·재시작 복구
- [ ] 기존 aws-bastion small에서 실제 부하와 SSH·기존 서비스 영향 검증
- [ ] 한국 시간 평일 10~17시 운영 예약과 진행 작업 보호·시간 외 접속 절차 검증

## 8. 선행 확인 사항 및 후속 범위

| 항목 | 확인 시점 | 처리 방침 |
| --- | --- | --- |
| 레거시 저장소 실제 위치 | Step 0 | `I:\VSCodeBases` 아래에서 web2df/df2preproc 루트를 확인한 후 분석 |
| API 명세·조건·호출 제한 | Step 0~3 | 공식 문서와 실제 응답으로 확인 |
| API credential | Step 3 / 실제 데모 | 환경변수로만 사용하고 오프라인·live 검증을 분리 |
| 원문과 evidence 위치 | Step 2~6 | 기준 텍스트·추출 버전·offset 계약을 먼저 고정 |
| 전처리 의미 손실 | Step 0 / 7 | 원문 보존, 회귀 fixture와 규칙별 기록 |
| gold 포함 정책 | Step 2 / 9~10 | 위 보수적 기본 정책을 schema와 검증기로 명문화 |
| 코드 라이선스·데이터 재배포 범위 | Step 0 / 문서화 | 별도 확인 후 기록하며 라이선스를 임의 선택하지 않음 |

Phase 1 이후 실제 오류 분포를 근거로 파싱과 alignment를 개선한다. Kiwi optional adapter, KSS 실험, scourt 외 추가 source adapter와 LLM annotation은 별도 계획으로 다루며 현재 핵심 파이프라인의 의존성으로 만들지 않는다.

## 9. 웹 앱 및 AWS 운영 결정 — 2026-09-09

### 사용자 결정과 현재 확인 상태

| 항목 | 기록 |
| --- | --- |
| 접속 방식 | 처음부터 SSH 터널이 아닌 일반 브라우저 웹 접속 |
| 서비스 도메인 | 사용자가 korcounsel.com을 이미 확보함. DNS 연결·인증서·배포 여부는 미확인 |
| 사용자 | 소수의 허용된 사용자. 도메인 공개와 데이터·기능의 익명 공개를 구분 |
| 운영 서버 | 기존 SSH 별칭 aws-bastion 대상 EC2 활용. 신규 EC2 추가를 기본안으로 삼지 않음 |
| 현재 크기 | 사용자 설명상 micro. 실제 인스턴스 계열은 아직 확인하지 않음 |
| 시작 크기 | 호환되는 small로 올린 뒤 시작, 측정상 부족하면 medium 검토 |
| 프런트 | React 19 + Vite + TypeScript SPA. Next.js는 초기 구성에 사용하지 않음 |
| 백엔드 | FastAPI + 별도 Python 처리 worker. CLI는 같은 core 호출 |
| DB | 같은 EC2에서 PostgreSQL 운영. SQLite 우선 검토 방침을 대체 |
| 로직 실행 위치 | 운영 API·PostgreSQL·수집·가공·검증·export worker 모두 해당 EC2. 브라우저는 표시·상호작용 담당, 프런트 빌드는 로컬/CI |
| 운영 시간 | Asia/Seoul 기준 월~금 10:00 시작, 17:00 종료 준비. 토·일 자동 시작 없음 |
| 공휴일 | 현재 범위는 주말 제외이며 평일 공휴일은 운영 |
| 현재 작업 | 계획 기록 갱신만 수행. SSH 접속·리사이즈·DNS 변경·배포·예약 생성은 아직 미실행 |

### 단일 EC2 애플리케이션 구조

```text
사용자 브라우저 → https://korcounsel.com → HTTPS 웹 서버
  ├─ /       → React 19 + Vite 정적 빌드 파일
  └─ /api/*  → FastAPI → PostgreSQL ← 단일 Python worker
                                        ↓
                                  Python pipeline core
                                        ↓
                                원본·후보·gold·manifest

CLI → 동일 core 및 작업 상태 관리
AWS EventBridge Scheduler → EC2 시작 / 종료 준비 제어
```

- 초기에는 별도 EC2, RDS, Redis, 로드밸런서, NAT Gateway를 새로 추가하는 구성을 기본으로 하지 않는다. 기존 인프라 삭제를 뜻하지 않는다.
- 작업 상태, 실행 이력과 웹 조회용 데이터는 로컬 PostgreSQL에 저장한다. 프로세스 메모리만으로 queue와 실행 상태를 유지하지 않는다. 원본 응답과 단계별 재현 artifact 및 JSONL/Parquet export는 파일로 보존하고 DB에 위치·hash·버전을 연결한다.
- 웹 앱과 worker는 프로세스를 분리하고 별도 앱 계정으로 운영한다. 앱에 bastion 관리용 SSH 키나 불필요한 인스턴스 역할 권한이 노출되지 않도록 기존 구성과 함께 검토한다.
- 인증·세션, 상태 변경 요청 보호, 계정별 작업 권한을 적용한다. worker·데이터 저장소 포트는 외부에 직접 공개하지 않는다.
- 목록·검색·필터는 PostgreSQL의 조회용 데이터를 사용하고 원문 대조·다운로드는 연결된 artifact를 사용한다. 조회만으로 재수집·재파싱하지 않는다. UI에도 원천 텍스트를 안전하게 표시하고 임의 HTML을 실행하지 않는다.
- 작은 묶음으로 읽고 export하며 worker는 우선 하나만 실행한다. 전체 corpus의 일괄 메모리 적재를 피한다.
- 배포 전에 기존 포트, reverse proxy, SSH 경유, 네트워크 역할과 서비스 자동 시작 구성을 확인한다. bastion과 앱의 장애 영향이 공유된다는 점을 운영 문서에 기록한다.

### 종료 정책과 운영 시간 외 동작

- 평일 10:00은 EC2 시작 요청 시각이다. 앱은 부팅·서비스 준비 후 이용 가능하며 정확히 10:00에 응답이 완료된다고 보장하지 않는다.
- 17:00에는 웹과 CLI 등 모든 경로의 새 작업 접수 및 대기 작업의 신규 실행을 막고 종료 준비 상태로 전환한다.
- 실행 중 작업은 완료하거나 안전한 체크포인트에서 멈춘 뒤 상태와 결과를 저장한다. 실제 EC2 중지는 17시보다 늦어질 수 있다.
- 종료 준비와 worker 작업 획득은 경합 없이 처리한다. 예약 중지가 진행 작업을 확인하지 않고 StopInstances를 직접 호출하는 방식은 사용하지 않는다.
- 최대 유예 시간, 응답 없는 worker의 처리와 실패 알림은 자동화 구현 시 운영 설정으로 확정한다. 무기한 종료 연기나 무조건 강제 중지를 기본값으로 삼지 않는다.
- 시작 예약과 조건부 중지 제어는 EC2 외부의 AWS 관리 기능을 사용한다. 필요한 소규모 제어 함수는 앱의 데이터 처리 로직과 구분하며 별도 EC2를 요구하지 않는다.
- 토·일에는 자동 시작하지 않는다. 운영 시간 외 수동 시작 시 적용할 종료 정책도 운영 문서에 기록한다.
- EC2 중지 중에는 도메인의 웹 앱과 이 bastion을 경유하는 SSH도 사용할 수 없다. 자동 깨우기와 시간 외 안내 페이지는 별도 외부 구성 없이는 제공되지 않으며 초기 범위에 넣지 않는다.
- 다른 서버의 시간 외 관리가 필요한지 확인한 뒤 일정 적용 조건을 확정한다. 이 항목은 배포 선행 확인이며 현재 문서 갱신을 막는 사유가 아니다.

### 비용·증설 판단

- 월 22영업일, 하루 7시간이면 종료 유예를 제외한 가동 시간은 약 154시간이다. 실제 운영일·부팅·유예·수동 시작에 따라 달라진다.
- EC2 중지 후에도 EBS, 보유 Elastic IP, 백업 등의 비용은 남는다. 단가·리전·세금·사용량은 배포 시 다시 산정하며 이전 대화의 비용은 추정치로만 취급한다.
- 메모리 여유 부족, OOM, 지속적인 swap, 웹·SSH 지연을 확인하면 배치 크기·동시성·자원 제한을 조정하고 medium 증설을 검토한다.
- 현재 계열이 T3a라면 small→medium은 주로 메모리 확장이다. 지속 CPU 성능 부족은 CPU 크레딧과 처리 방식을 별도로 점검한다.
- 타입 변경 전 호환성과 중지 영향을 확인한다. small로 이미 변경되었거나 medium이 자동 적용된 것으로 기록하지 않는다.

### Phase 1.5 — 사람의 검토와 실행 비교

- 쟁점·답변 연결 수정, evidence 재선택, 승인·반려·보류와 검토 의견을 추가한다.
- 자동 artifact를 덮어쓰지 않고 대상 record/원본 hash, 검토자, 시각, 수정 내용과 사유를 별도 기록한다.
- 원본 또는 parser 버전 변경 시 기존 검토 결정의 재사용 가능 여부를 판단한다.
- 실행 간 쟁점·답변·근거·검증 상태의 차이를 비교하고 사람이 검토한 자료와 자동 통과 자료를 구분해 내보낸다.

## 10. 기술 스택 확정 및 선택 근거 — 2026-09-09

### 확정 구성

| 계층 | 선택 | 역할 |
| --- | --- | --- |
| 프런트 | React 19 + Vite + TypeScript | 대시보드, 판례·쟁점 검수, 작업 실행·진행 조회 |
| API | FastAPI + ASGI 서버 | 인증·세션, 권한 확인, 조회·작업 등록·상태 API |
| 데이터 처리 | 별도 Python worker | 수집, 정규화, 파싱, alignment, 검증, export |
| 운영 DB | PostgreSQL, 같은 aws-bastion EC2 | 사용자·세션, queue·실행 이력, 조회용 판례·쟁점·근거, 검토 이력 |
| 파일 저장 | EBS의 원본 및 JSONL/Parquet artifact | 원본 보존, 단계별 재현, dataset export |
| HTTPS·정적 파일 | reverse proxy/web server | korcounsel.com TLS, React 파일 제공, /api 전달 |
| 관리 도구 | CLI | API와 같은 core를 이용한 개발·운영 |

### React/Vite를 선택한 이유

- Next.js는 React 기반 프레임워크이며 React 19와 서로 대체하는 라이브러리 관계가 아니다. 이번 선택은 Next.js 기반 앱과 Vite 기반 React 앱의 비교다.
- 현재 앱은 로그인 후 사용하는 소수 사용자용 검수·대시보드로, 공개 판례 콘텐츠의 검색 노출이나 서버 렌더링을 초기 핵심 요구로 삼지 않는다.
- FastAPI가 API·인증·처리 접점을 담당하므로 프런트는 정적 SPA로 제공한다. 운영 중 별도 프런트 Node.js 서버를 상시 실행하지 않는다.
- Next.js도 정적 export가 가능하므로 무조건 더 무겁다고 단정하지 않는다. 현재 필요한 기능과 운영 단순성을 근거로 Vite를 선택했다.
- routing과 데이터 조회·캐시 도구는 프런트 구현 시 선택한다. 초기 결정에 포함되지 않은 UI 라이브러리나 상태 관리 프레임워크를 확정된 것으로 기록하지 않는다.
- 프런트 dependency 설치와 production build는 로컬/CI에서 수행하고 검증된 정적 결과를 배포한다. 운영 서버에서 Vite 개발 서버를 서비스하지 않는다.

### FastAPI와 core의 경계

- Python 3.12·Pydantic 중심 domain model과 검증 기능을 활용한다. 인증·권한·입력 검증은 API에서 수행하며 pipeline은 웹 프레임워크에 종속시키지 않는다.
- 오래 걸리는 작업은 PostgreSQL 등록 후 worker가 수행한다. FastAPI BackgroundTasks를 영속 queue나 재시작 복구 수단으로 사용하지 않는다.
- 초기 API 프로세스는 1개, 데이터 처리 worker도 1개로 시작한다. FastAPI의 API worker 수와 별도 데이터 처리 worker 수를 구분한다.
- CLI와 웹에서 동일 작업이 중복 실행되지 않도록 job claim과 종료 준비 상태를 공유한다.
- 프런트는 DB에 직접 접근하지 않고 `/api/*`를 이용한다. 동일 origin으로 제공하되 인증, 세션, 상태 변경 요청 보호는 별도 구현한다.

### PostgreSQL과 artifact의 책임

| 데이터 | 보존 위치 및 기준 |
| --- | --- |
| 사용자·권한·세션 | PostgreSQL이 운영 기준 |
| 작업 queue·상태·실행 이력·오류 | PostgreSQL에 영속화하고 재시작 시 복구 |
| 판례·쟁점·근거의 목록·검색용 정보 | PostgreSQL 조회 projection, 원본·구조화 artifact와 버전 연결 |
| 사람의 검토·수정 이력 | Phase 1.5부터 PostgreSQL에 별도 기록, 자동 결과 재생성으로 삭제하지 않음 |
| 원본 API JSON/XML | 바이트를 보존한 immutable artifact |
| 단계별 결과·최종 JSONL/Parquet | 재현·export용 artifact |
| dataset manifest | 릴리스 파일을 보존하고 DB에 릴리스 참조·조회 정보를 연결 |

- DB 도입으로 원본 보존과 JSONL/Parquet 정책을 대체하지 않는다. domain model을 DataFrame이나 ORM 중심으로 재구성하지 않는다.
- schema migration을 코드와 함께 버전 관리하고 신규 설치·업그레이드를 검증한다. 배포 롤백 시 앱과 DB schema의 호환성을 확인하고 필요한 복구 방법을 문서화한다.
- 같은 EC2의 PostgreSQL은 RDS 추가와 구분한다. 자동 managed backup이 있다고 가정하지 않고 DB와 참조 artifact의 일관된 백업·복구를 구현한다.
- small은 API·worker·DB·OS·bastion 기능이 메모리를 공유한다. DB 전용 서버 기준의 메모리 비율을 그대로 적용하지 않으며 작은 connection pool과 보수적 설정부터 측정한다.
- PostgreSQL도 함께 운영하는 조건으로 small 부하 테스트를 다시 수행한다. 필요 시 medium으로 확장하되 기존 bastion 역할과 평일 가동·종료 정책은 유지한다.

### 구현 시 선택·고정할 항목

Step 1에서 Node 24.16.0, pnpm 11.23.0, React 19.3.0, Vite 8.2.2, TypeScript 5.9.3, uv 0.12.5 및 Python 3.12를 사용했다. Python/Node 의존성의 정확한 해상 버전은 lockfile에 고정했다. DB 연결은 Psycopg 3, 로컬 서버는 PostgreSQL 17, 웹 서버는 Nginx다. Step 2A는 ORM 없이 Psycopg와 번호순 SQL migration 실행기를 선택했다. router·조회 라이브러리와 운영 TLS는 후속 선택이다.

### 참고한 공식 문서

- [React 앱 구성과 Vite](https://react.dev/learn/build-a-react-app-from-scratch)
- [Vite 정적 배포](https://vite.dev/guide/static-deploy.html)
- [Next.js 정적 export](https://nextjs.org/docs/app/guides/static-exports)
- [FastAPI 프로세스와 메모리](https://fastapi.tiangolo.com/deployment/concepts/)
- [FastAPI BackgroundTasks](https://fastapi.tiangolo.com/tutorial/background-tasks/)
- [PostgreSQL 메모리 설정](https://www.postgresql.org/docs/current/runtime-config-resource.html)

## 11. 루트 문서 및 배포 자료 구조 — 2026-09-09

- README.md에 목적·현재 구현 전 상태·확정 스택·데이터 경계·목표 실행 명령·운영 방침을 작성했다.
- 인접 onju-ai-kr/AGENTS.md와 DESIGN.md를 읽고 작업 원칙, domain/adapters 경계, provenance·immutable history, 정확한 검수 대상, uncertain-operation 처리, professional legal-workbench 색상·3단 layout·접근성, 배포·secret·검증 지침을 이 프로젝트에 맞게 이전했다.
- 참조 프로젝트의 Next.js 루트 앱/backend 구조, 공개 주석 reader, AI draft/출판, editor roster·SES·채팅, ALB·별도 호스트, 전용 env·Compose 버전과 구현 완료 기록은 이식하지 않았다. 사용자 승인 범위에 따른 작업 진행 원칙을 유지한다.
- README는 사용·운영 안내, AGENTS는 작업 지침, DESIGN은 UX 기준이며 구현 순서와 완료 판단은 루트 PLAN을 따른다.
- 배포 자료 경로는 .fordeploy/로 통일한다. 기존 ops/ 계획은 대체하며 별도 배포 루트를 중복 생성하지 않는다. 설명은 README와 docs에 기록한다.
- .fordeploy/aws-backup/.gitkeep을 빈 파일로 생성했다. 실제 백업·배포 archive는 생성하지 않았다. 이후 사용자가 .env를 제공했으며 .gitignore로 제외한다.
- 향후 Docker 사용 시 staging·secret·runtime 자료가 build context에 포함되지 않도록 루트 .dockerignore를 추가했다. Docker/Compose 로컬 구성은 Step 1에 추가했다. 실제 AWS 배포·TLS·예약은 후속이다.
- 문서와 제외 규칙만 변경했다. 실제 인프라·DB·DNS·인증서·운영 예약 변경이나 서버 접속은 수행하지 않았다.

## 12. 추가 지시 적용과 후속 fidelity

2026-09-09 추가 지시는 기존의 단일 API·text 중심 가정을 확장한다. 상세 계약은 docs/architecture.md, case-identity.md, incremental-ingestion.md, source-fidelity.md, dataset-schema.md, provenance.md에 둔다. 기존 Step 0은 당시 범위의 완료 기록이며 확장 milestone의 구현 완료를 뜻하지 않는다.

실행 순서는 Step 0A → 1 → 2 → 2A → 3/3A → 4/4A → 5/5A → 6/6A → 7~12다. 두 source adapter의 독립 작업은 필요한 공통 계약을 먼저 고정한 뒤 진행한다. 기존 웹·EC2·PostgreSQL 결정은 유지한다.

후속 Source Fidelity 2는 Stage C 취득(binary+metadata, SHA-256/MIME/size, retry/failure manifest/storage), Stage D 실제 문서 위치 복원, Stage E OCR adapter/해석 순서다. 최초 milestone에 전체 이미지 다운로드·완전 layout·OCR를 밀어 넣지 않는다. OCR/vision/LLM은 별도 후속 범위다.

확장 DoD:

- [ ] scourt/lawgo inventory 및 source key를 보존하고 신규만 fetch·refresh·실패 재개를 검증한다.
- [ ] canonical identity와 confidence/reason, AMBIGUOUS/UNMATCHED/CONFLICT를 출력하고 잘못된 source 병합을 막는다.
- [ ] 판시사항·요지 없는 정상 record, source artifact 유형, image reference·문맥·order, requires_ocr/UNKNOWN과 manifest를 검증한다.
- [ ] case ingestion 성공·asset 부분 실패·OCR 미처리를 독립적으로 표현하고 필요한 evidence가 부족한 gold 발행을 막는다.
- [ ] 실제 source pairing·이미지 누락 비교·PDF/scan 실물 검증의 미완료를 보고서에 남기고 완료 전 실측한다.
- [ ] source/identity/asset 이력·snapshot과 DB를 일관되게 백업·복구하고 small EC2에서 browser·asset 자원을 측정한다.

2026-09-10 최종 검증: backend에서 uv ruff check·ruff format --check·mypy 통과, 로컬 PostgreSQL 연결 포함 pytest **105건 통과**. 기존 upstream deprecation warning 2건 유지. 실제 metadata 15행·저장 HTML 4개 검증 및 git diff --check 통과. 프런트·분석 전용 도구는 변경하지 않았으며 해당 테스트를 이번 작업에서 재실행하지 않았다.
