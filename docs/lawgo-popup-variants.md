# lawgo 날짜 지정 팝업 — 2026-09-14

## 관찰과 선택

기존 보존 frame 6개에는 fncLawPop JO/prec 링크 38개만 있었다. 기존 corpus에서 별표 언급 판례 5건의 보존 lawgo ID를 골라 현재 frame을 추가 관찰했다(149165, 149168, 149179, 148843, 148846). 이 중 4건에서 precYYYYMMDD 형식의 날짜 지정 링크를 확인했다. 공식 페이지가 참조한 /LSW/js/ls/lsLink.js의 fncLawPop 및 joInfoShow는 plain prec에만 판례 날짜를 붙이고, 이미 지정된 날짜는 유지하며 efYd에 전달한다.

공식 스크립트 원본은 lawgo-popup-audit:ls/lsLink.js, lawgo-popup-audit:prec/precSc.js, lawgo-popup-audit:ls/lsPopLayer.js에 보존했다. 추가 frame은 popup-audit-20260914:{lawgo_id}이다. 관찰하지 않은 별표·조약 등 호출을 임의로 지원하지 않는다.

## 구현

current-lawgo-2는 정확한 네 인자 JO 호출의 prec 또는 prec+유효한 달력 날짜만 허용한다. provider_context와 실제 provider_request를 조문 manifest에 저장한다. plain prec의 요청 날짜는 기존처럼 판례 frame 날짜이며, 날짜 지정 링크는 명시된 날짜를 그대로 보존한다. 법령명·조문 번호는 제공자 호출에서만 얻으며 원문 인용을 독자 해석하지 않는다.

같은 인용 문구에 연결된 법령명·조문 번호가 같아도 제공 날짜가 다르면 AMBIGUOUS로 남기고 요청하지 않는다. 잘못된 날짜·다른 namespace·추가 실행 코드는 요청 대상에서 제외한다. 기존 immutable plan에 provider_context가 없으면 plain prec 계약으로 읽는다. 이미 보존된 조문 payload를 덮어쓰거나 이전 reader를 수정하지 않는다. 명시된 요청 날짜가 있어도 판례 적용 법령 버전을 검증 완료했다고 표시하지 않으며 UNVERIFIED를 유지한다.

## 실제 로컬 검증

2010두9976(대법원 2011. 3. 10. 선고)의 scourt 2062733, lawgo 149165를 사용했다. 관리자 inventory 한 페이지에서 4개 ID를 관찰하고 기존 source 연결을 대조해 목표 1개 ID만 명시적으로 재수집했다.

- inventory job: 071d0f09-ba43-4efc-a9c6-a78748d1fc04
- detail job: 264180e3-deca-41ce-9b9e-c019c881bc1b
- lawgo job: 174e2fd5-8ef9-47a7-8d5d-2acfd16c5aae
- 원 reader: 057e8a583cbc778af322fa7d8ae8778da1a065d487e9ffa994b3ffe6d3fce931
- 보강 reader: 2afc6f9a029d2fea537a12bc4dcbac467308904fbce4c986623b5dd7917c6868

날짜 지정 조문 위치 8·14·18은 efYd=20100514, lsId=prec20100514로 요청·보존됐다. 선고일 20110310으로 바꾸지 않았다. 전체 조문 26곳 중 PRESERVED 24·UNLINKED 2이며 원문 HTML hash는 그대로다. 인증된 일반 /api/cases/search가 CURRENT_SOURCE 최신 revision 1건을 반환했고 실제 reader HTML의 해당 조문 위치와 법령 내용, 요청 artifact의 날짜를 확인했다. 미인증 검색·본문 401을 검증했다. 증거는 data/popup-date-live-20260914.json, data/popup-date-verified-20260914.json이다.

이번 브라우저 자동화는 Windows sandbox setup refresh 오류로 초기화와 재연결 모두 실패했다. 따라서 실제 브라우저 육안 검증은 미실행이며 API/반환 HTML 검증과 구분한다. 중지된 기존 로컬 DB/API/web은 기존 컨테이너 그대로 재시작했다. 로컬 CORS에는 실행 환경으로만 WEB_ORIGIN=http://127.0.0.1:8080을 주입했다. 환경파일과 기존 raw/manifest는 수정하지 않았다.

## 회귀와 남은 범위

Python/PostgreSQL 723개 회귀와 ruff check/format·mypy를 통과했다. 날짜 유지·legacy plan 호환·잘못된 날짜·namespace 거부·동일 조문 날짜 충돌의 요청 차단·원문 불변을 검증했다. 본 작업은 관찰된 날짜 지정 JO 형식에 한정한다. 별표·서식·조약 등 다른 분기는 실제 판례 연결 표본과 취득/표시 계약을 확인하기 전까지 미지원이며, 문구 불일치는 미연결로 남긴다. 자동 schedule·commit/push·AWS 변경은 하지 않았다.


## 미연결 두 위치 조사 — 2026-09-14 후속

최종 reader의 article_order 23(공정거래법 제23조 제1항 제5호)과 25(구 공정거래법 시행령 … 제36조 제1항)를 저장된 lawgo frame에 대조했다. 두 문구는 ‘상고이유 제2점에 관한 판단’ 아래 밑줄 본문에서 일반 텍스트로 제공되며 해당 위치를 감싸는 a 태그가 없다. 날짜 지정 팝업을 잘못 파싱해서 생긴 누락이 아니다.

다른 위치에는 법령 전체 명칭의 제공 링크가 있지만, 두 약칭 문구와 정확히 일치하는 제공 링크는 없다. 앱이 약칭을 해석하거나 다른 위치의 조문을 추정 연결하지 않는 계약에 따라 두 위치의 UNLINKED를 유지한다. 이 판단은 해당 보존 frame에 대한 조사이며 법령 전체의 제공 여부나 향후 제공자 변경을 단정하지 않는다. 이미 문구가 같은 ‘제2항’ 등 다른 참조의 연결 정책을 이 조사만으로 확대하지 않았다.

감사 artifact는 lawgo-link-audit:9b7001c11acd945280f874aaa384c843eef02c0741acb2d5196c1d6af517ef81이다. 부모 frame artifact·SHA-256, reader reference ID, scourt HTML 위치, provider HTML 위치, KEEP_UNLINKED 판단을 별도 immutable artifact에 보존했다. 파일 증거는 data/lawgo-unlinked-audit-20260914.json이다. source/reader/payload는 변경하지 않았고 외부 조문을 추가 요청하지 않았다.

브라우저 런타임을 초기화해 재시도했으나 Windows sandbox setup refresh 오류로 실패했다. 브라우저 검색→본문 육안 검증은 여전히 미실행이다. 이번 단계는 데이터 감사와 문서 갱신이며 앱 코드 변경·회귀 재실행은 없다. 이전 전체 723개 회귀 통과 기록을 이번 재실행으로 표현하지 않는다.


## 실제 브라우저 검증 완료 — 2026-09-14 WSL 후속

Windows 내장 브라우저 대신 저장소에 설치된 Playwright와 WSL Chromium 153.0.8010.12를 사용했다. 중지된 기존 PostgreSQL·API·web 컨테이너를 재시작하고 worker 정상 복귀를 확인했다. 컨테이너 재생성·환경파일 변경·신규 수집은 하지 않았다.

관리자 로그인 → 일반 검색 `2010두9976` → 현재 수집 결과 1건 → 위 보강 reader 열기를 실제 브라우저에서 검증했다. 조문 26곳 중 보강 내용 보존 24곳, 미연결 2곳을 확인했다. 날짜 지정 위치 8·14·18에는 2010. 5. 14. 제공 내용과 적용 버전 미확인 안내가 표시된다. 위치 23·25(화면 번호 24·26)는 미연결 안내를 유지하며 원문 인용 클릭으로 해당 보강 위치에 이동하고 돌아가기 링크로 원래 인용에 복귀한다. 각 화면을 캡처해 육안 확인했다.

새로고침 후 동일 reader 복원, 로그아웃 후 iframe 제거, 미인증 검색·reader HTML 401을 검증했다. 외부 호스트 요청을 차단한 브라우저에서 외부 요청 0건이었다. 이번 단계는 브라우저 실증·문서 갱신이며 앱 코드와 raw/reader manifest는 변경하지 않았다. 전체 723개 회귀는 앞선 실행 기록이며 이번에 재실행하지 않았다.

검증 JSON과 세 화면 캡처는 로컬 `data/browser-verification-20260914/`에 보존했다. 앱 내장 브라우저·이미지 도구의 복구 완료를 뜻하지 않으며, Chromium과 이미지 bytes 전달을 통한 대체 검증이다.


## 별표 링크 추가 표본 조사 — 2026-09-14

기존 검색 projection에서 별표 언급 행 30개를 원래 ordinal 순으로 읽고, 앞선 5개 lawgo ID를 제외한 서로 다른 공식 ID 5개를 선택했다. 최신 판례나 전수 대표 표본은 아니며 모두 2011년 선고 자료다. 각 현재 precInfoP frame 1회만 요청해 원본 응답과 SHA-256을 immutable artifact로 보존했다. frame 내부 precSeq와 선고일 구조를 검증했고 저장 hash를 재대조했다.

| 판례 | lawgo ID | 별표 언급 | 기존 지원 JO 링크 | 별표 문구 링크 |
| --- | --- | ---: | ---: | ---: |
| 대전지법 2010노2883 | 158613 | 4 | 5 | 0 |
| 서울중앙지법 2009가합120387 | 200574 | 4 | 22 | 0 |
| 서울고법 2010누8326 | 168531 | 7 | 31 | 0 |
| 서울고법 2010누27969 | 148889 | 2 | 12 | 0 |
| 서울행정법원 2010구합37674 | 167602 | 2 | 2 | 0 |

별표 언급 수는 script/style/comment를 제외한 frame 텍스트 기준이며 판례 본문만의 정밀 occurrence 집계는 아니다. a 태그의 표시 문구에 별표·별지·서식이 포함된 링크는 0개였고, a 태그 속성의 fncLawPop 호출은 모두 JO 분기였다. 72개 JO 링크는 기존 지원 형식이며 별표의 실제 연결을 의미하지 않는다. 별표와 인접한 조문 링크를 별표 취득 근거로 확대하지 않았다.

원본 frame ID는 `annex-link-audit-20260914:frame:<lawgo ID>`이며 최종 감사 artifact는 `annex-link-audit:7e2f027341048426929904bf376346708735fe690e432d5d70ccc345219bfc93`이다. 최초 감사에서 script 주석의 ‘별표’까지 집계된 부분을 새 파생 감사 revision에서 제외했고 최초 감사도 보존했다. 추가 네트워크 요청 없이 검증했다.

이 범위에서는 구현할 별표 제공 링크가 확인되지 않았으므로 앱 코드·reader·원문은 변경하지 않았다. 별표 URL 추정, 별표/법령 API 요청, 신규 보강 job 등록도 하지 않았다. 조약·서식이나 현재 전체 lawgo의 미제공을 결론내리지 않는다. 다음 확대 조사가 필요하다면 더 최근 선고연도의 별표 언급 표본을 별도로 선정한다. Python/프런트 변경이 없어 전체 회귀는 재실행하지 않았고 문서 diff 검사를 수행했다.
