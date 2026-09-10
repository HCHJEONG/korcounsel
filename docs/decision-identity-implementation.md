# 재판결과 키와 출처 독립 canonical 구현

2026-09-10. 사용자가 확정한 법원 명칭 + 사건번호 + 재판 종류 규칙과 출처 독립 canonical 정책을 코드에 반영했다.

## 구현된 계약

- `DecisionKey(court, case_number, decision_kind)`는 날짜·출처 ID를 포함하지 않는다. `CourtCaseKey`는 기존 사건 단위 모델로 유지한다.
- `normalize/decision.py`의 `decision-key-1` 규칙은 판결·결정·중간판결·명령·재결과 관찰된 전원합의체판결/전원합의체결정 표기를 처리한다. 재결 지원은 그 기관을 법원으로 재분류한다는 뜻이 아니다.
- 명시적 쉼표 병합 표기의 전체 번호와 숫자 생략형을 처리한다. 예: 85후40, 41 → 85후40·85후41. 원표기는 기존 metadata/행에 남고, 지원하지 않는 표기는 추측하지 않는다. 지원·지부 명칭은 자르거나 합치지 않는다.
- metadata의 법원·전체 번호와 연결 키가 상충하면 거부한다. 재판 종류 결측·미지원, 해석되지 않은 사건번호는 완전한 재판결과 키를 만들지 않는다. legacy mapper는 결측·해석 불가 사유와 원행을 보존한다.
- 기존 `CanonicalCaseIdentity`의 직렬화 필드를 변경하지 않았다. 재판결과 키는 보존 metadata와 사건 키에서 파생하므로 과거 이벤트 payload·release를 새 필드로 다시 쓰지 않는다.

## 내부 ID와 등록 재실행

`canonical_id_for_request`는 고정 규칙 `canonical-allocation-1`과 등록 request key의 SHA-256으로 `kc:<64자리 hash>`를 만든다. UUID는 강제하지 않는다. 원본 내용 hash나 법원·사건번호·출처 ID를 canonical 값으로 직접 사용하지 않는다.

legacy의 request key는 기존 `preservation_id`(snapshot hash + 원래 position)다. 같은 보존 행을 다시 처리하면 같은 후보를 만들며 source ID나 내용이 바뀌었다고 후보를 재발급하지 않는다. snapshot/행이 다른 후보는 다른 값을 가질 수 있다. **후보의 차이는 서로 다른 재판결과라는 판정이 아니다.** 다른 snapshot의 같은 문서는 기존 registry를 대조해 연결해야 한다.

`Registry.register`는 검증한 metadata·사건 키·출처 식별자·actor·reason 및 request key를 받는다. 같은 요청은 하나의 트랜잭션·고정 event ID로 최초 등록 revision을 재사용한다. 같은 key로 내용을 바꿔 재요청하면 IDENTITY_REQUEST_CONFLICT다. 후속 RELINK 뒤 재시도해도 최초 등록 결과를 반환하며 현재 상태는 get/find_decision으로 조회한다. 등록 request key에 출처 번호를 대신 넣지 않는다.

이미 연결된 재판결과 키의 다른 등록 요청은 DECISION_KEY_ALREADY_LINKED로 거부한다. `find_decision`으로 기존 canonical을 확인한 뒤 명시적 연결 검토를 거쳐 RELINK한다. 키가 같다는 사실만으로 원자료 충돌을 무시하고 자동 병합하지 않는다.

`Registry.apply`는 과거 opaque ID와 이력을 읽고 재현하는 하위 이벤트 경로로 유지했다. 신규 발급에는 register를 사용한다. 기존 source 기반 staging 후보도 역직렬화할 수 있지만 mapper 0.2.0은 새 출처 독립 후보를 만든다. 과거 staging artifact·규칙 버전·content revision은 덮어쓰지 않는다.

## PostgreSQL과 이력

migration 0007_decision_keys.sql은 `active_decision_keys`를 추가한다. 법원·사건번호·재판 종류의 복합 PRIMARY KEY와 문서 revision FK를 가지며 registry advisory lock 안에서 출처 연결과 함께 갱신한다. 실패 시 이벤트·현재 연결 전체가 rollback된다.

판결·결정·중간판결은 같은 사건 아래 별개로 등록할 수 있다. 같은 재판결과의 출처 번호 추가는 같은 canonical의 새 revision이며 옛 번호·원본을 덮어쓰지 않는다. 과거 revision과 registry snapshot은 계속 보존하고 snapshot 복원으로 키 인덱스도 재구성한다.

업그레이드는 기존 활성 자료의 지원되는 단일 사건번호와 재판 종류를 보수적으로 backfill한다. 기존 complete key 충돌은 UNIQUE 실패로 중단한다. 기존 병합/미지원 표기나 법원 충돌은 DECISION_KEY_BACKFILL_REVIEW_REQUIRED로 중단하며 기존 자료를 자동 수정하지 않는다. 누락·미지원 종류는 기존 자료를 그대로 유지하고 키를 확정하지 않는다. 이미 적용된 0001–0006은 수정하지 않았다.

현재 로컬 개발 DB의 0007 적용은 성공했다. 전체 corpus가 등록된 운영 DB의 업그레이드를 검증한 것은 아니다.

## 검증

- ruff check/format, mypy 40개 source 파일 통과.
- 전체 pytest 252건(실제 PostgreSQL integration 47건) 통과, 기존 upstream deprecation warning 2건.
- 실제 PostgreSQL에서 동일 요청 동시 등록·서로 다른 요청의 동일 키 경쟁, 사건 내 재판 종류 구별, 병합 alias 충돌, 옛/새 출처 번호 연결, 이전 revision 보존, 재시도, migration backfill/충돌 rollback, snapshot 복원을 검증했다.
- 실제 legacy metadata 15행의 새 mapper 보존·JSONL round-trip·재실행을 확인했다. 이번 표본 검증에서 저장 본문 파일을 추가로 읽지는 않았다. [표본 결과](identity-legacy-sample-verification.json).
- API·worker용 로컬 Compose 이미지를 재빌드하고 0007을 적용했다. API·worker·DB·web healthy, worker heartbeat 정상, draining=false/running=0을 확인했다. AWS·실제 출처 재조회·전체 corpus import·새 후보의 동일성 확정은 수행하지 않았다.

## 다음 단계

기존 89,130행 FULL_ROW 보존 importer와 항목별 ledger·재개·격리 보고서를 연결한다. 먼저 표본에서 재판 종류·병합 번호·충돌을 검토하고 registry 등록 범위를 확정한다. 현재 구현은 검증된 등록을 위한 Python repository이며 자동 source matcher·검토 HTTP/UI 또는 전체 수집 등록 pipeline은 아니다.
