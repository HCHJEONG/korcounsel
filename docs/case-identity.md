# 판례 식별과 기존 corpus 계승 계약

2026-09-10 사용자 추가 결정 반영. Step 2 모델은 구현 초안이며 canonical ID 발급 정책은 기존 corpus의 실제 식별자 분석에 앞서 확정하지 않는다.

## 기존 자료가 출발점

기존 약 9만 건을 신규 수집으로 대체하지 않는다. 기존 판례·공식 ID·출처 연결·원문 표현·행 참조를 보존해 초기 corpus로 가져오고 이후 신규/변경분을 확장한다. 원래 사용한 대표 ID가 확인되면 그 ID를 우선 계승한다. 새로운 UUID로 일괄 재번호를 부여하는 정책은 채택하지 않았다.

canonical_id는 모델에서 opaque 문자열이다. 기존 정부 ID를 대표값으로 사용하거나 그 값을 namespace와 함께 유지할 수 있다. canonical의 논리적 역할과 source별 ID의 역할을 구분한다는 원칙은 **반드시 다른 난수 값을 발급해야 한다는 뜻이 아니다**. scourt와 law_go_kr에서 숫자가 같다고 같은 source ID로 취급하지 않는다.

## 네 식별 축

| 대상 | 계약 |
| --- | --- |
| CourtCaseKey | **법원명 + 사건번호**. 사용자가 확인한 고유 업무 식별키. 정부 ID 없는 LawnB 보유 판례도 등록·대조 가능 |
| source 식별자 | scourt contId, law_go_kr 판례일련번호, 존재하는 LawnB 자체 ID를 각각 원래 namespace에서 보존 |
| canonical_id | registry에서 대표 판례를 가리키는 안정적인 값. 기존 대표/공식 ID 활용을 우선 조사하며 발급 정책은 분석 후 결정 |
| 내용/연결 revision | source bytes hash, issue content revision, identity link revision을 각각 보존. 등록키·내용 변경·연결 정정을 혼동하지 않음 |

정부 ID가 없다는 이유로 레거시 행을 버리거나 가짜 정부 ID를 만들지 않는다. 기존 행은 snapshot 파일 hash + 원래 index/position으로도 추적한다. 이는 원자료의 행 locator이며 법원명+사건번호 업무키나 법적 판례 identity 자체를 대신하지 않는다.

## 법원명 + 사건번호 업무키

이 조합을 canonical과 함께 사용할 고유키로 유지한다. 드물게 발견된 과거 수작업 오류는 명시적 충돌/예외 기록으로 관리하고, 그러한 예외 때문에 조합의 고유성을 일반적으로 포기하지 않는다. 이 원칙은 2026-09-10 사용자의 도메인 지식에 따른 프로젝트 결정이다.

- 법원 지원·지부를 보존한다. alias 정규화 규칙과 원문을 함께 기록한다.
- 전체 병합 사건번호를 보존하고 각 사건번호를 해당 법원과 결합한 key alias로 연결한다. 첫 번호만 남기지 않는다.
- 선고일·판결/결정·내용 hash는 키에 무조건 추가할 구성요소가 아니라 출처 대조·오류 발견·버전 구별에 사용하는 정보다.
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

[조사 보고서](legacy-corpus-bootstrap.md)를 기준으로 대표 ID 정책을 확정한다. 최종 corpus 60컬럼에 canonical_id 컬럼은 없고 gmeta_contId/lmeta_serialno 및 행 index가 있다. 공식 ID를 대표로 활용할 근거는 있으나 공식 ID 하나가 항상 corpus 행 하나와 일대일인 것은 아니다.

법원명+사건번호의 업무키 고유성은 유지한다. 다만 저장된 scourt/law_go_kr metadata 양쪽에서 대법원 2008재도11의 2011-01-20 판결과 2010-10-29 결정이 각각 다른 ID로 확인됐다. 서울고등법원 2001나60578도 판결/중간판결 자료가 있다. **사건 업무키와 그 사건의 개별 판결·결정 문서 identity를 구분**해야 원자료를 지울 필요가 없다. 여러 문서가 한 업무키에 속하는 경우를 수작업 키 오류로 분류하지 않는다. canonical을 어느 단위의 대표값으로 사용할지, 사건→결정 문서→source representation 연결을 import 설계에서 확정한다. 이 결정 전에는 모든 문서 행에 court+docket UNIQUE를 직접 걸지 않는다.
