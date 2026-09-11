# 레거시 이미지 미해결 원인 감사 — 2026-09-11

`scourt-body-image-targets.json`의 `source_id_usable=false` 43행과 `MISSING_SRC` 17곳/3행을 원본 교정 Parquet 및 기존 전수 inventory와 읽기 전용으로 대조했다. 두 집합은 겹치지 않아 총 46행이다. 원문·ID·reader revision·수집 대상을 변경하지 않았으며 DB 쓰기나 추가 live 수집은 수행하지 않았다. 목록에는 position과 이유만 남기고 원 URL·query token은 기록하지 않는다.

## gmeta 기반 재조회 ID 미확보: 43행

43행 모두 원 Parquet의 `gmeta_contId`와 `lmeta_serialno`가 문자열 `empty`다. 함께 저장된 gmeta 법원·사건번호·재판 종류도 `empty`이며 lawgo 법원·사건번호 관측은 원래 정수 0으로 보존된 결측 표현이다. 모든 행의 site는 glaw다. 현재 inventory는 `gmeta_contId`를 읽고 양의 ASCII 숫자인 경우에만 `source_id_usable=true`로 표시하므로, 원 값이 있는데 잘못된 컬럼을 선택했거나 문자열 숫자를 오인한 확정 코드 오류는 확인하지 못했다.

그러나 이 43행의 원문 전체에 출처 ID가 없는 것은 아니다. 정적 표식 3종을 제외한 이미지 **424곳** 모두 공식 glaw의 보존된 이미지 참조이며 숫자 contId와 비어 있지 않은 attachImgNm이 남아 있다. 각 행 안에서 contId는 정확히 하나로 일관되고, 43행 사이에서도 서로 다른 43개 후보다. 이 후보 값은 전체 89,130행 inventory의 gmeta 기반 source_id 어디에도 등록되어 있지 않았다. 행별 고유 이미지 파일명 합계는 423개이며 6429행의 같은 파일명 2회 등장 때문에 위치 수가 하나 더 많다. 반복 위치를 합치거나 제거하지 않았다.

이는 **원 이미지 주소에 보존된 출처 관측 후보**이며 판례 행과의 문서 동일성, 현재 제공자 조회 가능성, 공식 metadata 등록을 확정한 결과가 아니다. gmeta 누락 원인이 당시 목록 수집·매칭·가공 중 어느 단계였는지는 이 자료만으로 확정하지 않는다. URL에서 본 contId를 gmeta·canonical ID로 자동 승격하거나 이번 1,825개 기본 재조회 source 목록에 자동 추가하지 않는다. 현재 상태는 ‘gmeta 기반 source ID 미확보 / 원문 URL ID 후보 관찰 / 연결 미확정’으로 구분하는 것이 정확하다.

43행의 `folder_file_name`은 모두 과거 수집 페이지·페이지 안 순번을 담은 `page_…_case_…-jomunimgsrcprocessed.txt` 형태다. 별도 contId나 lawgo serialno를 명시한 파일명이 아니므로 페이지 번호를 출처 ID로 사용하지 않는다. HTML에는 별도 contId input 및 contImagePath 파일명 매핑 input이 없고, `case_txt_in_file`에서도 이미지 src/contId를 제공하는 별도 태그를 확인하지 못했다. 이미지 원 src 자체의 후보와 원래 행 locator를 유지한다.

| position | 이유 |
| --- | --- |
| 6429 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정; 같은 파일명 반복 위치도 유지 |
| 6620 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 26270 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 28164 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 32825 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 32827 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 33042 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 33055 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 34396 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 35496 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 37059 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 39052 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 39490 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 39714 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 39924 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 40593 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 40807 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 40809 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41045 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41046 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41047 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41048 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41049 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41262 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41278 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41490 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41491 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41700 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41701 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41705 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41707 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41709 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41710 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41711 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41712 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41714 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정; 정적 제공자 표식 1곳은 별도 집계 |
| 41920 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41921 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41932 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41933 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41934 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41935 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |
| 41936 | gmeta·lawgo ID 누락; 원 이미지 주소의 단일 ID 후보와 파일명은 보존됐으나 행 연결 미확정 |

## 원문 태그에 src가 없는 17곳: 3행

이 3행은 모두 gmeta contId와 lawgo serialno가 숫자로 보존되어 있다. 따라서 위 43행의 ID 누락 문제와 다르다. 해당 img에는 name과 `object-fit:contain` style만 있고 src 속성 자체가 없으며, 기존 HTML에는 contImagePath input이 없어 보존본만으로 name을 첨부 파일명에 대응시킬 수 없다. `case_txt_in_file`은 img 태그가 없는 텍스트이며 독립 이미지 매핑 근거가 아니다. 과거 처리 시점에 주소가 누락됐다는 관측까지 가능하고, 당시 제공자가 이미지를 제공하지 않았다고 단정하지 않는다.

| position | 이유 |
| --- | --- |
| 2233 | src 없는 img3가 order 0·5에 반복된 2곳. 다른 4곳의 주소는 있으나 img3 파일명으로 대체할 근거가 없음 |
| 9389 | 유일한 img1의 src가 없는 1곳. 출처 ID는 있지만 보존 파일명 매핑이 없음 |
| 11394 | Img1~Img14의 src가 모두 없는 14곳. 원래 등장 순서 중 Img13·Img14가 Img10~Img12보다 앞서며 번호를 정렬하거나 URL을 추측하지 않음 |

현재 source의 보존 응답에 해당 이미지 name·파일명 대응이 나중에 관찰되더라도, 제목·문서 증거와 원문 위치·주변 문맥을 확인한 별도 연결 revision이 필요하다. 이번 감사는 이를 실행하지 않았으며 17곳을 취득/연결 완료로 세지 않는다.

## 기본 그림 재조회 및 정적 표식과의 경계

기본 그림 목록은 1,872행·10,877위치이며 gmeta source ID가 사용 가능한 1,829행에 서로 다른 1,825개 source가 있다. 위 43행/424위치는 그 기본 source 재조회에서 제외된 상태로 남는다. src 누락 3행은 ID 사용 가능한 행에 속하지만, 그 사실만으로 17곳의 이미지 참조가 회복되지는 않는다.

`alert_img_01.png`, `flag_01.gif`, `flag_03.gif`의 정적 제공자 표식은 원 glaw 주소의 기존 DNS 실패 이력이 있는 별도 3 URL이다. 기본 그림 1,825 source 재조회와 분리하며 이 감사에서 다시 호출하지 않았다. 표식의 원래 alt·위치·원 참조는 유지한다. 기본 그림 재조회 성공을 정적 표식 3 URL이나 위 미해결 위치의 성공으로 확대 해석하지 않는다.

## 재현 근거

- 대상 목록: `data/legacy-reader-scale-20260911-v1/scourt-body-image-targets.json`, SHA-256 `82a5a30037293bed58dd463391324e1c5661e0610851d8cd687185519238de71`.
- 원본 교정 Parquet: `data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet`, SHA-256 `3fa3a55e5d126e2f2d413c2a6cb1ab2215e135197533899f6c981d54c4d586e2`. 감사 후 기존 고정값과 일치했다.
- 기존 전수 inventory: `data/legacy-enrichment-inventory-20260911-v1/rows.jsonl` 및 `summary.json`. 이번 읽기에서 summary SHA-256은 `ed472060b0626eea900aba9dab2db6ac0790506bb0c516c6ec1afd43732cad9d`다. rows 파일은 89,130행이며 SHA-256 `ae4332ee5652cbbe3b0a01747654dc82eb1a1b1eaad130e4c908b85e8f4c8045`가 summary의 고정값과 일치했다.
- Parquet에서 위치로 선택한 46행의 기준 본문 SHA-256이 대상 목록의 각 body_hash와 일치함을 확인했다. 원문 HTMLParser/기존 image_occurrences로 src 유무·원 query 필드 존재·행별 ID 일관성·파일명 반복을 대조했으며, URL 원문은 이 보고서에 복사하지 않았다.

이 문서는 미해결 사유 감사이며 새 취득·ID 복구·reader 연결 완료 보고가 아니다. 코드 변경은 없고 상태를 pending/미확정으로 유지한다.
