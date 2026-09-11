# 전수 reader 확대 독립 점검 — 2026-09-11

**후속 전수 확인:** 조문 payload 안의 추가 이미지 4,698개 등장 위치(651판례·480URL)를 확인하고 모두 취득·연결했다. 473개 고유 이미지 bytes의 decode와 전체 위치·hash 검증도 통과했다. 아래의 미확인 표시는 후속 점검 전 상태다. [조문 이미지 전수 결과](legacy-statute-image-audit.md)를 우선한다.

전수 목록과 실제 보존 HTML을 읽어 검증했다. 아래 렌더링 점검은 PostgreSQL에 저장하지 않는 capture adapter로 수행했으며 실제 브라우저 검증과 구분한다.

## 집계 해석

- 89,130행의 기본 HTML은 합계 2,741,923,197문자다.
- 조문 등장 1,641,768곳의 payload 합계는 1,424,284,025문자다. 비어 있지 않은 고유 payload는 136,853개이며 정상 표 136,850개와 실패 표식 3개다. 고유 payload 합계는 268,400,061문자다.
- 새 HTML artifact와 reader manifest를 각각 행마다 보존하고 고유 조문 payload를 분리하면, 기존 저장·행간 HTML 중복·배치 manifest를 제외한 기본 artifact 수의 상한은 315,113개다. 디스크 용량은 UTF-8·JSON encoding·manifest 내부 반복과 기존 CAS 공유를 포함해 실제 저장 후 측정해야 한다.
- 전수 기본 HTML 관측의 hidden image 수는 0이다. 이는 저장 HTML에 대한 파서 관측이다.
- table 안 BODY image 0은 원래 기본 HTML에서 table 열림/닫힘 영역 안의 img 태그 수다. jtable 속성에 보관된 조문 HTML 내부 이미지, PDF/스캔 이미지에 그려진 표, 원제공자의 다른 representation까지 없다는 뜻이 아니다. 해당 범위를 전수 취득·표본 브라우저 완료로 표현하지 않는다.
- 현재 renderer는 조문 payload 안에 img가 있으면 미확보 위치로 표시하지만, 해당 img를 별도 취득 ledger에 연결하는 단계는 없다. 전수 payload 내부 이미지 수는 이 점검에서 확인하지 않았다.

## 실제 확대 표본의 렌더링 점검

각 표본에서 생성한 citation ID와 statute section ID 집합이 정확히 같았고, 출력된 script/iframe/object 태그는 없었다. 확보하지 않은 이미지에는 외부 URL을 사용하지 않고 미확보 상태가 표시됐다.

| position | 사례 | 원문 bytes | reader manifest bytes | 조문 section 수 | 파싱·직렬화 시간 |
| --- | --- | ---: | ---: | ---: | ---: |
| 3977 | 서울고등법원 2018누52497 | 457,965 | 610,880 | 131 | 0.176초 |
| 4374 | 서울남부지방법원 2008가합21038 | 137,971 | 128,090 | 24 | 0.056초 |
| 5300 | 서울중앙지방법원 2019고합738 | 2,022,179 | 2,103,895 | 305 | 0.638초 |
| 6429 | 중앙해양안전심판원 2008중해심26 | 345,583 | 239,616 | 31 | 0.108초 |
| 16634 | 서울중앙지방법원 2017고합1008 | 3,736,106 | 3,959,976 | 1,115 | 1.328초 |
| 39923 | 서울고등법원 2021노345 | 2,196,177 | 2,224,077 | 521 | 0.801초 |

위 시간에는 PostgreSQL·파일 저장·브라우저 DOM 구성 비용이 포함되지 않는다. 표본 16634는 전수 목록에서 가장 긴 기본 HTML이며 2,225,813문자, 원문 표 26개다. 보강 후 원문 표와 조문 표를 합쳐 440개 table이 렌더링됐다.

8건 외의 확대 브라우저 표본으로 4374(표 6개·이미지 5곳·과거 조문 실패 2곳), 3977(표 16개·이미지 4곳·과거 조문 실패 36곳), 16634(최대 길이·1,115개 조문 이동 대상)를 권고한다. 표 안의 이미지 사례로 제시하는 표본은 아니다.

## 버전과 보존 경계

현재 reader manifest는 원문·이미지 연결·조문 보존 입력과 reader version을 기록하지만, HTML 응답은 현재 renderer 코드로 생성한다. 따라서 동일 revision을 과거의 렌더링 출력 bytes까지 동결한 것으로 설명하지 않는다. 향후 renderer version 변경 시 기존 reader 재사용과 새 revision 생성 기준을 별도로 정해야 한다. 현행 version 2 전수 실행에서 입력·위치 연결 불일치는 발견하지 않았다.

## DB 연결 비용

전수 reader handler 안에서만 Database.reuse_connections()로 thread-local 연결을 재사용한다. 각 connect() 호출의 transaction은 독립적으로 commit/rollback하고, 중첩 connect는 별도 연결을 연다. 다른 API 스레드와 다른 handler는 기존 경계를 유지한다. 실제 PostgreSQL에서 rollback·중첩·스레드 경계와 batch/import/jobs 회귀 33개를 통과했다.

## 전수 worker 성능 확인

공유 corpus DB를 변경하지 않고 별도 테스트 DB·임시 FileStore에 실제 19200~19299행을 등록했다. cProfile 오버헤드를 포함해 7.17초였고 HTML 파싱 누적 2.96초, fsync 1.85초, 전체 artifact 저장 3.29초였다(누적 항목은 서로 겹친다). 필요한 원문 파싱·원자적 저장·hash 검증을 생략하지 않았다. 조문 이미지 4,698등장은 행별 고유 URL로 1,460개이므로 향후 재보강에서 검증을 유지한 decode 재사용은 검토할 수 있으나 이번에는 추가하지 않았다.
## 일반 검색과 실제 브라우저 검증

실제 저장 corpus를 대상으로 `playwright.reader.config.ts`의 desktop Chrome과 mobile Chromium(iPhone 13 viewport)에서 검증했다. 인증·세션 기록은 `korcounsel_test`의 매 실행 고유 schema에 만들고 종료 시 해당 schema만 제거한다. 판례·reader·이미지는 별도 `korcounsel_dev` 연결로 읽되 매 transaction에 `SET TRANSACTION READ ONLY`를 적용한다. 계정과 비밀번호는 테스트 실행 시 생성하며 실제 운영 계정을 재사용하지 않는다.

첫 통합 실행은 22개 검사를 4.3분에 통과했다. 기존 저장 이미지의 반복 위치·실패 표시, 일반 검색의 scourt 이미지·lawgo 조문, 직접 URL과 고정 revision 재열기, 관리자·편집자 인증 및 세션 만료를 포함한다. 이후 검증 표본 목록을 기본 접힘 `details/summary`로 바꾼 뒤 영향받는 desktop/mobile 10개 검사가 1.3분에 통과했다. 기본 접힘, 표본 버튼으로 본문 열기, 빈 목록 안내, Enter 키로 펼침/접힘을 확인했다. 이 실행 수는 서로 겹치는 회귀 실행이며 32개의 서로 다른 시나리오를 의미하지 않는다.

법제처 조문 내부 이미지는 다음 두 판례를 일반 검색해 확인했다. 표본 전용 URL에서만 확인한 결과가 아니다.

| 검색 사건번호 | corpus position | 원래 조문 위치의 이미지 연결 |
| --- | ---: | --- |
| 2007두21587 | 57 | article 34·37·38 각각 image 0·1, 총 6곳 |
| 2009누41099 | 124 | article 1·3·8·9·11·13 각각 image 0, 총 6곳 |

두 경우 모두 원래 인용→조문 이동과 돌아가기, 보존 표 안 이미지 표시·decode, 반복 위치별 내부 인증 URL, 적용 버전 미확인 표시, 새로고침 후 같은 revision을 확인했다. 브라우저의 외부 제공자 요청은 0건이었고, 로그인한 이미지 요청은 200, 로그아웃 후 동일 이미지 요청은 401이었다. 전체 문서의 가로 넘침은 없었다. 실제 이미지 3개 URL 취득 검증과 651판례 전수 취득·연결 집계는 [조문 이미지 전수 결과](legacy-statute-image-audit.md)와 구분한다.

## 대규모 파일 저장 중 개발 서버 지연

후속 브라우저 실행에서 로그인 전 단계가 지연됐다. 같은 시점에 API 직접 요청(8000)은 health 8ms·미인증 session 2ms로 정상 응답했지만, Vite 프록시(5173)를 통한 같은 두 요청은 각각 10초 timeout이었다. 테스트 DB에는 대기 연결이 없었고, Vite 프로세스는 inotify 감시 443,764개를 유지했다.

`vite.config.ts`에서 프런트 갱신과 무관한 `data`, `backend`, `.fordeploy`, `test-results`, `playwright-report`를 파일 감시 대상에서 제외했다. 변경 후 감시는 181개로 줄었고 Vite 프록시 health/session은 각각 7ms/4ms로 응답했다(API 직접 요청은 11ms/4ms). 프런트 `src`와 설정 파일 감시는 유지한다. 측정은 전체 corpus worker가 실행 중인 같은 로컬 환경에서 이뤄졌다.

로그인 대기 시간을 늘리는 임시 접근은 제거하고 기존 클릭 후 5초 화면 표시 기준으로 되돌린 상태에서 위 10개 검사를 통과했다. 타입 검사·lint·production build도 통과했다. 지연을 경험한 중간 실행을 성공 검사 수에 포함하지 않았다. 비밀값 없는 측정 결과는 `data/legacy-reader-scale-20260911-v1/browser/vite-watch-performance.json`에 보존했다.

## 최종 화면 확인

스크린샷에서 좁은 모바일 검색 표가 열을 한 글자씩 줄바꿈하는 문제가 보여 기존 가로 스크롤 컨테이너 안의 표에 720px 최소 너비를 적용했다. 보완 후 두 법제처 판례의 desktop/mobile 4개 검사를 다시 실행해 1.1분에 통과했고, 타입 검사·lint·build도 재통과했다. 기본 접힘 이후 10개 실행과 최종 표 너비 보완 이후 4개 실행은 겹치는 영향 회귀다.

최종 desktop/mobile 전체 화면과 조문 본문 이미지를 직접 확인했다. 접힌 표본 목록 다음에 본문이 이어지고, 보존된 세율표·용도지역별 적용배율 이미지가 조문 안의 원래 위치에 보인다. 모바일 검색 표는 영역 안에서 가로로 스크롤하며 페이지 전체를 옆으로 밀지 않는다. 브라우저 스크린샷은 `data/legacy-reader-scale-20260911-v1/browser/`에 보존했다.

- `lawgo-statute-image-2007두21587-desktop.png`, `lawgo-statute-image-2007두21587-mobile.png`: 검색→접힌 표본 목록→법인세법 조문 이미지 전체 화면.
- `lawgo-statute-image-2009누41099-desktop.png`, `lawgo-statute-image-2009누41099-mobile.png`: 검색→지방세법 시행령 조문 이미지 전체 화면.
- 같은 위치의 `lawgo-statute-detail-…` 파일 4개: iframe 본문 상세 화면.
- `before-result-table-width/`: 최종 표 너비 보완 전 화면.

이 브라우저 표본 성공은 모든 판례의 시각 검수가 완료됐다는 의미가 아니다. 전수 위치·hash·상태 집계와 실제 브라우저의 선정 표본 검증을 함께 사용한다.

## 개발 서버 정적 파일 접근 경계

Vite 파일 감시 제외는 HTTP 파일 접근 차단을 뜻하지 않는다. 후속 점검에서 비민감 감사 파일 `/data/legacy-reader-scale-20260911-v1/statute-image-all-download.json`을 인증 없이 요청했을 때 200과 원파일 그대로의 437bytes를 확인했다. 실제 환경파일·비밀파일을 HTTP로 요청하지 않았다.

설치된 Vite 8.2.2 코드의 기본 `server.fs.deny` 6개 패턴을 확인해 유지하고, `data`, `backend`, `.fordeploy`, `test-results`, `playwright-report` 아래를 추가로 차단했다. 원본·이미지는 인증된 FastAPI `/api` 경로에서 제공하며 Vite의 정적 파일 경로로 제공하지 않는다.

수정 뒤 실제 audit JSON은 403이었다. 5개 폴더에 만든 비민감 임시 canary는 일반 URL과 `/@fs` URL 모두 403, 비밀값 없는 가짜 `.env.*`와 `.key` canary도 두 URL에서 모두 403이었다. `/src/App.tsx`, `/src/styles/global.css`, `/`는 200, `/api/health`는 200, 미인증 `/api/auth/session`은 401로 총 20개 HTTP 검사를 통과했다. 임시 canary는 점검 직후 제거했다. 타입 검사·lint·build도 통과했다.

기록은 `data/legacy-reader-scale-20260911-v1/browser/vite-static-boundary-before.json`과 `vite-static-boundary-after.json`이다. 파일 내용이나 credential은 기록하지 않았다. 이 확인은 로컬 개발 서버의 실제 노출을 수정한 결과이며 AWS 운영 검증으로 간주하지 않는다.
