# 전체 import 전 text 파일 포함 관계 점검

2026-09-10. 전체 89,130행 import는 실행하지 않고, 기존 DataFrame과 실제 저장 text 파일을 읽기 전용으로 대조했다.

## 결론

확인한 두 레거시 저장소 범위에서 **DataFrame 밖의 새 판례로 확정할 자료는 발견하지 않았다.** 다만 공식 ID로 연결되지 않는 재결 저장본과 metadata 보완 과제가 있다. 별도 text 원본은 DataFrame 안의 보강본과 다른 representation이므로 함께 보존할 가치가 있다.

| 파일 분류 | 파일 수 | 확인 내용 |
| --- | ---: | --- |
| DataFrame 저장 문자열과 일치 | 7,989 | Python text-mode 읽기의 CRLF/CR → LF 변환을 적용하면 정확히 일치 |
| 기본 본문과 저장 보강본이 다른 경우 | 491 | 같은 source ID·대상 행으로 연결되는 보강 파일이 별도로 있으며, 그 보강본은 DataFrame과 일치 |
| 공식 ID로 미연결 | 2 | 두 날짜 폴더의 2029039.txt. 같은 재결로 보이는 기존 행 6429를 metadata에서 발견 |
| 합계 | **8,482** | 파일 수이며 고유 판례 수가 아님 |

법제처 조문 보강 text 파일 **7,821개 전부**가 줄바꿈 변환 후 DataFrame의 본문 필드와 일치했다. 직접 문자열이 일치하는 파일이 그 파일명 source ID와 무관한 다른 행에만 배치된 사례는 이번 대조에서 없었다.

## 실제 점검 범위

- 기준 DataFrame: saved/20241126/df_glaw_corpus/df_glaw_corpus_fullest_gmeta_lmeta.pickle
- SHA-256: aa3d2c57d0f647b8c078df5784be5ef3e02e8b24cf40e543e9358b7b74dc7b69
- **89,130행·60컬럼**. 모든 행의 case_txt_scraped_with_tags 및 case_txt_in_file을 대조했다.
- 탐색 루트: I:\\VSCodeBases\\web2df 및 I:\\VSCodeBases\\df2preproc. .git·개발 의존성 폴더를 제외했다.
- text/html/htm 파일을 탐색했으며 발견된 것은 txt 8,482개다. df2preproc에는 해당 파일이 없었다. 두 저장소의 사전 파일 분포 점검에서 압축 archive 파일은 발견되지 않았다.
- 읽기/encoding 실패, 디렉터리 접근 오류, 미탐색 symlink는 없었다. 컴퓨터의 모든 드라이브를 전수 검색한 결과는 아니다.

| 폴더 | 전체 | 저장 내용 일치 | 기본/보강 차이 | ID 미연결 |
| --- | ---: | ---: | ---: | ---: |
| saved/20240723/glaw_updated_panre_txt | 120 | 83 | 36 | 1 |
| saved/20240723/lawgo_jomunupdated_panre_txt | 7,365 | 7,365 | 0 | 0 |
| saved/20241126/glaw_updated_panre_txt | 541 | 85 | 455 | 1 |
| saved/20241126/lawgo_jomunupdated_panre_txt | 456 | 456 | 0 | 0 |

원본 파일 bytes hash는 8,482개 모두 서로 달랐다. DataFrame 문자열의 UTF-8 bytes와 원본 파일 bytes가 그대로 일치한 파일은 0개였지만 이를 내용 누락으로 해석하면 안 된다. 기존 _03_create_new_df.py:693 부근과 _07의 open(..., mode='r')/read()가 text-mode newline 변환을 수행한다. 원본 bytes hash와 별도 newline 비교를 구분했다. 원본 파일과 DataFrame 값은 변경하지 않았다.

source ID로 연결되는 corpus 행은 8,102행이다. 파일 하나가 여러 중복 행에 연결되거나 같은 사건의 기본·보강·날짜별 파일이 따로 있으므로 파일 수와 행 수를 일대일로 비교하지 않는다.

## 확인이 필요한 재결 1건·저장 파일 2개

- saved/20240723/glaw_updated_panre_txt/2029039.txt
- saved/20241126/glaw_updated_panre_txt/2029039.txt

파일 제목은 **중앙해양안전심판원 2008. 12. 4.자 중해심제2008-26호 재결**이다. 두 파일은 제목의 “4.자”와 “4. 자” 사이 공백 1개를 제외하면 bytes가 동일하다. 각각의 원본 hash를 유지하며 파일을 삭제·병합하지 않았다.

DataFrame의 **원래 position/index 6429**에서 다음 값을 확인했다.

| 항목 | 기존 값 |
| --- | --- |
| 기관 | 중앙해양안전심판원 |
| 사건번호 | 2008중해심26 |
| 인용문 | 중앙해양안전심판원 2008. 12. 4.자 2008중해심26 기타 |
| gmeta_contId / lmeta_serialno | 둘 다 empty |
| 저장 HTML | 200,321 Unicode 문자, img 태그 34개 |

따라서 새 판례 2건이 누락됐다고 판단할 근거가 아니다. 같은 재결로 보이는 기존 기록이 있으나 **source ID 연결·사건번호 표기·재판 종류(기타/재결)를 검토해야 한다.** 본문 전체가 동일하다는 판단이나 자동 canonical 연결은 하지 않았다.

레거시 _03_create_new_df.py:2189에는 중앙해양심판원 사건 1개가 오류로 건너뛰어진다는 주석이 있다. 이는 이번 파일의 공식 ID가 기존 row에 연결되지 않은 현상과 부합하지만 당시 실행 로그 자체를 확인한 것은 아니다. 기존 6429행에 본문이 있으므로 사건 전체가 corpus에서 빠졌다고 설명하지 않는다.

## 예전 파일 경로와 현재 DataFrame

folder_file_name에는 다음 과거 루트가 남아 있다.

- C:\\casesscrapedwithjomunimg_nnn: 86,606행
- D:\\VSCodeProjects: 1,865행

현재 그 경로를 그대로 찾으면 디렉터리가 없다. 저장 위치 이동 가능성은 남아 있으며 이를 원본 삭제나 DataFrame 본문 결측으로 단정하지 않는다. 이번 대조는 현재 확인한 레거시 저장소의 파일만 대상으로 했다. 89,130행 전체에는 본문 문자열이 이미 보존돼 있다.

## 다음 순서

1. 기존 89,130행은 현재 FULL_ROW importer로 보존 import할 수 있다. 본문·원행은 파일 저장소에, PostgreSQL에는 참조·metadata·처리 이력을 저장한다.
2. 별도 txt 8,482개도 원래 파일 hash·경로·source ID 및 기존 행과의 연결 근거를 가진 보존 대상으로 관리한다. 기본/보강 representation을 하나로 덮어쓰지 않는다.
3. 6429행과 2029039 파일의 연결 및 재판 종류를 검토하고, 확정 시 새 연결 revision으로 반영한다. 원래 empty·기타 값은 그대로 보존한다.

이번에는 점검·보고서만 작성했다. 전체 DB import, 파일 삭제/수정, ID 재연결, metadata 정정, 재수집, AWS 변경은 하지 않았다.

## 재현·검증 자료

- [전수 결과](legacy-text-coverage-audit.json)
- [미연결 재결과 줄바꿈 표본 확인](legacy-text-coverage-followup.json)
- scripts/audit_legacy_text_coverage.py: 전체 본문 hash·source ID·newline·보강 counterpart 비교.
- data/legacy-audit/text-coverage-inventory.jsonl: 파일별 hash·후보 행·일치 필드. Git 제외, 보고서에 checksum 기록.
- data/legacy-audit/corpus-body-field-hashes.json: 반복 조사용 본문 hash 색인. snapshot hash와 연결하며 원문 대체물이 아니다.
- audit 분류·newline 회귀 9건 및 ruff 검사 통과. 앱 runtime 코드는 변경하지 않았다.
