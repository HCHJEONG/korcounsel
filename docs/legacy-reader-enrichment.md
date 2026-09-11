# 일반 검색의 이미지·조문 보강 열람 — 2026-09-11

기존 Parquet의 `case_txt_scraped_with_tags`를 그대로 두고, 일반 검색 결과에서 보존 이미지와 lawgo 조문 내용을 읽는 경로를 연결했다. 이번 실제 등록 범위는 기존 8행이다. 전체 이미지 취득이나 신규 수집 자동 통합 완료가 아니다. [행별 본문/reader hash와 취득 결과](legacy-reader-enrichment-verification.json)를 함께 보존한다.

## 실제 표본과 누락 대조

position과 original index는 아래 8행에서 동일하다. 제목은 원문에서 가져온다. 19539행의 gmeta 재판 종류·contId는 empty이며 원문 제목은 제26사단보통군사법원 판결이다. metadata 결측을 새 canonical 등록으로 해소하지 않았다.

| position | 판례 | scourt / lawgo | 이미지 등장 / 연결 | 조문 인용 위치 / 저장 표 |
| --- | --- | --- | --- | --- |
| 33 | 대법원 2010후3226 판결 | 1970723 / 157612 | 4 / 1 | 22 / 7 |
| 8467 | 대법원 2006후4086 판결 | 1955834 / 69280 | 4 / 2 | 4 / 2 |
| 2233 | 대법원 2009다47340 판결 | 1970841 / 145511 | 6 / 2 | 7 / 2 |
| 11792 | 대법원 2005후1356 판결 | 1955787 / 68334 | 6 / 0 | 10 / 4 |
| 19539 | 제26사단보통군사법원 2002고26 판결 | empty / 77567 | 0 / 0 | 23 / 12 |
| 37 | 대법원 2009도6256 판결 | 1970725 / 157613 | 1 / 0 | 26 / 3 |
| 331 | 춘천지방법원영월지원 2010고합50 판결 | 2035511 / 221321 | 0 / 0 | 72 / 0 |
| 88590 | 대법원 2023도11810 판결 | 3328392 / 240889 | 4 / 0 | 30 / 11 |

이미지 등장에는 과거 UI 안내 이미지 `alert_img_01.png`도 포함된다. 법적 도표의 수로 해석하지 않는다. 37행에는 과거 `jomun not registered at 법제처` 표식이 9곳 있다. 331행은 조문 연결 표식은 있으나 jtable 내용이 없고 본문의 표 7개는 남아 있다. 이를 현재 법제처의 제공 정보 부재로 확정하지 않는다.

I 드라이브 `web2df/saved/20241126/lawgo_jomunupdated_panre_txt`의 `19539-empty-77567.txt`, `88590-3328392-240889.txt`를 실제로 읽었다. Parquet과 raw payload hash는 다르지만 CRLF→LF 대조만으로 각각 12개·11개 조문 payload가 순서까지 모두 일치한다. 대조를 위해 원파일을 다시 쓰지 않았다. Parquet 전체 SHA-256도 최초 export의 `3fa3a55e5d126e2f2d413c2a6cb1ab2215e135197533899f6c981d54c4d586e2`와 같다.

실제 표 안 이미지 사례는 이번 탐색에서 확보하지 못했다. 표 안 이미지·반복 등장·Unicode 위치는 합성 회귀로 검증하며 실제 표본 검증과 구분한다.

## 조문 표시와 보존

`enrichment/legacy_statutes.py`는 원래 a 태그의 위치·속성·본문 hash와 디코딩한 jtable payload/hash를 기록한다. `PRESERVED`, `LEGACY_FAILURE`, `UNLINKED`를 구분한다. 시행일·법률번호 등의 기존 표기는 표 안에 그대로 남기되 해당 판례의 적용 버전과 과거 취득 시각은 미확인으로 표시한다.

reader는 원래 인용 자리에 문서 내부 링크를 두고 본문 뒤의 보강 내용과 돌아가기 링크를 제공한다. 조문 표·문단은 같은 allowlist로 렌더링하고 원본 script/event/style/외부 요청은 실행하지 않는다. jtable 내부의 중첩 jtable은 재귀적으로 펼치지 않는다. srcDoc의 fragment가 상위 앱 주소로 잘못 이동하는 브라우저 동작은 앱이 생성한 statute/citation 링크의 내부 스크롤로 처리한다.

등록 표본에서는 원래 HTML, 조문 payload artifact, 위치·상태 manifest를 분리해 CAS/기존 artifacts에 보존한다. 별도 manifest가 없는 corpus 행도 공통 renderer에서 저장 jtable을 표시한다. 따라서 표시 코드는 전체 corpus에 적용되지만 89,130행의 모든 보강 내용에 대한 전수 품질 검증을 완료한 것은 아니다. 본문에 없는 내용을 생성하거나 조문을 새로 조회하지 않았다.

## 이미지 취득과 연결

`image-context-link-1`은 같은 source ID와 정규화 공백을 제외한 정확한 제목, 원래 URL의 contId/파일명, img name, 현재 제공자의 contImagePath 매핑, 앞뒤 각 120자의 공백 제외 문맥과 등장 순서를 대조한다. 유일한 대응만 연결하며 여러 후보·문맥 차이는 미확정으로 남긴다. 전체 문서 동일성·역사적 이미지 bytes 동일성을 확정하는 규칙이 아니다. source ID가 바뀐 후보는 이 규칙으로 연결하지 않는다.

- 보유 파일 3개를 decode 재검증해 4개 등장 위치에 재사용했다. 8467행은 같은 파일의 2개 위치가 모두 표시된다.
- 기존 11792행의 매핑된 2개 URL을 job `47a9d492-ea3b-4c22-9364-fd13abc6e67b`로 재시도했다. 두 파일 모두 `IMAGE_DECODE_FAILED`; 실제 취득 성공 0개다. job SUCCEEDED와 파일 성공을 구분한다.
- 33행은 source worker로 현재 본문을 새로 취득·보존하고, 대응을 확인한 URL 1개를 job `3be28527-9690-4fac-a4d8-ac3092ffd613`로 취득했다. GIF 1,694 bytes, SHA-256 `3b614212867dcd8166cf287f8a991a926c913534506272278c7773975e6bfbed`, 실제 decode 통과. 본문 위치 1곳을 연결했다.
- 같은 파일명이 있어도 33행의 다른 위치와 2233행의 앞쪽 위치는 문맥 비교를 통과하지 않아 자동 연결하지 않았다. src 없는 img3와 UI 안내 이미지도 미확보로 남긴다.

Pillow 12.3.0을 lockfile에 추가했다. 허용 이미지 형식만 열고 verify 후 모든 프레임을 decode하며 총 2,500만 pixel·200프레임 상한을 적용한다. [Pillow의 파일 열기·decode 계약](https://pillow.readthedocs.io/en/stable/reference/Image.html)을 따른다. worker는 허용된 공식 URL만 취득하고 redirect를 따라가지 않는다. 이미지를 변환·재인코딩하거나 OCR하지 않는다.

## 재현과 재개

기존 환경파일을 명시하고 DATA_DIR와 LEGACY_PARQUET_PATH를 실제 절대경로로 지정한다. 아래는 저장소 루트에서 실행한다. staging은 1~50개 행을 읽어 보강 revision을 등록하며 다운로드를 직접 실행하지 않는다.

```bash
export KLEGAL_ENV_FILE="$PWD/.fordeploy/aws-backup/.env"
export DATA_DIR="$PWD/data"
export LEGACY_PARQUET_PATH="$PWD/data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet"
backend/.venv-reader/bin/python scripts/stage_legacy_reader.py   --positions 8467,2233,19539   --current 8467:93f8e6069bde1b0119cc59123c8839ff0e7e7d75da96a1ca7d388b928dd25d78   --current 2233:57b10a6d5507ac460639c22e46193d98f58be42e916c97706d676d264a8fcfb7   --report data/legacy-reader-staging.json
```

보고서의 download_manifest를 기존 `klegal ops submit-image-batch`로 등록하고 최신 worker가 처리하게 한다. 동일 실행 요청은 같은 request key로 조회·재사용하고, 완료 실패를 명시적으로 재시도할 때는 새 key를 사용한다. 다운로드 후 같은 staging을 실행하면 취득 attempt/시각/hash에 연결한 새 reader revision이 생긴다. 이전 본문·reader revision·실패 기록은 남는다. 같은 입력과 취득 이력으로 재실행하면 같은 artifact를 재사용한다. worker queue·drain·lease 정책은 유지한다.

일반 `/api/cases/{position}/body?body_hash=...`는 snapshot+행+본문 hash에 맞는 보강 manifest를 찾는다. 응답 X-Reader-Revision을 프런트 URL에 보존해 새로고침 시 같은 revision을 읽는다. 다른 행·본문·snapshot의 revision을 넘기면 409이며, 이미지도 기존 인증된 `/api/reader/{revision}/images/{order}`에서 제공한다.

## 검증과 남은 범위

Python/PostgreSQL 전체 회귀 332개, ruff check/format 및 mypy를 통과했다. 프런트 타입/lint/build 통과. 실제 desktop/mobile 14개 시나리오를 확인했다. 최초 실행은 13개 통과·desktop 조문 이동 1개 실패였고, srcDoc 내부 이동 수정 후 해당 desktop 시나리오를 재실행해 통과했다. 모바일 조문 이동도 수정 후 통과했다. 8개 staging을 다시 실행해 모두 동일한 reader revision이 재사용됐으며 기존 import의 PRESERVED·고유 position은 각각 89,130개다. 일반 검색은 현재 pyarrow 전체 컬럼 scan이며 이번 좁은 검색 표본에서는 약 30초가 걸렸다. 검색 엔진·색인 변경은 수행하지 않았다.

남은 범위는 89,130행의 재개 가능한 전수 연결 계획·품질 집계, 미확정 이미지의 추가 문맥/제공자 확인, 실제 표 안 이미지 표본, lawgo 미보강분의 현행 취득 경로와 신규 수집 자동 통합이다. 신규 본문도 공통 reader와 decode 검증을 사용할 수 있지만 신규 판례 수집→lawgo 보강→일반 검색 등록의 종합 검증을 완료한 것은 아니다. PostgreSQL 원행 보존·canonical·gold 상태를 변경하지 않았고 AWS 배포·운영 변경도 수행하지 않았다.
