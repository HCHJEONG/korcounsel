# 레거시 이전 분석 — Step 0

확인일: 2026-09-09. 실제 경로는 `I:\VSCodeBases\web2df`, `I:\VSCodeBases\df2preproc`다. 원본 저장소를 읽어서 분석했으며 수정·import·crawler 실행·pickle 역직렬화는 하지 않았다. 이 경로는 개발 참고 위치이며 앱 런타임 의존성이 아니다.

## 분석 범위와 근거

`web2df` 루트 Python 파일을 목록화하고 `_03_create_new_df.py`, `_04_concat_old_and_new_df_corpus_then_create_fullest.py`, `_11_law_open_api_scraping.py`, 두 util 파일과 `_08`, `_09`, `_10`의 관련 부분을 확인했다. `df2preproc/_1_glaw_df2preproc.py`는 활성 처리 흐름을 확인했다. 하위 legacy/노트북/저장 데이터 전체 감사나 실행 결과 검증은 하지 않았다. 아래 위치는 원본 파일의 1-based 행 번호다. [소스 해시 목록](step0/legacy-source-manifest.json)으로 분석 당시 파일을 식별한다.

재사용은 개념과 검증된 규칙의 재작성이다. 원본 코드를 새 프로젝트에 import하거나 일괄 복사하지 않는다. 검색 범위에서 LICENSE·dependency lock·pyproject·requirements 파일을 찾지 못했다. 코드 재배포 라이선스는 확정하지 않는다.

## 1. web2df에서 가져올 개념과 필드

원본 판례와 판시사항·요지·참조조문·참조판례를 연결하고 번호별 하위 항목으로 만드는 방향은 유지한다. 표시 문자열 `case_full_no` 하나에 식별자·날짜·법원을 의존하는 방식은 바꾼다.

| Legacy field | 실제 의미 / 관찰 위치 | 새 계약과 이동 위치 |
| --- | --- | --- |
| case_full_no | 법원·날짜·사건번호·판결/결정 및 일부 표시가 섞인 인용 문자열. `_03:735–786` | 원래 표시를 보존하고 `domain/LegalCase`, `normalize/metadata`에서 구성 요소 분리. source 식별자는 source+공식 serial이며 canonical은 별도 registry ID |
| case_txt_in_file | 파일에서 읽은 원문. `_03:909` 이후 section 탐색 및 summary 행에 반복 저장 | 원본 응답은 `storage/`; 디코딩된 기준 텍스트와 필드별 위치는 provenance로 참조 |
| decision_items | 판시사항 section. `_03:913–920` | `parse/`에서 번호·범위를 보존한 issue 후보 |
| decision_gists | 판결요지 section. `_03:923–931` | answer 후보. 결측이면 생성하지 않고 unmatched |
| reasoning | 이유 heading 변형으로 찾는 본문 영역. `_03:1286` 이후 | `parse/sections`에서 주문·당사자 등과 분리. API 판례내용 전체를 이유로 간주하지 않음 |
| applicable_acts | 참조조문 section. `_03:934–942` | `domain/LegalAuthority`, `parse/citations`; 우선 case 범위 인용 |
| applicable_precedents | 참조판례 section. `_03:945–954` | 원래 인용 + 파싱된 식별 요소. 사건에 등장했다는 이유만으로 각 issue에 직접 연결하지 않음 |
| number / items / gists / acts / precedents | `_03:395–510,1523–1568`에서 같은 번호를 조회해 summary row 생성 | `pipeline/`의 명시적 alignment. 번호 누락·복수 번호·무번호를 보수적으로 처리 |
| cname / idx / unit_str / gistno | df2preproc 문장·구 절편과 원래 summary 위치. `:229–230` | `segment/` 결과 + 기준 필드의 code point span. 행 번호는 evidence offset이 아님 |

공식 API 목록의 `판례일련번호`와 본문의 `판례정보일련번호`를 같은 source_document_id로 연결한다. 사건번호는 병합 목록과 원문을 함께 보존한다. 중복은 source+ID+raw hash로 관리하고 수집 시도와 내용 버전을 구분한다.

## 2. 전처리 규칙 판정표

A는 개념 재사용, B는 수정 후 사용, C는 기본 pipeline에서 폐기다. A도 기존 함수를 그대로 사용한다는 뜻은 아니다. Test는 [회귀 fixture](../tests/fixtures/legacy/regression-cases.json)의 ID 또는 후속 테스트 요구다. fixture는 합성 데이터이며 앱 테스트 통과를 뜻하지 않는다.

| Legacy Rule | Current Meaning | Decision | Replacement | Test |
| --- | --- | --- | --- | --- |
| section별 판시사항·요지·인용 추출 `_03:909–954` | 법률 문서 구성 요소 분리 | A | `parse/sections`, 인식된 heading 및 위치 보존 | section-preserve |
| raw와 metadata 연결 `_03:491–496` | 결과에서 원래 판례 추적 | A | immutable artifact + Provenance 참조 | 후속 hash/round-trip |
| lnfd → newline `df2preproc:59` | 웹 추출 시 만든 줄바꿈 표식 | B | legacy adapter에만 적용. 공식 원문에서 literal lnfd 일괄 치환 금지 | literal-marker |
| remove_judges `df2preproc:321–325` | lnfd 사이 재판부 서명 삭제 | B | 인식된 끝부분 서명 범위만 별도 분류, raw 보존 | signature-context |
| 빈 괄호를 그림으로 변경 `df2preproc:61–67` | 빈 추출 artifact에 의미 부여 | C | 결측/추출 경고; 그림을 생성하지 않음 | empty-parenthesis |
| 별지·대괄호 전체 삭제 `df2preproc:69–75` | 번호·별지 외 법률 한정 문구까지 제거 | C | 내용 보존 후 구조 분류 | bracket-content |
| 모든 【…】 삭제 `df2preproc:77–79` | heading과 임의 내용 구분 없음 | B | 알려진 heading만 구조로 인식, 그 외 보존 | section-preserve |
| 숫자·한글·원문자 번호 삭제 `df2preproc:81–159` | 구조 신호를 문장 분리 전에 소거 | B | 위치·문맥 기반 번호 파싱, 텍스트/번호 둘 다 보존 | numbering-fourteen |
| whitespace 축약 `df2preproc:219–220` | 비교용 텍스트 정리 | B | normalized 파생값 + source 위치 매핑 | 후속 whitespace-offset |
| KSS 문장 분리 `df2preproc:166–180` | 외부 NLP와 worker 8 의존 | B | SentenceSplitter interface + 기본 결정론적 splitter | sentence-tail |
| 길이·숫자 비율 필터 `df2preproc:190,208,222` | 짧은 주문·금액 문장도 누락 | C | 보존하며 quality flag만 기록 | short-disposition, numeric-content |
| 문장 residue replace `df2preproc:334–353` | 잔여문을 전역 문자열 치환으로 계산 | B | 현재 cursor 이후 slice; 한 글자 잔여문도 보존 | repeated-sentence, sentence-tail |
| 문장 buffer `df2preproc:355–383` | 사건 경계를 넘는 누적·마지막 미완성문 유실 | B | 사건/필드별 buffer와 마지막 flush | cross-case-buffer, unfinished-tail |
| comma phrase buffer `df2preproc:238–305` | 괄호를 묶는 휴리스틱; 잔여 buffer 미배출 가능 | C | MVP evidence에 구 분리를 강제하지 않음 | phrase-tail |
| sen_phr_pair 홀수 마지막 삭제 `df2preproc:304–317` | 학습 pair 길이 맞춤 | C | 홀짝과 관계없이 보존. 현재 main은 False임 | odd-units |
| 순차 번호별 summary `_03:428–488,1523–1568` | 모든 필드가 비는 번호에서 중단; 후속 번호 누락 가능 | B | 존재하는 번호 집합 순회; 모호한 연결은 ambiguous | numbering-gap |
| 〔14〕 → [13] `_03:1670` | 손으로 나열한 변환표의 오타, 〔13〕 처리 누락 | B | 범용 숫자 파싱과 원래 번호 보존 | numbering-fourteen |
| 첫 사건번호만 사용 `util_df_standard_case:74–82`, `_04:46–54` | 병합 정보 손실 | B | 전체 사건번호 배열 + 원문 | merged-dockets |
| 사건번호 문자 class의 pipe `util_df_standard_case:75` | 문자 class의 세로줄도 사건구분 문자로 허용 | B | 사건구분자 검증 + 실패 상태 | invalid-docket-pipe |
| 잘못된 날짜 → 2072 `_04:106–128` | 결측을 실제 미래 날짜처럼 저장 | C | nullable date + parse error; `parser.parser(...)` 호출도 재작성 | invalid-date |
| 법원 분리 `_04:74–104` | 날짜 내부 공백 전제에 따라 법원에 날짜가 섞일 수 있음 | B | 날짜와 법원 각각 검증 | compact-date |
| int(total/20)+1 `_11:483` | 정확한 배수에서 불필요한 마지막 page | B | 실제 page size로 ceil, 빈 page 종료/중복 방지 | pagination-multiple |
| prec를 항상 반복 목록으로 취급 `_11:508` | singleton object / empty 결과 미대응 | B | object/list/absent 명시적 변환 | singleton-result, empty-result |
| Hangul 외 제거와 Word2Vec `util_case_df2case_df_for_ml:47–56` | 학습용 손실 전처리 | C | 학습 pipeline 제외 | numeric-content |

## 3. 제거할 dependency와 실행 결합

추가 지시로 Selenium/BeautifulSoup/웹 scraping의 일괄 폐기 판단을 수정한다. DOM·세션·popup·iframe·image reference 확보 역할을 조사하고 scourt adapter에 필요한 취득 수단을 선택한다. 기존 driver 하드코딩·parmap/multiprocessing 결합은 그대로 이전하지 않는다. pdfplumber 표준 판례집 입력과 학습용 konlpy/Okt·gensim/Word2Vec·NumPy shuffle은 초기 제외하되 PDF_TEXT/SCAN artifact schema는 포함한다. df2preproc의 KSS는 선택적 후속 adapter로 미루며 주석 처리된 Kkma/Kiwi/NLTK는 실제 활성 dependency로 세지 않는다.

pandas는 도메인 계약과 중간 저장의 필수 의존성에서 제거한다. 공식 API 통신·JSON/XML parsing·Parquet export에 필요한 패키지는 Step 1/3에서 별도로 고정한다. stdlib re/logging/hashlib 같은 기능과 section·citation 추출 개념은 유지한다. 라이브러리 버전 전체를 추정해 requirements를 복원하지 않는다.

## 4. hard-coded path

- `util_df_standard_case.py:9,12,160`: `e:/20211026/` 아래 PDF·CSV 경로.
- `util_case_df2case_df_for_ml.py:20,70,72`: 사용자 홈의 VSCodeProjects/df2model 및 web2df 저장 경로.
- `df2preproc:385–436`: 날짜를 입력받고 `../web2df/saved/<date>` pickle을 읽어 `../web2df/dataset/<date>`에 기록.
- `_10`의 플랫폼별 경로와 `_03/_04/_08`의 saved/CSV/pickle 위치는 실행 디렉터리와 과거 작업 환경에 결합되어 있다.

새 구조에서는 명시적 DATA_DIR·run ID·source ID와 pathlib을 사용한다. I: 드라이브나 레거시 폴더 없이 EC2에서 동작해야 한다. .env는 사용자가 선택한 경로에서만 로드한다.

## 5. pickle과 DataFrame 문제

`_03:623,638`, `_04:510–568`, `df2preproc:385–436` 등은 corpus/summary 전체를 pickle로 저장·로드한다. 대규모 전체 적재, 클래스·패키지 버전 결합, 부분 실패 복구 및 안전한 교환 형식 부재가 문제다. 이번 분석에서는 pickle을 열지 않았다. 새 기본 형식은 원본 JSON/XML 바이트, 버전 있는 중간 artifact와 JSONL/Parquet이며 기존 pickle 일괄 import는 별도 미래 작업이다.

`_03:498,500`의 행별 DataFrame.append, 표시 인용문 기반 join/dedup, summary 행별 전체 원문 중복, 빈 문자열·None·숫자·미래 날짜가 섞인 결측 표현을 버린다. `_08`은 module-level pickle 읽기와 case_full_no 연결을 사용한다. `util_df_standard_case:149–155`의 법원+사건번호 dedup은 선고일·문서 버전 구분이 없다. 도메인 객체, stable ID, explicit missing/error, 원문 artifact 참조로 대체한다.

## 6. 취약 regex와 Python 호환성

번호 변환이 여러 함수와 파일에 중복되어 있으며 `_03:1533`은 같은 번호 그룹을 수십 회 나열한다. `_03:1634` 이후 손으로 쓴 치환표, df2preproc의 bracket 삭제와 후속 번호 삭제는 유지보수·정보 손실 위험을 함께 만든다. section 경계의 `[^【]+`는 내부 표식에 민감하다. 알려진 구조를 작은 parser로 처리하고 미인식 부분은 그대로 남긴다.

web2df Dockerfile은 `python:3.8.19-bullseye`이며 루트에 없는 requirements·설치 script·실행 파일을 COPY한다. 그 Dockerfile을 현재 배포에 재사용하지 않는다. pandas 2.0에서 DataFrame.append가 제거되었으므로 기존 호출은 현대 pandas에서 그대로 동작하지 않는다. [공식 pandas 변경 내역](https://pandas.pydata.org/docs/whatsnew/v2.0.0.html)

목표는 Python 3.12지만 이번 로컬 WSL 기본 Python은 3.10.12였다. 레거시의 Python 3.12 실행 호환성·KSS 설치·전체 dependency 충돌은 테스트하지 않았다. 정규식 escape, import 시 I/O, deprecated API를 새 구현에서 독립적으로 해결하고 Step 1의 3.12 환경에서 검증한다. `_04:parser.parser(temp_date_string)`는 날짜를 반환하는 parse 호출이 아니며 예외를 sentinel로 감추는 흐름이다.

## 7. 새 아키텍처로 옮기는 순서

1. `sources/`: 공식 목록·상세 client, ID 유지, pagination, timeout/retry와 명시적 오류. `_11`의 절차 개념만 참고한다.
2. `storage/`, `domain/`: immutable raw 및 hash, LegalCase/LegalIssueUnit/EvidenceSpan/LegalAuthority/Provenance.
3. `normalize/`, `identity/`, `ingestion/`에서 metadata·canonical·inventory를 분리한다. `parse/`, `documents/`, `assets/`에서 section·citation 및 source fidelity를 보존한다.
4. `segment/`, `pipeline/`: 문서 경계와 위치를 보존하며 alignment 및 후보/오류를 출력한다.
5. `validate/`: evidence exact slice, 결측, ambiguous, 버전·재현성 검증 후 export한다.
6. `db/`, `jobs/`, `web/`와 frontend는 같은 core 결과를 조회·실행한다. 레거시 학습용 CSV/DataFrame UI를 만들지 않는다.

## 8. 검증 상태와 남은 일

회귀 fixture는 실제 정적 분석에서 발견한 규칙을 합성 입력과 기대 동작으로 기록했다. 운영 판례 원문·개인 데이터·인증값을 포함하지 않는다. fixture JSON 구조와 ID를 검증했으며 실행 가능한 신규 parser/pytest는 아직 없다. 구현 단계에서 각 fixture를 테스트에 연결해야 한다.

공식 API 계약과 실제 소량 조회 결과는 [API 메모](law-open-api-contract.md)에 분리했다. 이 분석은 Step 0 산출물이며 Step 1 이후 구현·전체 레거시 실행 검증·AWS 배포 완료를 의미하지 않는다.

## 추가 조사에 따른 정정 — 2026-09-09

초기 Step 0은 `_05/_06`의 복합 identity 매칭·이미지 보존 책임을 충분히 다루지 못했다. [추가 조사 보고서](legacy-case-identity-and-assets.md)가 이를 보완한다. 첫 사건번호 사용에는 병합 표기 대응과 뒤 숫자 prefix 오탐 보호라는 의도가 있었으며 새 resolver에서 전체 번호·유일 후보 검증으로 계승한다.

`gmeta_contId`와 `lmeta_serialno`는 source ID이고 canonical identity가 아니다. source+ID+hash는 원본 버전의 키로 유지하되 canonical 연결 revision을 별도로 둔다. `_02`의 ID 집합 비교를 inventory subsystem으로 계승한다. 모든 판례의 editorial 구조를 전제하지 않고 Detect/Preserve Reference를 초기 범위에 넣는다.

새 회귀 범위는 [추가 fixture](../tests/fixtures/legacy/identity-fidelity-cases.json)에 있다. 원래 23건은 보존하며 추가 30건은 합성 계약 사례다. 저장 자료 8,482개 조사 수치는 고유 판례 수가 아니며 실제 관찰과 미검증 표본을 추가 보고서에서 구분한다.
