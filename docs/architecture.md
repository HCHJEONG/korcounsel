# 아키텍처 설계

2026-09-09 추가 지시 반영. 구현 전 계약이다. React 19/Vite/TypeScript, FastAPI, Python 3.12/uv, PostgreSQL과 기존 aws-bastion 운영 결정은 유지한다.

```text
sources/scourt      sources/law_go_kr
      └──── source inventories ────┘
                     ↓
ingestion: snapshot delta + fetch ledger + refresh
                     ↓
storage: immutable source versions / raw
                     ↓
normalize → identity resolver → versioned canonical links
                     ↓
documents + assets: classify / detect / preserve references
                     ↓
LegalCase: structured fields | full text | scan/artifact references
                     ↓
parse / segment / alignment (지원되는 structured 입력)
                     ↓
LegalIssueUnit candidates → validate → gold / reports
```

| 경계 | 책임 |
| --- | --- |
| domain | LegalCase/Issue/Evidence/Authority/Provenance와 공용 ID·snapshot·artifact 계약 |
| identity | metadata 신호 정규화, 후보, 결정론적 점수, 충돌·versioned linking |
| ingestion | source inventory 비교, fetch/refresh 계획, checkpoint·재시도; jobs와 분리 |
| sources | API/HTTP/browser 실제 취득. transport·session은 core 밖 |
| documents | artifact 분류, ordered block, text 추출 기준 |
| assets | 탐지·reference manifest; 후속 binary 취득 |
| enrichment | 초기 확장 조문 내용 보강. source 원문과 별도 파생 결과 |
| storage / db | 불변 파일·manifest / identity registry·작업·사용자·조회 projection·review |
| jobs / pipeline | 영속 작업 실행 / CLI·웹 공용 유스케이스 |
| web / frontend | 인증 API / 읽기·작업·상태 UX. 독자적 matching·gold 정책 없음 |

공유 metadata 정규화는 normalize에 두고 identity는 이를 사용한다. identity별 특수 정규화가 필요하면 명시적 wrapper를 둬 중복 regex를 늘리지 않는다. sources/scourt 같은 미래 모듈은 해당 단계에 실제 구현할 때 생성한다.

identity 연결, 원문 취득, asset 취득, OCR, issue alignment, 자동 검증과 사람 검토는 별도 상태다. canonical이 같아도 source별 내용을 덮어 합치지 않는다. 재현 입력에 inventory·identity registry/link revision·artifact hashes·규칙 버전을 포함한다.

기존 EC2 한 대에 API 1개·worker 1개·PostgreSQL을 둔다. browser가 필요하면 worker의 제한된 작업으로 실행하고 웹 프로세스에 붙이지 않는다. asset 크기·보관량·browser 최대 메모리를 운영 전 측정하며 새 EC2·GPU를 기본으로 추가하지 않는다. 17시 drain은 snapshot/page·fetch·asset ledger를 보존해야 한다.

세부 계약: [identity](case-identity.md), [incremental](incremental-ingestion.md), [fidelity](source-fidelity.md), [schema](dataset-schema.md), [provenance](provenance.md).


## 폴더·도구 결정 — 2026-09-10

루트 src/·package.json은 프런트, backend/는 pyproject.toml·uv.lock·backend/src/klegal_gold를 가진 독립 Python 프로젝트다. README는 루트 하나로 통합했다. 문서·배포는 루트 docs/·.fordeploy/, Compose는 루트 compose.yaml/compose.dev.yaml이다. 내부 모듈 배치는 변경 가능한 초안이며 단계에 필요한 코드만 만든다.

Step 1은 공개 법률 데이터가 없는 개발용 상태 화면, /api/health liveness, CLI version/check-config/check-db, explicit env 및 PostgreSQL SELECT 1 검증을 제공한다. health 성공은 DB·worker 준비 완료가 아니다. Step 2A에서 실제 queue/worker와 SQL migration을 추가했다. worker는 artifact 검증과 projection 재생성을 실행하며 migration만 tools profile의 명시적 명령이다.

API·worker 이미지는 backend/를 build context로, 프런트 이미지는 루트를 context로 사용한다. 루트 .dockerignore는 backend·data·.fordeploy·secret을 제외하며 Nginx 설정은 Compose의 읽기 전용 mount로 전달한다. 실제 이미지 취득·TLS·운영 배포는 후속이다. DB와 판례 데이터는 각각 named volume을 사용하고 `down -v`를 일반 종료 절차에 사용하지 않는다.


## 기존 corpus bootstrap 우선 — 2026-09-10

legacy archive → 읽기 전용 전수/표본 audit → ID/업무키·결정 문서/출처 표현 구분 → 보존 import + mapping manifest → inventory delta/refresh 순서로 확장한다. UUID 발급은 선결정하지 않는다. 공식 ID가 없는 자료는 법원명+사건번호 업무키와 legacy locator를 유지한다. 일회성 분석용 pandas/NumPy는 runtime dependency가 아니다.

Step 2 domain 초안은 backend/src/klegal_gold/domain/에 있으며 표본용 ingestion/legacy.py staging mapper를 추가했으며 전체 import는 후속이며 DB registry는 Step 2A에서 구현했다. [bootstrap 조사](legacy-corpus-bootstrap.md)의 결측·문서 단위·과거 provenance 문제를 해결하고 고정한 [legacy 계약](legacy-import-contract.md)을 기준으로 Step 2A migration을 구현·검증했다.

## 기본 본문과 보강 역할

scourt 기본 본문, lawgo metadata/조문 보강, 기존 corpus baseline을 계승한다. enrichment는 초기 확장 Step 5B에서 ledger와 출처별 artifact를 연결한다. 원본·조문·보강 결과는 각각 보존하며 실제 이미지 취득은 별도다. [검증한 레거시 전략](legacy-enrichment-and-incremental.md)을 따른다.

## 수집 속도와 보강 범위

scourt 기본 검증·등록은 lawgo 보강 완료를 기다리지 않는다. 정부 제공 판례/조문 연결만 출처별로 결합하며 독자적인 인용 해석 기반 직접 법령 보강은 채택하지 않는다. 양쪽 HTML·세션·내부 endpoint의 현행 호환성은 Step 3A에서 검증하며 과거 구현을 현재 작동 계약으로 간주하지 않는다.

## Step 2A persistence 구현

[저장·worker 계약](persistence-and-jobs.md)에 현재 테이블·SQL migration·파일/DB 복구·registry snapshot·고정 입력 job·drain·실제 검증 범위를 기록했다. db/records.py와 registry.py·ledger.py가 domain과 PostgreSQL을 연결하고 jobs/queue.py·worker.py를 로컬 CLI와 공유한다. 로그인 HTTP와 실제 source adapter는 후속이며 private API를 추가하지 않았다.
