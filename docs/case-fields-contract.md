# 60필드 대응 계약과 구현 — 2026-09-15

규칙 `case-fields-6`.  실제 corrected Parquet 89,130행의 원래 60컬럼을 대조했다. `__legacy_position`·`__legacy_index`는 제외한다. 기존 저장값은 변환·덮어쓰기 없이 조회하며 새 값과 처리 상태/근거를 분리한다.

**2026-09-15 제한 품질 교정 후:** `current-lawgo-3`의 법원명 공백 비교와 서비스
오류 응답 분류를 적용한 reader 5개에 새 v6 필드를 발행했다. 필드 추출 규칙은
변경하지 않았다. 현재 고정 433개에서 ERROR/NOT_PROCESSED는 0이며 폐기
역참조 433개·lawgo 충돌 35개는 REVIEW다. 기존 v6 snapshot과 reader별
필드는 불변이고 새 aggregate는 로컬 export로 추가했다.
[전후 값·근거·시각 차이와 snapshot](quality-baseline-20260915.md).

## 계승과 수정

`web2df/_03_create_new_df.py`의 제목·명시 구획·milestone 규칙과 `_04_concat_old_and_new_df_corpus_then_create_fullest.py`의 사건번호·법원·날짜·당사자·서명 규칙을 읽고 재작성했다. filename 강제 합성, 본문 손실성 치환, 특정 사건 삭제, 잘못된 날짜 fallback, 본문 부재에 따른 미폐기 단정은 계승하지 않는다. legacy 전체 재추출은 실행하지 않았다.

## 필드별 대응

| 필드 | 기존 Parquet 저장 타입 | 신규 원천·규칙·검증/결측 |
|---|---|---|
| `case_txt_scraped_with_tags` | large_string | 보존 HTML 그대로; HTML SHA-256 대조 |
| `case_txt_in_file` | large_string | 가시 텍스트; legacy lnfd 대신 실제 줄바꿈, script/style 제외. 원문은 그대로 보존 |
| `case_full_no` | large_string | HTML h2의 전체 재판 제목; 없으면 reader 제공 제목 |
| `case_official_name` | large_string | scourt csNmLstCtt 공식 사건명 |
| `case_unofficial_name` | tagged cell (원 타입·encoding·값) | scourt jdcpctCsAlsNm 별칭 |
| `citedPlace` | tagged cell (원 타입·encoding·값) | scourt jdcpctPublcCtt 게재정보 |
| `previous_case` | tagged cell (원 타입·encoding·값) | 【】 본문 구획 원심판결, 원심결정, 원판결, 원결정, 불복대상결정; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `decision_items` | tagged cell (원 타입·encoding·값) | 【】 본문 구획 판시사항, 결정사항; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `decision_gists` | tagged cell (원 타입·encoding·값) | 【】 본문 구획 판결요지, 결정요지; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `main_decision` | tagged cell (원 타입·encoding·값) | 【】 본문 구획 주문; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `reasoning` | tagged cell (원 타입·encoding·값) | 【】 본문 구획 이유, 판결이유, 결정이유, 재정이유; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `case_comment` | large_string | 대괄호 tail 구획 평석; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `related_articles` | large_string | 대괄호 tail 구획 관련문헌; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `applicable_acts` | tagged cell (원 타입·encoding·값) | 【】 본문 구획 참조조문; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `applicable_precedents` | tagged cell (원 타입·encoding·값) | 【】 본문 구획 참조판례; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `applicable_acts_tail` | large_string | 대괄호 tail 구획 참조조문; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `applicable_precedents_tail` | large_string | 대괄호 tail 구획 참조판례; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `applicable_acts_in_body` | large_string | 대괄호 tail 구획 본문참조조문; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `applicable_precedents_in_body` | large_string | 대괄호 tail 구획 본문참조판례; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `following_cases` | large_string | 대괄호 tail 구획 따름판례; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `original_case` | large_string | 대괄호 tail 구획 원심판결; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `site` | large_string | scourt 출처 namespace |
| `hangul_keyword` | tagged cell (원 타입·encoding·값) | legacy 파일/외부 편집 workflow 전용; 현재에는 NOT_APPLICABLE. 과거 경로·시각·주석 생성 금지 |
| `important` | tagged cell (원 타입·encoding·값) | 제공 제목의 별표가 있는 경우만 true; 부재는 미제공 |
| `supreme` | tagged cell (원 타입·encoding·값) | 공식 법원명 대법원 여부 |
| `jeonhap` | tagged cell (원 타입·encoding·값) | 제공 제목의 전원합의체 표식 |
| `party_info` | tagged cell (원 타입·encoding·값) | 명시 당사자 구획 원표기 |
| `multipartycase` | large_string | 대괄호 tail 구획 다수당사자판례; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `uppercase` | large_string | 대괄호 tail 구획 상급심판결; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `file_created_time` | large_string | legacy 파일/외부 편집 workflow 전용; 현재에는 NOT_APPLICABLE. 과거 경로·시각·주석 생성 금지 |
| `etcdoc` | large_string | 대괄호 tail 구획 기타문서; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `file_process_time` | tagged cell (원 타입·encoding·값) | 이번 필드 job 생성 시각(ISO); 과거 파일 처리시각으로 소급하지 않음 |
| `folder_file_name` | large_string | legacy 파일/외부 편집 workflow 전용; 현재에는 NOT_APPLICABLE. 과거 경로·시각·주석 생성 금지 |
| `case_no` | large_string | 첫 사건번호; 병합번호 전체는 gmeta_saNo에서 유지 |
| `code` | large_string | 대표 사건번호의 기호 |
| `case_sort` | large_string | 사건기호의 공식 코드·분야·심급·재판부·절차·설명·시간 적용 상태를 구조화; 과거 시행본 미확인·미등록 기호는 REVIEW |
| `court_name` | large_string | scourt cortNm; 법원 지원·지부 표기 유지 |
| `decision_date` | tagged cell (원 타입·encoding·값) | scourt prnjdgYmd 달력 검증, ISO 날짜 문자열; 임의 2072년 fallback 금지 |
| `judge` | tagged cell (원 타입·encoding·값) | 명시 서명 줄의 직역→이름·역할 원표기 |
| `repealed_cases` | large_string | 전체 corpus 폐기 역참조 감사가 필요하므로 REVIEW; 미폐기 추정 금지 |
| `party_info_dict` | tagged cell (원 타입·encoding·값) | 명시 역할별 구획값; 대리인 문구를 손실 없이 유지 |
| `closing_argument` | tagged cell (원 타입·encoding·값) | 【】 본문 구획 변론종결; 다음 구획까지; 미제공/반복 구획 REVIEW 구분 |
| `gmeta_contId` | large_string | 보존 scourt metadata jisCntntsSrno; 누락은 NOT_PROVIDED, 날짜 달력 검증 |
| `gmeta_gjaeInfo` | large_string | 보존 scourt metadata jdcpctPublcCtt; 누락은 NOT_PROVIDED, 날짜 달력 검증 |
| `gmeta_sngoDay` | large_string | 보존 scourt metadata prnjdgYmd; 누락은 NOT_PROVIDED, 날짜 달력 검증 |
| `gmeta_bubNm` | large_string | 보존 scourt metadata cortNm; 누락은 NOT_PROVIDED, 날짜 달력 검증 |
| `gmeta_panTypeNm` | large_string | 보존 scourt metadata adjdTypNm; 누락은 NOT_PROVIDED, 날짜 달력 검증 |
| `gmeta_saNm` | large_string | 보존 scourt metadata csNmLstCtt; 누락은 NOT_PROVIDED, 날짜 달력 검증 |
| `gmeta_saNo` | large_string | 보존 scourt metadata csNoLstCtt; 누락은 NOT_PROVIDED, 날짜 달력 검증 |
| `for_lawschool` | large_string | legacy 파일/외부 편집 workflow 전용; 현재에는 NOT_APPLICABLE. 과거 경로·시각·주석 생성 금지 |
| `lmeta_serialno` | large_string | 동일성 EXACT인 lawgo 후보의 판례일련번호; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_saNm` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 사건명; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_saNo` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 사건번호; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_sngoDay` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 선고일자; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_bubNm` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 법원명; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_bubCode` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 법원종류코드; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_saType` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 사건종류명; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_saCode` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 사건종류코드; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_deType` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 판결유형; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |
| `lmeta_sentence` | tagged cell (원 타입·encoding·값) | 동일성 EXACT인 lawgo 후보의 선고; 충돌 REVIEW, 단계 미실행 NOT_PROCESSED, 연결 없음 NOT_PROVIDED |

## 표현·상태 계약

신규 Parquet는 60개 같은 이름의 컬럼을 모두 `original_type/encoding/text/integer` tagged cell로 직렬화한다. legacy의 STRING/INTEGER/NULL/JSON codec을 재사용하며 physical schema가 기존의 native 문자열/혼합 cell과 동일하다고 주장하지 않는다. 본문 텍스트의 줄바꿈·날짜와 이번 처리시각의 ISO 표현을 명시적으로 버전 관리한다. 매 판례 Parquet 왕복 대조와 SHA-256을 확인한다. 23행 snapshot의 행→source/reader/fields revision 연결은 별도 manifest에 있다.

상태는 PRESENT, NOT_PROVIDED, NOT_APPLICABLE, NOT_PROCESSED, ERROR, REVIEW, LEGACY_STORED다. REVIEW가 있으면 전체 검증 완료가 아니며 ERROR/NOT_PROCESSED는 INCOMPLETE다. 기존 no_info·0·빈 문자열도 값 원형으로 표시하며 과거 의미 검증 성공으로 바꾸지 않는다.

근거의 ranges는 보존 HTML의 byte offset이 아니라 `visible-text-v1`의 Python 문자열 문자 범위다. metadata key와 artifact 참조를 별도로 기록한다. 원본 HTML·source artifact·기존 reader manifest는 수정하지 않는다.

## 영속 처리와 UI

`BUILD_CASE_FIELDS`는 lawgo와 그 후속 image refresh의 terminal 상태를 DB에서 확인한 뒤 실행한다. 원본 수집 job checkpoint에 fields_job_id를 연결한다. 같은 reader+규칙 결과는 재사용하며 artifact 발행 직후 재시도에도 revision이 늘지 않는다. 과거 reader에는 관리자 필드 생성 버튼을 제공한다. 필드 job 성공과 의미 검증 통과를 구분한다.

일반 검색→보강 본문/60필드 전환, 직접 URL의 view=fields·새로고침, 빈값/복합값/긴값, 근거·규칙·revision 표시를 제공한다. 모든 조회는 서버 인증, 생성은 관리자와 same-origin 검증을 거친다. 원문 수집 단계 종료를 전체 완료로 표시하지 않는다.

## 한계

폐기 역참조는 전체 corpus 감사가 필요한 REVIEW이며 임의 미폐기 값을 생성하지 않는다. 날짜/텍스트의 신규 표현과 legacy 값은 위 계약에 따라 소비자가 정규화해야 한다. 법령 버전·조문 취득 실패는 reader의 위치별 상태를 유지한다. 신규 23건 산출물 생성과 전체 의미 검증 완료를 구분한다. 정기 실행·AWS 이관·commit/push는 실행하지 않는다.

## 실제 비교·발행 결과

- 기존 표본: 2010도16942(position 0), 2017허1854(position 26270), 2017도953(position 29641). 판시사항/요지/주문/이유/참조조문/참조판례 18항목 중 값 있는 12항목은 공백·lnfd 정규화 후 기존 저장값과 일치했다. 나머지 6항목은 기존 결측 sentinel과 새 NOT_PROVIDED 차이다.
- 위 비교에서 `[1]` 번호와 `【청구항 1】`을 본문 구획으로 잘못 나누는 초기 오류를 확인했다. `case-fields-3`은 인정된 문서 구획·당사자 역할·tail 표제만 경계로 사용하며 두 유형의 회귀 테스트를 추가했다. v1/v2 artifact는 그대로 남고 당시 조회 기본값은 v3였다.
- 최종 23건의 고정 입력·파생 연결·검증은 `data/case-fields-20260915/snapshot-v3.json`, 60필드 Parquet는 `current-23-v3.parquet`에 있다. DB artifact에도 같은 bytes와 manifest가 등록됐다. 현재 23건의 미처리/추출 실패는 0, 폐기 역참조 검증 보류는 23, lawgo 충돌은 3건이다.
- 기존 89,130행 Parquet와 raw HTML/source artifact/기존 reader는 변경하지 않았다. 초기 2건 보존 replay의 새 reader를 포함해 최종 23건 HTML hash가 최초 고정 입력과 일치한다.

## 최종 검증

PostgreSQL 전체 회귀 751개 통과(컨테이너 backup/restore 검사 포함, skip 없음), 이후 추가한 필드 artifact 발행 직후 checkpoint 전 실패·재개 테스트도 통과했다(고유 테스트 총 752개). ruff check/format·mypy(70 source files)·pnpm lint/build·git diff --check를 확인했다.

WSL Chromium에서 신규 23건의 일반 검색→최신 reader→60필드 API 대조, 신규/기존 60필드 UI, view=fields 새로고침, 관리자 필드 재실행→동일 본문 결과 재열기, 저장 이미지, 로그아웃 화면 제거와 미인증 401을 확인했다. 브라우저의 외부 요청은 0건이었다. 결과는 `data/case-fields-20260915/browser-verification.json`과 같은 폴더의 current-fields.png/legacy-fields.png에 있다. 로컬 Compose 반영 완료이며 AWS 변경·정기 실행·commit/push는 하지 않았다.


## 각주가 붙은 구획 제목 — case-fields-4

2024년 10월 실제 수집에서 `2026000033679`의 제목이 `【이    유주1)】`로 제공되어 v3가 이유를 NOT_PROVIDED로 분류하고 주문에 이유까지 포함하는 오류를 확인했다. v4는 구획명 비교 시 끝에 붙은 `주숫자)` 각주 표지만 제외해 알려진 구획과 대조한다. HTML·visible text·반환 값·근거 range의 제목/각주 표기는 그대로 유지한다. 번호 문단·특허 청구항을 구획으로 오인하지 않는 기존 제한도 유지한다.

기존 종료 자료는 보존된 HTML/metadata/조문 artifact만 재사용해 v4 revision을 생성했다. v3 및 과거 Parquet snapshot은 삭제하지 않는다. 최초 200건 비교에서 생성 시각을 제외한 값 변경은 위 판례의 주문/이유 2필드뿐이었다. 새 worker의 60필드 후속 job도 v4를 사용하며 새 기본 request key는 규칙 버전을 포함한다. 실제 재검증·최종 snapshot은 기간 증보 기록에 연결한다.


## 공백이 든 당사자 표제 — case-fields-5

첫 기간 410건의 결측 점검에서 `【원    고】`, `【피 고 인】`, `【상 고 인】`처럼 공백이 든 표제 때문에 119건의 당사자 정보가 NOT_PROVIDED로 잘못 분류된 것을 확인했다. v5는 표제 비교에서만 공백을 정규화하고, 관찰된 항소인 표제도 역할 목록에 포함한다. 원래 제목·이름·본문 문자열과 HTML은 유지한다. 임의 인물 추론이나 값 보완이 아니다.

현재 종료 자료 437건(이번 snapshot cohort 외 기존 보강 자료 포함)의 v4→v5 비교에서 당사자 두 필드만 바뀌었다. party_info 값 변경 144건, party_info_dict 146건이며 그 외 필드값은 처리 시각을 제외하고 같다. 기존 v3/v4 bytes는 유지했다. 공백 원고·피고·피고인·상고인·항소인·군검사 6종 및 이전 revision 불변 회귀를 포함해 전체 775개가 통과했다. 현재 조회/생성 기본값은 v5이며 과거 snapshot은 당시 버전의 이력이다.


## 사건기호 상세 분류 — case-fields-6

원 사건기호 `code`를 유지하면서 `case_sort`를 구조화된 값으로 발행한다. 신규 433건에서 관찰한 27개 기호를 공식 대법원 사건구분안내와 2022-07-29 시행 예규에 연결했고, 기존 REVIEW 184건의 22개 기호를 포함해 미등록 0건을 확인했다. UI는 예컨대 `가단`을 “민사 · 제1심 · 단독”으로 표시하고 공식 설명·근거·시간 적용 상태를 함께 제공한다.

2022-07-29 이전 판례에는 현행 설명을 참고값으로 제공하더라도 당시 시행본을 확인하기 전까지 REVIEW를 유지한다. 접미 글자만으로 재판부나 절차를 추론하지 않는다. 기존 89,130행의 문자열 `case_sort`, v5 이하 artifact와 Parquet는 변경하지 않는다. 상세 계약은 [사건기호 구조화 분류](case-symbol-classification.md)를 따른다.
