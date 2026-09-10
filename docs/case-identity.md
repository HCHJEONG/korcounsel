# 판례 식별과 기존 corpus 계승 계약

## 중요 도메인 규칙: 재판결과의 업무 식별키 — 2026-09-10

> **법원 명칭 + 사건번호 + 재판 종류의 세 가지 조합은 제도적으로 특정 재판결과를 식별한다.** 사용자가 명시한 도메인 규칙으로 기록하며 identity 설계의 기준으로 적용한다. 이번 기록은 별도의 법령 조사 결과가 아니다.

| 식별 대상 | 업무키 또는 ID |
| --- | --- |
| 사건 | 법원 명칭 + 사건번호 (기존 CourtCaseKey) |
| 재판결과 | **법원 명칭 + 사건번호 + 재판 종류** |
| 내부 개별 결정 문서 | 출처와 독립적인 canonical ID; 재판결과 업무키와 연결 |
| 출처 표현·취득 이력 | scourt contId/jisCntntsSrno, lawgo serialno 및 원본 hash·관찰 시각·연결 revision |

재판 종류는 판결·결정·중간판결 등 재판결과를 구분하는 종류다. 형사·민사 같은 사건 분류나 인용·기각 같은 주문 결과와 혼용하지 않는다. 세부 어휘와 출처 필드 대응은 원표기를 보존하며 별도 정규화 계약으로 구현한다. 법원 지원·지부 및 전체 병합 사건번호도 보존한다.

선고일은 대조·오류 탐지 정보이며 이 세 가지 업무키에 필수 구성요소로 추가하지 않는다. 같은 사건의 판결과 결정, 판결과 중간판결은 재판 종류가 다른 재판결과로 구별한다. 서로 다른 source ID나 내용 버전이 같은 재판결과를 표현할 수 있으며 이를 별개의 재판결과로 자동 분리하지 않는다.

입력 metadata의 정확성과 이 제도적 식별 규칙은 구분한다. 재판 종류가 누락되거나 출처 간 값이 상충하면 완전한 재판결과 키를 확정하지 않고 결측·충돌로 보존한다. 세 값이 같지만 날짜·본문 등이 충돌하면 원자료와 연결 근거를 검토한다. 데이터 오류를 피하려고 날짜나 source ID를 임의로 키에 덧붙이거나, 상충하는 원자료를 자동 병합·삭제하지 않는다.

**현재 구현:** CourtCaseKey를 유지하고 DecisionKey, 보수적 정규화, 독립 canonical 등록, migration 0007과 충돌 검증을 구현했다. 기존 데이터·검토 이력을 재번호하지 않았다. [상세 계약](decision-identity-implementation.md).

## 중요 결정: 출처 ID를 canonical ID로 사용하지 않는다 — 2026-09-10

> **contId와 serialno의 영구 안정성을 전제하지 않는다. 신규 canonical ID는 출처 ID와 독립적으로 발급·유지한다.** 이는 기존의 공식 ID 우선 대표값 정책을 대체하는 사용자 결정이다. 현재 발급 형식은 kc:<SHA-256>이며 등록 request key를 사용하는 canonical-allocation-1 규칙으로 고정했다.

실측에서는 기존 번호가 미조회되고 같은 사건의 다른 번호 후보가 발견됐다. 공식적인 번호 변경·재발급·삭제 후 재등록 여부와 전체 본문 동일성은 미확인이다. 따라서 “전체 ID가 변경됐다”거나 “동일 문서로 확정됐다”고 기록하지 않는다. [표본과 원본 증거](source-path-validation.md)를 따른다.

- scourt: 레거시 contId에 해당하는 현재 상세 요청·응답 필드는 jisCntntsSrno다. 기존 번호가 유지되는 사례도 있다.
- lawgo: 레거시 serialno는 API의 판례일련번호/판례정보일련번호를 보존한 필드다. 이름 차이와 번호 값 차이를 구분한다.
- 두 출처 ID는 관찰 당시의 source 식별자이자 재조회·변경 추적 키다. source namespace, 원래 필드명·값, 취득/관찰 시각, 원본 hash 및 연결 revision을 함께 보존한다. 레거시에 없는 과거 취득 시각은 만들지 않는다.
- 내부 canonical ID는 개별 결정 문서를 가리키며 출처 번호 교체·추가로 변경하지 않는다. 법원명+사건번호 업무키와 구분한다.
- 새 source ID는 신규 출처 관찰이다. 새 판례로 자동 확정하지 않고 법원·전체 병합 번호·날짜·문서 종류·본문을 대조해 동일 문서 여부를 판단한다. 기존 번호와 원본을 보존하고 확인된 연결만 새 revision으로 추가한다.
- 기존 발급값·release·검토 기록을 일괄 재번호하거나 덮어쓰지 않는다. 이미 확정된 내부 ID는 명시적인 이력 보존 전환 정책으로 다루며, 옛 source 값에서 유래했다는 이유로 현재 출처 번호와 동기화하지 않는다.

**현재 구현:** legacy mapper 0.2.0과 Registry.register는 출처 독립 ID를 사용한다. 같은 보존 행/등록 요청은 같은 ID를 재사용한다. 과거 source 기반 후보는 읽기 호환성을 유지하며 기존 artifact를 덮어쓰지 않는다. [발급·동시성·이력 계약](decision-identity-implementation.md).


2026-09-10 사용자 추가 결정 반영. 기존 corpus 분석 후 canonical을 개별 결정 문서 단위로 확정했다. 신규 대표값 후보·기존 registry 재사용·merge/split 계약은 [legacy import 계약](legacy-import-contract.md)을 따른다. 아래 조사 전 원칙은 이 확정 정책과 함께 읽는다.

## 기존 자료가 출발점

기존 약 9만 건을 신규 수집으로 대체하지 않는다. 기존 판례·공식 ID·출처 연결·원문 표현·행 참조를 보존해 초기 corpus로 가져오고 이후 신규/변경분을 확장한다. 기존 ID는 출처 및 역사적 연결 자료로 계승한다. 신규 canonical 발급에는 위의 독립 ID 정책을 적용하며 기존 자료를 일괄 재번호하지 않는다.

canonical_id는 모델에서 opaque 문자열이다. 신규 값은 정부 ID에서 파생하지 않으며 정부 ID는 source namespace와 함께 별도 보존한다. canonical의 논리적 역할과 source별 ID의 역할을 구분한다는 원칙은 **반드시 다른 난수 값을 발급해야 한다는 뜻이 아니다**. scourt와 law_go_kr에서 숫자가 같다고 같은 source ID로 취급하지 않는다.

## 식별 축

| 대상 | 계약 |
| --- | --- |
| CourtCaseKey | **법원명 + 사건번호**. 사용자가 확인한 고유 업무 식별키. 정부 ID 없는 LawnB 보유 판례도 등록·대조 가능 |
| 재판결과 업무키 | **법원 명칭 + 사건번호 + 재판 종류**. 특정 재판결과를 식별하는 사용자 확정 도메인 규칙 |
| source 식별자 | scourt contId, law_go_kr 판례일련번호, 존재하는 LawnB 자체 ID를 각각 원래 namespace에서 보존 |
| canonical_id | registry에서 대표 판례를 가리키는 안정적인 값. 개별 결정 문서 대표값; 기존 확정 연결은 이력 보존, 미등록은 출처 독립 ID 발급 |
| 내용/연결 revision | source bytes hash, issue content revision, identity link revision을 각각 보존. 등록키·내용 변경·연결 정정을 혼동하지 않음 |

정부 ID가 없다는 이유로 레거시 행을 버리거나 가짜 정부 ID를 만들지 않는다. 기존 행은 snapshot 파일 hash + 원래 index/position으로도 추적한다. 이는 원자료의 행 locator이며 법원명+사건번호 업무키나 법적 판례 identity 자체를 대신하지 않는다.

## 법원명 + 사건번호 업무키

이 조합을 canonical과 함께 사용할 고유키로 유지한다. 드물게 발견된 과거 수작업 오류는 명시적 충돌/예외 기록으로 관리하고, 그러한 예외 때문에 조합의 고유성을 일반적으로 포기하지 않는다. 이 원칙은 2026-09-10 사용자의 도메인 지식에 따른 프로젝트 결정이다.

- 법원 지원·지부를 보존한다. alias 정규화 규칙과 원문을 함께 기록한다.
- 전체 병합 사건번호를 보존하고 각 사건번호를 해당 법원과 결합한 key alias로 연결한다. 첫 번호만 남기지 않는다.
- 재판 종류는 사건 업무키에 더해 재판결과 업무키를 구성한다. 선고일·내용 hash는 대조·오류 발견·버전 구별 정보이며 재판결과 업무키에 필수로 추가하지 않는다.
- 같은 업무키에 여러 원자료 행이 있으면 출처별 중복 representation인지, 연결/입력 오류인지 확인한다. 중복 행 수를 곧바로 제도상 고유성 예외 수로 세지 않는다.
- 충돌은 두 자료를 보존하고 사유·검토 결과를 남긴다. silent overwrite, first-hit merge, 일괄 drop_duplicates를 사용하지 않는다.
- 정상 key의 unique 제약과 예외 승인 이력/alias 설계는 Step 2A에서 실제 PostgreSQL로 구현한다.

LawnB 판례 등록을 위한 식별 계약은 포함한다. 이 결정이 LawnB 신규 crawler 실행이나 자료 재배포 허용을 뜻하지는 않는다.

## 출처 간 연결 결과

`IdentityResolution`은 EXACT/HIGH_CONFIDENCE/AMBIGUOUS/UNMATCHED/CONFLICT, 후보 metadata hash, MATCH/MISMATCH/MISSING 신호, 규칙 점수·사유·resolver version·run_id를 저장한다. 점수는 확률이 아니다. 모델 검증은 결과의 형태·모순을 검사하며 실제 후보 생성/매칭 알고리즘은 Step 5A다.

현재 초안의 EXACT는 완전한 metadata와 유일 후보를 확인하는 보수적 출처 연결 상태다. 이 조건을 법원명+사건번호 업무키의 고유성 요건으로 확대하지 않는다. 날짜 결측 때문에 업무키 자체를 무효로 만들지 않는다. HIGH_CONFIDENCE 규칙·threshold는 아직 고정하지 않았다.

기존 `gmeta_contId↔lmeta_serialno` 연결은 버리지 않고 LEGACY 관찰로 가져온다. 과거 느슨한 매칭을 새 resolver의 EXACT로 자동 승격하지 않는다. 연결 신뢰도 확인이 끝나지 않았어도 source-local 원자료를 보존·조회할 수 있어야 한다.

## 재현과 정정

원자료 import manifest는 입력 파일 checksum, 원래 index/position, 기존 source IDs·업무키·대표값, import rules version 및 충돌 보고서를 고정한다. 같은 입력을 재실행하면 기존 행/ID를 재사용하도록 한다. 새로운 수집과 최초 legacy import는 별도 작업이다.

merge/split/relink는 새 연결 revision과 사유로 기록하며 기존 release·검토는 이전 snapshot을 계속 참조한다. issue revision은 실제 source version·evidence 위치·원/정규화 내용·규칙 버전의 SHA-256이며 canonical 재연결이나 run_id 변경만으로 바뀌지 않는다. 사람의 검토는 issue revision과 link revision에 모두 묶어 과거 승인을 자동 승계하지 않는다.


## 전수/표본 조사에서 확인한 문서 단위

[조사 보고서](legacy-corpus-bootstrap.md)를 기준으로 대표 ID 정책을 확정한다. 최종 corpus 60컬럼에 canonical_id 컬럼은 없고 gmeta_contId/lmeta_serialno 및 행 index가 있다. 공식 ID는 source 연결 자료로 보존한다. 공식 ID 하나가 항상 corpus 행 하나와 일대일인 것은 아니며, 현행 조회 조사 후 canonical 직접 사용 정책을 철회했다.

법원명+사건번호의 업무키 고유성은 유지한다. 다만 저장된 scourt/law_go_kr metadata 양쪽에서 대법원 2008재도11의 2011-01-20 판결과 2010-10-29 결정이 각각 다른 ID로 확인됐다. 서울고등법원 2001나60578도 판결/중간판결 자료가 있다. **사건 업무키와 그 사건의 개별 판결·결정 문서 identity를 구분**해야 원자료를 지울 필요가 없다. 여러 문서가 한 업무키에 속하는 경우를 수작업 키 오류로 분류하지 않는다. canonical은 개별 결정 문서 단위로 확정했다. 사건→복수 문서→source representation 관계를 유지하며 문서 행에 court+docket UNIQUE를 직접 걸지 않는다. legacy 후보를 확정 registry에 반영하는 트랜잭션은 Step 2A다.

Step 2A에서 현재 revision 대조·source unique·이벤트 단위 rollback·snapshot prefix 복원을 실제 PostgreSQL로 검증했다. [구현 및 운영 계약](persistence-and-jobs.md) 참조. 자동 source matcher와 legacy 후보의 일괄 확정은 수행하지 않았다.
