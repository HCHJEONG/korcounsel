# 기존 날짜 추출 로직 조사 — 2026-09-10

**전수 검증 후속 — 2026-09-10:** 89,130행 날짜 교정 후보와 이미지 inventory를 생성했다. 선고일 89,130행, 변론종결일 13,518행 READY이며 복수 날짜 45행은 적용 보류다. 교정 변경분 Parquet의 Python·Node 전수 왕복을 검증했고 현재 이미지 38 URL의 bytes를 취득했다. 이후 전체 60컬럼 corrected Parquet, corrected bundle v2, 로컬 개발 PostgreSQL 보존 import, Parquet 직접 검색 UI를 완료했다. 이미지 전수 취득과 canonical 등록은 미완료다. [결과와 한계](legacy-repair-and-images-progress.md).

## 확인 결론

기존 추출 로직을 재사용할 수 있다. decision_date는 날짜 문자열을 찾은 뒤 변환 함수를 잘못 호출한 버그가 확인됐다. closing_argument는 date와 미취득 표식 문자열을 함께 반환하도록 작성된 함수이며, 혼합 타입이라는 사실만으로 추출 실패라고 판단하면 안 된다. 이번에는 코드를 읽고 기존 Parquet 표본 146행에서 재현했으며 원본 pickle·레거시 코드·운영 필드를 수정하지 않았다.

## 코드 위치와 저장 흐름

기준 경로는 I:/VSCodeBases/web2df다.

- _04_concat_old_and_new_df_corpus_then_create_fullest.py:106의 date(case_full_no)는 사건번호 앞 제목 부분에서 날짜를 찾는다. 122행에서 parser.parser(temp_date_string)를 호출한다.
- 같은 파일 545행은 기존+신규를 concat한 DataFrame 전체의 decision_date를 다시 계산한다. 신규 행만 계산하는 코드가 아니므로 과거 정상값이 있더라도 이 단계에서 덮어쓸 수 있다. 실제 과거 실행 시점·변경 commit은 이번에 조사하지 않았다.
- 447~474행의 closing_argument는 case_txt_in_file의 변론종결 구역에서 날짜를 추출한다. 564행에서 적용한다.
- 568행의 full_gmeta 저장 → 580행의 fullest_gmeta 저장 → _05의 lawgo metadata 보강 → _07의 HTML 보강 및 최종 fullest_gmeta_lmeta 저장으로 이어진다.
- legacy/_4_case_df2case_df_full.py에도 같은 parser.parser 호출이 있다.
- util_df_standard_case.py:98~111에는 parser.parse(...).date()를 쓰는 다른 날짜 함수가 있다. 날짜 후보를 모두 이어 붙이는 방식이므로 복수 날짜 사례까지 검증하지 않고 그대로 대체하지 않는다.
- df2preproc의 Python 파일에서는 두 필드의 대입 코드를 찾지 못했다.

## decision_date: 오타와 별도 경계 문제

parser.parse(text)는 날짜를 해석하지만 parser.parser(text)는 parser 객체를 생성한다. 확인한 생성자는 info 인자에 전달된 문자열을 그대로 저장하므로 즉시 예외가 나지 않는다. 따라서 기존 try/except가 오류를 발견하지 못한다. 재현 객체의 info에는 "2011. 3. 10."이 들어 있었다. 이는 이번 재현 객체의 관찰이며, 원본 pickle 객체의 내부 속성을 전수 조사한 것은 아니다.

기존 date 함수에서 parser.parser만 parser.parse로 바꾼 메모리상 실험 결과:

| 146행 표본 | 기존 함수 | 호출 수정 후 |
| --- | --- | --- |
| 145행 | parser 객체 | 제목에서 추출한 datetime |
| position 19,539 | 2072-01-01 datetime | 여전히 2072-01-01 |

**전수 프로파일의 datetime 1개는 정상 선고일이 아니라 오류용 sentinel 2072-01-01이다.** 기존 “datetime 1개” 설명은 타입만 확인한 결과였으며 날짜가 유효하다는 의미로 사용하면 안 된다.

예외 제목은 “제26사단보통군사법원 2002. 10. 24. 선고 2002고26 판결”이다. 기존 사건번호 regex가 먼저 “26사단보통군사법원 2002”를 사건번호로 잡는다. 그 앞에서 날짜를 찾으므로 실패한다. 제목에는 날짜 2002. 10. 24.가 남아 있다.

또한 기존 날짜 regex는 점 뒤 공백을 요구한다. 합성 제목의 2020.1.2.는 호출만 고쳐도 실패한다. 따라서 원래의 “제목에서 해당 재판의 날짜를 추출”하는 접근은 계승하되 사건번호 경계·공백·sentinel·반환 타입을 보완해야 한다. 전체 89,130행의 수정 성공률과 날짜 정확성은 아직 검증하지 않았다.

## closing_argument: 기존 결과의 의미와 재사용 조건

기존 함수는 “【변론종…” 구역의 날짜를 찾는다.

- 하나이면 parser.parse(...).date()를 반환한다.
- 여러 개이면 가장 늦은 날짜를 반환한다.
- 찾지 못하면 "no_info", 짧은 입력이면 "Error"를 반환한다.

실제 표본은 date 30개, 문자열 "no_info" 116개이며 **재계산 결과가 기존 저장값과 146행 모두 일치**했다. 이는 로직 재현성 확인이며 no_info 116행에 실제 변론종결일이 없다는 원문 검수 결과는 아니다. 전체 문자열 75,584개를 모두 no_info로 확정한 것도 아니다.

합성 경계 확인: None은 len(None) 때문에 TypeError, 잘못된 날짜는 ParserError, 복수 날짜는 가장 늦은 날짜를 반환했다. 재사용 시 입력 검사·실패 상태를 보완하고 복수 날짜의 원래 후보와 선택 근거를 함께 남긴다. 이번 조사만으로 기존의 최댓값 선택 정책을 변경하지 않는다.

## 검증 방법과 후속

레거시 모듈을 import하지 않고, 읽어 확인한 regExSearch/date/closing_argument 함수 정의만 AST로 분리해 실행했다. _03의 사건번호 regex 문자열은 AST literal로 읽었다. 레거시의 파일 읽기·concat·저장·수집 등 최상위 실행 코드는 실행하지 않았다.

실제 입력은 data/parquet-validation-20260910-v2/sample.parquet의 기존 146행이다. 합성 경계와 실제 관찰은 [기계 판독 결과](legacy-date-logic-audit.json)에 구분했다. 레거시 파일 SHA-256도 포함한다. 앱 코드 변경이 없는 조사이며 앱 전체 회귀를 다시 실행하지 않았다.

다음은 기존 함수를 보완한 분석 전용 날짜 복구 로직으로 전수 대조하는 단계다. decision_date는 제목 근거·metadata 대조·충돌/실패를 기록하고, closing_argument는 기존 date/no_info/Error와 재계산 결과를 구분한다. 원본 행은 유지하며 검증된 수정 결과를 별도 버전으로 저장한다. 전수 Parquet 운영 변환보다 먼저 수행한다.
