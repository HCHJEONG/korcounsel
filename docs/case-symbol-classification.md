# 사건기호 구조화 분류 — case-fields-6

## 목적

`case_sort`를 민사·형사 같은 한 단어로 축약하지 않고 사건기호가 공식적으로 나타내는 범위까지 보존한다. `code`에는 원 사건기호를 그대로 유지하고, `case_sort`에는 아래 구조를 저장한다. 원문 HTML·metadata·기존 필드 revision·기존 Parquet는 수정하지 않는다.

- `official_code`: 법원 사건구분표의 숫자 코드
- `category`: 민사·형사·행정·가사·특허·신청·선거특별
- `stage`: 제1심·항소·상고·항고·재항고·준항고. 공식 설명이 말하지 않으면 null
- `panel`: 단독·합의·재정단독. 공식 설명이 말하지 않으면 null
- `procedure`: 본안·소액·신청·항고·재항고·준항고·특수소송
- `description`: 법원 사건구분안내의 설명 원문
- `label`: 위 속성을 중복 없이 조합한 화면 표시
- `basis`: 근거 기관·URL·확인한 예규 시행일
- `temporal_status`: 해당 선고일의 적용 범위를 확인했는지 여부

예를 들어 `가단`은 `민사 · 제1심 · 단독`, `고합`은 `형사 · 제1심 · 합의`, `누`는 `행정 · 항소`로 표시한다. `구합`의 합의부 여부처럼 공식 설명에 명시되지 않은 속성은 글자 모양만 보고 채우지 않는다.

## 근거와 시간 적용

대법원 사건구분안내의 코드·사건유형·내용과 국가법령정보센터의 「사건별 부호문자의 부여에 관한 예규(재일 2003-1)」를 근거로 사용한다. 확인한 예규는 2022-07-29 시행본이다.

- 선고일이 2022-07-29 이후이고 분류표에 등록한 기호이면 `PRESENT`와 `VERIFIED_EFFECTIVE_RANGE`로 기록한다.
- 그 이전 판례는 현행 설명과 legacy corpus의 기존 상위 분류가 일치해도 당시 시행본을 확인하기 전에는 `REVIEW`와 `HISTORICAL_VERSION_NOT_VERIFIED`로 기록한다.
- 미등록 기호는 추측하지 않고 `REVIEW`로 남긴다. 이후 공식 연혁 또는 충분한 출처 metadata를 확인해 새 규칙 revision으로 추가한다.

현재 근거:

- [대법원 사건구분안내](https://www.scourt.go.kr/portal/information/event/guide/index14.html)
- [국가법령정보센터 사건별 부호문자의 부여에 관한 예규](https://www.law.go.kr/LSW/admRulInfoP.do?admRulSeq=2200000102523&chrClsCd=010201)
- 분야별 법원 안내: [행정](https://www.scourt.go.kr/portal/information/event/guide/index8.html), [특허](https://www.scourt.go.kr/portal/information/event/guide/index9.html), [가사](https://www.scourt.go.kr/portal/information/event/guide/index7.html), [신청](https://www.scourt.go.kr/portal/information/event/guide/index2.html), [선거·특별](https://www.scourt.go.kr/portal/information/event/guide/index10.html)

## 확인 범위

신규 고정 snapshot 433건의 27개 사건기호를 모두 등록했다. 그중 첫 기간 증보에서 기존 규칙이 검토 대상으로 남긴 184건의 22개 기호도 모두 공식 설명에 연결된다. 433건에 새 규칙을 읽기 전용 적용한 결과 미등록 기호는 0건이다.

레거시 89,130건의 기존 `case_sort`는 민사 39,257, 행정 22,241, 형사 20,662, 특허 3,331 등 14개 상위 범주이며 원형 그대로 보존한다. 레거시 전체를 현행 표로 소급 확정하지 않는다. 후속 작업은 사건기호·선고연도·법원·기존 `case_sort`·lawgo 사건종류의 교차 집계에서 충돌과 역사적 기호를 먼저 분리하고, 확보된 시행본별 유효기간을 추가하는 것이다.
