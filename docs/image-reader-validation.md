# 이미지 포함 본문 열람 구현·검증 — 2026-09-11

**최종 열람 목표 보완 — 2026-09-11 사용자 확정:** 검색된 판례를 클릭했을 때 scourt HTML 기반 본문, 원래 위치의 scourt 이미지, lawgo 법령·조문 보강 내용이 함께 나타나야 한다. 아래 이미지 표본 검증은 이 목표의 일부다. 검색 corpus에 이미지와 조문을 모두 연결한 통합 열람의 완료를 뜻하지 않는다. [완료 기준과 보존 계약](legacy-enrichment-and-incremental.md#검색에서-완전한-보강-본문-열람까지).

**로그인 정책 갱신 — 2026-09-11:** 아래 최초 CLI 계정 생성 안내보다 [환경변수 두 계정 정책](site-login.md)이 우선한다. 설정 비밀번호로 첫 로그인 시 DB에 해시로 등록되며 다른 DB 계정의 웹 접근은 거절된다.

사용자 목표는 다운로드한 이미지가 판례 본문의 원래 위치에 표시되는 것이다. 이번 단계에서 **실제 표본의 보존 이미지 → 본문 내 위치 → 인증된 화면 표시**를 연결했다. 전수 corpus 이미지 복구 완료와는 구분한다.

## 실제 등록 표본

| 별도 보존한 현재 제공 본문 | 이미지 등장 | 저장 파일 연결 | 실패 위치 |
| --- | ---: | ---: | ---: |
| 대법원 2008. 2. 28. 선고 2006후4086 판결 | 2 | 2 | 0 |
| 대법원 2005. 1. 28. 선고 2003후2249 판결 | 2 | 2 | 0 |
| 대법원 2010. 5. 13. 선고 2009다47340 판결 | 6 | 4 | 2 |
| 대법원 2006. 11. 23. 선고 2005후1356 판결 | 3 | 0 | 3 |
| 합계 | 13 | 8 | 5 |

각 수치는 고유 파일 수가 아니라 본문 내 등장 위치 수다. 같은 이미지가 여러 번 쓰여도 별도 위치를 보존한다. 기존 분석 단계에서 취득한 bytes와 mapping·ledger·source response를 검증하여 재사용했으며 이번 단계에서 새 live 다운로드를 수행한 것은 아니다. 첫 표본의 같은 파일이 두 위치에 표시되는 것을 실제 브라우저에서 확인했다.

결과 manifest ID와 제목·집계는 `data/reader-samples-20260911.json`에 기록했다. 이 네 표본은 현재 제공 본문을 독립 보존한 것이다. 동일 source ID나 파일명만으로 과거 Parquet 본문에 이미지를 붙이거나 canonical 연결을 확정하지 않았다.

## 위치와 파일의 연결

`documents/reader.py`는 HTML parser로 각 img의 등장 순서, 원 src/name, 제공자 매핑과 URL, HTML 행/열, 태그의 시작·끝 위치, 원 태그, 전후 문맥을 얻는다. 모든 위치는 특정 UTF-8 본문 hash에 고정된다. 문자열 위치는 Python Unicode code point이며 정규화 텍스트 evidence offset이 아니다. `html[start:end] == html_tag`를 검증한다.

`documents/reader_store.py`는 기존 Records/FileStore를 통해 다음을 불변 artifact로 저장한다.

- `reader-html:<hash>`: 기준 HTML 문자열의 UTF-8 bytes.
- `reader-image:<hash>`: 저장한 이미지 bytes.
- `reader-evidence:<hash>`: 원래 mapping과 취득 ledger.
- `reader-source:<hash>`: 기존에 취득·보존한 source response.
- `reader:<manifest hash>`: 본문·개별 이미지 위치·취득 상태·실제 파일 hash·근거 artifact를 연결하는 manifest.

본문·이미지 파일은 읽을 때도 hash를 확인한다. reader manifest는 artifact 테이블과 파일에 영속 저장하며, 기존 URL 그룹 기반 image_references 테이블을 본문별 위치 전수 보존으로 오인하지 않는다. 이번 위치 보완은 reader manifest의 개별 occurrences에 적용됐다. 두 ledger를 하나의 worker 흐름으로 연결하고 전수 확장하는 작업은 남아 있다.

## 화면과 API

- 최초 화면은 로그인이다. 기존 app_users/app_sessions와 scrypt password hash를 재사용한다.
- 기존 Parquet 문자열 검색에 본문 hash를 반환한다. 검색 결과의 본문 열기는 해당 hash가 일치하는 행만 읽는다. Parquet에 있는 과거 본문은 원 태그 위치에 미확보 안내를 표시하며, 미확정 현재 이미지를 자동으로 끼워 넣지 않는다.
- 별도 보존한 실제 표본은 ‘이미지 연결 검증 표본’에서 연다. 문단·표·이미지 순서, 반복 사용, 미취득 안내를 표시한다.
- HTML은 태그·속성 allowlist와 escape를 거친 열람 표현으로 만든다. script·event handler·외부 링크/asset 실행을 제거하고 sandbox iframe과 CSP로 격리한다. 원문은 덮어쓰지 않는다.
- 이미지 파일은 `/api/reader/{manifest_hash}/images/{occurrence}`에서 제공한다. source URL이나 개발 PC 절대 파일 경로를 브라우저에 직접 연결하지 않는다.
- 검색·본문·표본 목록·이미지 모두 세션을 서버에서 검사하며 private 응답은 no-store다. 쿠키는 HttpOnly/SameSite=Strict, 8시간 만료이며 HTTPS origin에서는 Secure다. 로그인/로그아웃 POST의 Origin을 WEB_ORIGIN과 대조한다. HTTP origin은 loopback 개발 주소만 허용한다.
- 로그아웃과 세션 만료 시 본문·검색 결과를 비운다. 늦은 본문 응답은 다른 선택을 덮어쓰지 않는다. 본문 선택은 URL에 manifest hash 또는 행+본문 hash로 남아 새로고침·로그인 후 같은 버전을 다시 연다.

회원가입·AWS 배포·기존 사용자 자동 seed는 추가하지 않았다. 이번 로그인 연결은 로컬 검증을 위한 최소 경로이며 운영 배포 전 로그인 시도 제한, HTTPS reverse proxy와 WEB_ORIGIN 등 운영 설정은 별도 검증해야 한다.

## 재현

WSL의 저장소 루트에서 실행한다. 아래 DSN은 기존 loopback 개발 DB 예시다. 운영 DB에 표본·검증 계정을 자동 주입하지 않는다.

```bash
export DATABASE_URL='postgresql://korcounsel:korcounsel_local_only@127.0.0.1:55432/korcounsel_dev'
export DATA_DIR="$PWD/data"
export LEGACY_PARQUET_PATH="$PWD/data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet"
export WEB_ORIGIN='http://127.0.0.1:5173'
export UV_PROJECT_ENVIRONMENT="$PWD/backend/.venv-reader"
uv sync --directory backend --frozen
uv run --directory backend python ../scripts/stage_reader_samples.py \
  ../data/image-sample-1955834 ../data/image-sample-1956328 \
  ../data/image-sample-1970841 ../data/image-sample-1955787 \
  --report ../data/reader-samples-20260911.json
uv run --directory backend klegal ops create-account <사용할아이디>
uv run --directory backend uvicorn klegal_gold.web.app:app --host 127.0.0.1 --port 8000
# 별도 터미널, 저장소 루트
pnpm dev
```

create-account는 비밀번호를 숨긴 입력으로 받는다. 이미 발급한 계정이면 재생성하지 않는다. 이번 브라우저 테스트는 임의 비밀번호를 가진 격리 schema의 계정을 사용하고 종료 시 해당 schema를 정리한다. 사용자 운영 계정을 생성·변경하지 않았다. 기존 Docker worker는 이전 단계에서 중지한 상태이며 이번 UI 검증은 worker 재기동이나 AWS 변경을 하지 않는다.

브라우저 검사:

```bash
KLEGAL_TEST_DATABASE_URL="$DATABASE_URL" backend/.venv-reader/bin/python scripts/test_reader_browser.py
```

이 검사는 위 실제 sample manifest가 개발 DB/data 저장소에 있어야 한다. 테스트 서버는 loopback DB만 허용하고 5173/8000을 사용한다. 원 source 사이트 요청을 모두 차단하여 저장 이미지의 독립 표시를 검증한다. 캡처는 `test-results/reader-real-desktop.png`, `reader-real-mobile.png`다.

## 검증과 한계

- Python ruff check/format·mypy 통과, 실제 PostgreSQL을 포함한 전체 회귀 315개 통과. 기존 migration 0009/0010 추가에 맞춰 이전 테스트의 migration 기대 목록을 갱신했다.
- 실제 브라우저 desktop/mobile 4개 통과, 프런트 typecheck/lint/build 통과. Node 테스트 타입을 위해 @types/node 24.13.4를 개발 의존성과 lockfile에 고정했다. 저장 이미지 decode(naturalWidth), 반복 등장, 실패 위치, 외부 요청 0건, Parquet 본문 열람, 새로고침, 로그아웃 및 만료 후 차단을 검사한다.
- 합성 회귀: 비BMP 문자 앞의 HTML 위치, 표 안 이미지, 같은 이미지 반복, 원문 hash 변경, 위험 HTML 15종, 실패·미확정 상태, 직접 비인증 API 호출을 검사한다.
- 현재 portal 이미지 URL 허용 조건도 실제 observe_html이 생성하는 pgmId/jisCntntsSrno/atchImgFileNm으로 정정했다. 이전 문서의 `?name=...`는 잘못된 설명이었다. img의 name은 본문 내부 매핑 이름이고 다운로드 query 이름과 다르다.
- 전수 8,418개 URL의 취득·과거 본문 연결은 미완료다. 다음은 과거/현재 본문 동일성·이미지 매핑 근거를 확인하여 legacy occurrence별 manifest를 만들고 worker와 연결하는 것이다.
- 원 페이지와 pixel 단위 동일한 배치까지 보장하지 않는다. 안전한 문단·표 구조와 이미지 순서를 보존하며 임의 CSS와 외부 코드 실행은 제거한다. OCR은 수행하지 않았다.

