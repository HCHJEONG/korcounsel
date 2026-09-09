# 레거시 판례 identity·증분 수집·asset 조사

2026-09-09 추가 지시서 33항 A–G에 대응한다. `I:\VSCodeBases\web2df`의 `_01`~`_07` 관련 코드를 읽고 saved 아래 텍스트/HTML을 조사했다. 원본 저장소 수정·pickle 역직렬화·crawler 실행·외부 브라우저 수집은 하지 않았다. 코드 관찰, 저장 자료 관찰, 사용자가 제공한 역사적 배경, 새 설계 결정을 구분한다.

## A. scourt identity

`_01_crawl_glaw_and_lawgo_metadata.py:95–147`은 브라우저 세션 준비 후 내부 목록 HTTP endpoint의 searchResultList를 모은다. count endpoint와 20건 pagination을 사용하며 `d1=0~<date>` 등 검색 범위가 있다. 따라서 주석의 “전체”만으로 모든 시기·분류의 완전한 inventory였다고 확정할 수 없다. 당시 HTTP 경로는 현재 공식 API 계약이나 동작 보장이 아니다.

`_02:27–34`는 기존 corpus의 gmeta_contId 집합에 현재 metadata의 contId가 없는 항목을 새 수집 목록에 넣는다. `_02:89` 이후 contId로 GLAW 판례 URL을 만들고 제목 bmunStart, 본문 .page, areaNetwork의 outerHTML을 연결해 `<contId>.txt`로 저장한다. `_03:230–247`은 파일명과 metadata contId를 비교해 gmeta_contId·법원·날짜·사건번호 등으로 연결한다. contId는 scourt 내부 문서 식별자이지 canonical ID가 아니다.

## B. law.go.kr identity

`_01:154–188`은 공식 목록의 판례일련번호와 사건 metadata를 모은다. 이 분기는 `(total//20)+1`과 singleton 미대응 위험이 있다. `_05_create_df_lmeta.py:9–17`은 scourt 기반 corpus와 lawgo metadata를 읽고 `_05:77` 이후 일치한 판례일련번호를 lmeta_serialno에 넣는다. `_06`은 이 serialno로 법제처 HTML 상세를 조회한다. scourt contId와 직접 ID join하는 구조가 아니다.

## C. Composite reconciliation의 의미와 타협

`_05:18–96`, `_06:305–355`에 다음 로직이 중복되어 있다.

1. lawgo 사건번호를 `[,\-\s#]+`로 나누고 첫 token을 고른다. 병합·쉼표·특수 표기를 넘기려는 후보 단서다. 공백이 사건번호 내부에 있으면 과도하게 잘릴 수 있다.
2. 법원명을 첫 “법원”까지만 남긴다. 표현 차이에 대응하지만 지원·지부 차이를 잃는다.
3. 날짜의 점을 지우고 YYYY/MM/DD 위치를 잘라 월·일의 앞 0을 없앤 뒤 `YYYY. M. D.`로 만든다. 고정 폭·비어 있지 않다는 가정이 있어 날짜 형식/결측에 취약하다.
4. 세 값이 case_full_no에 모두 포함되는지 검사한다. 사건번호 바로 뒤 문자가 0–9가 아닌지 검사해 `...1`을 `...10`에 연결하는 prefix 오탐을 막는다.
5. 첫 성공 후보에서 사실상 확정한다. 복수 후보·점수·충돌 기록은 없고 미성공은 empty로 표시한다.

이것은 첫 사건번호 단독 equality가 아니라 세 metadata 신호를 조합한 매칭이다. 뒤 숫자 검사는 중요한 보존 대상이다. 다만 앞쪽 토큰 경계는 확인하지 않고, 사건번호가 문자열 맨 끝이면 뒤 문자열이 없어 거절될 수 있다. 법원 지원 손실, 첫 후보 의존, disposition 미비교 때문에 새 resolver에서 전체 번호 집합·법원 계층·날짜·결정 종류·유일 후보를 검증해야 한다. missing/0/empty/NaN의 기존 분기를 명시적 상태로 바꾼다.

`_04:515–537`은 old/new corpus concat 뒤 일부 결측을 0으로 바꾸고 gmeta의 사건번호·법원을 결과에 반영한다. 새 canonical 결합에서는 출처별 필드 provenance를 보존하며 이렇게 조용히 덮어쓰지 않는다.

## D. Incremental update

`_02:20–40`의 existing contId set와 current metadata 비교는 신규 등록 식별의 핵심 개념이다. 선고일 > 마지막 실행일 비교가 아니다. 원래 구현은 현재 목록의 중복 제거, 같은 ID 본문 변경·사라짐, snapshot 완전성, ID 타입 일관성을 명시적으로 처리하지 않는다. 신규 수집 실패는 error_contId_list로 남기지만 완료 ledger와 snapshot 간 원자적 상태는 없다.

새 [증분 계약](incremental-ingestion.md)은 snapshot 비교와 상세 fetch ledger를 분리한다. NEW/UNCHANGED/CHANGED/MISSING, source availability, 재시도·중단 재개, 별도 refresh를 갖춘다. inventory가 부분이면 disappearance를 단정하지 않는다. 과거 raw는 유지한다.

## E. 실제 저장 자료의 구조 다양성

[표본·해시·집계](step0/legacy-fidelity-inventory.json)는 saved 아래 txt/html/pdf 검색 결과 8,482개를 읽은 기록이다. 이번 범위에 PDF 파일은 없었다. 같은 판례의 원본/조문 보강본 등 중복 representation이 있으므로 아래 수는 고유 판례 수나 corpus 전체 통계가 아니다. 표식 존재 조사이며 field 본문 완전성 검증은 아니다.

| 관찰 | 파일 수 | 확인 표본 / 한계 |
| --- | ---: | --- |
| 판시사항·판결/결정요지 표식 모두 | 7,584 | glaw_updated_panre_txt/3325503.txt, 전문·이유 표식도 존재 |
| 판시사항 표식만 | 439 | glaw_updated_panre_txt/3325151.txt, 이유 존재·img 없음 |
| 요지 표식만 | 21 | lawgo_jomunupdated_panre_txt/64176-2061329-194079.txt, 이유 존재·img 없음 |
| 둘 다 없음 | 438 | glaw_updated_panre_txt/2029039.txt, 전문·주문·이유와 긴 텍스트 존재 |
| img 태그 존재 | 4,222 | 위 분류와 중복. 법적 시각자료 수가 아니며 UI 이미지도 포함 |

표본 파일은 모두 saved/20240723/ 아래이며 JSON에 정확한 상대경로와 SHA-256을 기록했다. 3325503의 image 경로는 alert_img_01.png여서 단순 img 존재로 법적 evidence를 판정하면 오탐이다. 2029039에는 34개 img와 `/wsjo/cm/imgDownload.do` 참조가 있다. 전문·이유가 존재하고 editorial 표식이 없는 representation의 실제 표본으로 확인했다. 이 표본에는 해양사고관련자 heading도 있어 데이터 범주·기관 판정을 법원 판결이라고 일괄 가정하지 않는다.

판시사항·요지가 없는 저장 자료는 실제 존재한다. 반면 PDF_TEXT·PDF_SCAN·page-image-only 실물 판례는 이번 검색 범위에서 확인하지 못했다. 구조적 스캔 판정은 향후 실물로 검증하며 합성 fixture로만 계약을 먼저 기록한다. 표식 탐지는 HTML parser의 section 판정이나 PDF text layer 검사를 대신하지 않는다.

## F. 이미지 보존과 browser 필요성

사용자는 law.go.kr 경유 데이터에서 판결 내 이미지가 손실되는 것이 scourt를 병행한 이유였다고 설명했다. 이번 코드는 그 배경과 부합하는 scourt HTML 보존·URL 보정 흐름을 보여준다. 다만 동일 판례의 양 source raw를 대조하지 않았으므로 특정 이미지가 lawgo에서 누락됐다는 직접 비교 검증은 아직 없다.

`_06:293–294`는 `src="/`를 scourt absolute URL로 문자열 치환한다. 이는 reference 보정이며 binary 다운로드·MIME 검사·hash 저장·OCR이 아니다. single quote·상대 ../·protocol-relative src를 충분히 처리하지 못하고 원래 표기를 덮어쓴다. 새 assets reference는 original_src와 안전한 resolved URL을 모두 보존한다.

`_02`는 렌더링된 DOM과 popup을 다루고 `_06:92–248`은 법제처 frame 0, .link, 조문 popup과 table을 처리한다. 즉 Selenium에는 DOM/세션/팝업/프레임이라는 실제 역할이 있었다. 이 파일에서 browser 사용의 상당 부분은 이미지 취득이 아니라 조문 링크 보강이다. 현재도 browser가 반드시 필요한지, 다른 방식이 더 안정적인지는 별도 adapter 조사 대상이다.

## G. Mixed responsibilities와 이동

| 레거시 책임 | 새 위치 | 유지할 invariant / 바꿀 점 |
| --- | --- | --- |
| _01 목록·세션·pagination | sources/scourt, sources/law_go_kr + ingestion | namespace별 inventory, 범위·완전성 보존 |
| _02 신규 contId·DOM 취득·실패 목록 | ingestion + sources/scourt | 집합 비교를 유지하고 snapshot/ledger 분리 |
| _03 metadata/section·원문 | normalize + parse + documents | raw와 source metadata를 불변 보존 |
| _05 및 _06 재매칭 | identity | 세 신호·prefix 보호를 계승, 첫 후보 확정 폐기 |
| _06 image src 보정 | assets/detector·manifest | 원 참조·순서·문맥 유지; 다운로드와 구분 |
| _06 cross-source 조문 anchor matching | enrichment/statute_linker | 같은 표시 문구를 앞에서부터 대응시키는 heuristic; repeated anchor/버전 차이는 모호함으로 기록 |
| _06 popup/table 추출 | source adapter + enrichment | jtable 삽입은 derived enrichment. 원문 덮어쓰기 금지 |
| _07:26–37 파일명 index로 HTML 교체 | storage + versioned projection | index 재배열 오연결 위험. source IDs/hash 검증과 새 revision으로 대체 |

`_06`의 success marker는 asset 전체 취득 성공을 의미하지 않는다. `_07`이 보강 HTML을 같은 field에 넣는 방식 대신 원본·파생본을 분리한다. source 간 일치한 조문 문자열이 같은 법령 시점·같은 인용 occurrence를 보장한다고 가정하지 않는다.

## 조사 결론과 검증 범위

기존 migration 문서의 “Selenium/웹 scraping 제거” 결론은 수정한다. 구식 실행 결합·하드코딩을 그대로 가져오지 않되 필요한 원문 확보 수단과 그 이유는 계승한다. 추가 source 중 scourt identity/inventory와 Stage A/B는 초기 확장 milestone에 포함한다. OCR·LLM·LawnB 수집은 초기 범위에 넣지 않는다.

추가 지시의 최소 15종과 증분/충돌 경계를 [합성 fixture](../tests/fixtures/legacy/identity-fidelity-cases.json)에 기록했다. 실제 공개 판례의 원문 복제 없이 metadata·표식 관찰 근거를 manifest로 남겼다. 확정 1:1 매핑·양 source 이미지 누락 비교·PDF 실물 검증은 아직 미완료이며 해당 live milestone의 조건으로 유지한다.
