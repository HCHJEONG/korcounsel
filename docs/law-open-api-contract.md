# 국가법령정보 공동활용 API 계약 메모

확인일: 2026-09-09, Step 0. 공식 문서의 계약, 이번 소량 실측, 향후 구현 정책을 구분한다. API adapter 및 자동화 테스트는 아직 구현하지 않았다.

## 공식 계약

목록 endpoint는 `/DRF/lawSearch.do`이고 `OC`, `target=prec`, `type`이 필요하다. page는 1부터, display는 기본 20·최대 100이다. `nb`는 사건번호, `org=400201`은 대법원, `400202`는 하위법원 필터다. 목록의 판례일련번호를 후속 상세 식별자로 사용하며 row의 id와 혼동하지 않는다. [공식 목록 명세](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=precListGuide)

본문 endpoint는 `/DRF/lawService.do`이며 동일 기본 인자에 `ID`를 전달한다. 응답의 판례정보일련번호를 확인한다. JSON/XML/HTML을 안내하지만 국세청 판례 본문은 HTML만 제공한다고 명시한다. 현재 adapter의 미지원 형식은 unsupported로 기록한다. fidelity용 별도 취득 adapter는 설계할 수 있으나 실패 시 무조건 browser로 전환하지 않는다. [공식 본문 명세](https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=precInfoGuide)

문서 예시는 HTTP지만 이번 검증은 `https://www.law.go.kr`로 직접 요청해 성공했다. 앱도 HTTPS를 기본으로 하고 credential이 담긴 요청 URL·redirect·예외 전문을 로그에 남기지 않는다.

## 인증 설정 계약

사용자가 지정한 로컬 `.fordeploy/aws-backup/.env`에 `LAW_GO_KR_OC`가 존재하며 이번 네 건의 조회에 사용했다. `OPENAPI_CO_KR_KEY`도 있지만 이번 source와 검증에서는 사용하지 않았다. 값과 env 내용은 문서·로그·Git에 포함하지 않는다. 환경파일은 수정하지 않았다.

향후 표준 설정 이름은 `LAW_OPEN_API_OC`, 호환 alias는 `LAW_GO_KR_OC`다. 둘 중 하나만 있으면 그것을 사용하고, 둘이 같으면 허용한다. 둘 다 존재하며 값이 다르면 값을 출력하지 않고 설정 오류로 중단한다. 2026-09-10 Step 1에서 이 alias 계약을 앱 config와 합성 테스트로 구현했다. 실제 API adapter는 후속이다. 환경파일 경로는 명시적으로 선택하며 다른 레포의 env를 탐색하지 않는다. DB·인증/세션 설정의 준비 여부는 이번 확인 범위가 아니다.

## 실제 확인 결과

2026-09-09 17:26 KST경 직렬로 총 네 요청을 보냈다. 각 요청 timeout 20초, redirect 비활성, 요청 사이 약 1초 간격이었다. 이는 smoke 설정이며 공식 rate limit을 의미하지 않는다. [비밀값 없는 실측 기록](step0/api-smoke.json)

| 요청 | 관찰 |
| --- | --- |
| 목록 JSON, nb=2017도953, org=400201, display=1, page=1 | HTTP 200. PrecSearch, totalCnt="1", prec는 단일 객체. 판례일련번호 195490 |
| 같은 조건 page=2 | HTTP 200. totalCnt="1"이지만 prec 필드가 없음. 정상 빈 page로 해석 |
| 상세 ID=195490, JSON | HTTP 200. PrecService, 판시사항·참조조문·참조판례·판례내용 존재. 판결요지는 빈 값이며 본문에 markup 존재 |
| 같은 상세 XML | HTTP 200. PrecService 및 대응 field 확인 |

이것은 단일 판례와 빈 page에 대한 접근·응답 구조 확인이다. 여러 결과 배열, 무검색 결과, quota 초과, 잘못된 credential/ID, 재시도, 대량 pagination, 모든 출처와 API 안정성을 검증한 것은 아니다. HTTP 200만으로 작업 성공을 확정하지 않고 root·필수 field·ID를 검사해야 한다.

실측 보고서의 section_lengths는 .NET UTF-16 단위 길이다. Python Unicode code point 기반 EvidenceSpan으로 사용하면 안 된다. 최초 빈 page 검사에서 null을 한 항목으로 감싸는 audit 오류가 있었고 저장된 JSON을 재확인해 item_count=0, parsed_empty로 수정했다.

## raw와 provenance

상세 JSON/XML 및 빈 page는 Git에서 제외되는 `data/raw/step0-20260909T082633Z/`에 원본 바이트로 저장하고 SHA-256을 기록했다. 목록 첫 page는 응답 본문에서 credential 문자열과의 일치가 감지되어 이번 smoke에서 저장하지 않았다. 어느 field가 일치했는지는 확정하지 않았으며 raw 전체 보존 완료로 주장하지 않는다. hash는 받은 원본 바이트에 대한 값이다.

향후 adapter에서는 credential 포함 여부를 판별하고 격리된 비공개 저장 정책을 적용해야 한다. 원본을 마스킹해 놓고 같은 raw라고 부르지 않는다. 안전한 보관이 불가능하면 raw 저장 실패를 명시하고 정상 수집 완료로 처리하지 않는다. 정제된 fixture는 별도 파생 artifact로 이름·hash·변환 내역을 구분한다. URL metadata는 credential 없는 endpoint와 허용된 parameter만 기록한다.

JSON/XML을 decode한 필드 텍스트와 HTML markup 변환을 각각 버전 관리한다. body에서 이유 영역을 구조적으로 찾고 offset 기준 artifact·field를 확정한다. 내용 hash와 ID는 유지하되 XML/JSON transport가 다르면 raw hash가 달라도 정상이다. 상세의 빈 요지는 답변 생성 사유가 아니며 unmatched 후보로 보존한다.

## 오류·pagination·호출 제한: 구현 정책

- prec object는 1건, list는 여러 건, absent/null은 응답 root와 metadata가 유효하면 빈 목록으로 변환한다. 예기치 않은 scalar는 오류다.
- totalCnt의 문자열 숫자를 검증해 정수로 읽는다. 실제 display로 페이지 수를 계산하고 빈 page·동일 page 반복·ID 중복·중간 실패를 처리한다. 변경되는 검색 결과를 snapshot이라고 보장하지 않는다.
- 네트워크 timeout, 일시적 HTTP 실패와 비정상 payload를 구분한다. 제한된 backoff/retry, 부분 결과 및 재개 지점을 구현한다. 인증·잘못된 요청을 무한 retry하지 않는다.
- 고정 초당/일당 quota와 완전한 오류 schema는 확인한 공개 목록·본문·이용안내에서 찾지 못했다. FAQ는 도구 조회가 404, 오류자가진단은 로그인으로 이동했다. 숫자를 추정해 공식 한도로 쓰지 않는다. Step 3에는 보수적인 configurable rate와 실패 fixture를 구현하고 운영 전 계정별 승인 범위·제한을 확인한다.

## 이용 조건과 출처

공식 이용안내는 공동활용 승인 후 사용, 운영 신청 시 활용사례 등록, 트래픽 등으로 인한 제한 가능성을 안내한다. 저작권 정책은 영리 목적을 포함한 활용을 설명하면서 이용조건·제3자 권리 준수와 출처 표시를 요구한다. 이를 모든 외부 출처 데이터의 무조건적 재배포 허가로 확대하지 않는다. [공식 이용안내·저작권 정책](https://open.law.go.kr/LSO/information/guide.do)

이번 키로 소량 조회가 성공한 사실과 해당 계정의 모든 운영/재배포 승인 범위는 별개다. source_system, 원 제공 출처, source_document_id, credential 없는 URL, retrieved_at, raw hash와 변환 버전을 보존한다. 공개 배포 전 실제 제공 데이터·신청 범위에 맞는 표시 및 조건을 확인한다. 합성 회귀 fixture에는 실제 판례 본문을 복제하지 않았다.

## 추가 지시와의 연결

이 메모의 source_document_id는 law_go_kr namespace의 serialno이며 canonical ID가 아니다. scourt contId와의 복합 매칭은 [identity 계약](case-identity.md), source 목록·상세 재조회는 [incremental 계약](incremental-ingestion.md)을 따른다. 실제 네 건의 smoke는 두 source reconciliation이나 전체 inventory 수집 검증이 아니다.

빈 판결요지는 정상 LegalCase에서 허용하고 field 부재/parse 실패를 구분한다. JSON/XML text에 이미지 참조가 없더라도 판결문 전체에 이미지가 없다고 확정하지 않는다. [fidelity 계약](source-fidelity.md)에 따라 reference·탐지 범위·UNKNOWN 상태를 보존한다. API 목록/본문의 원 ID·raw·field provenance는 canonical 연결 후에도 유지한다.
