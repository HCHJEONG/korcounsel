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
