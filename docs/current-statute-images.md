# 신규 reader의 lawgo 조문 이미지 — 2026-09-14

## 구현 계약

lawgo가 해당 판례에 제공한 조문 popup의 보존 payload에서 이미지를 관찰한다. 원 scourt HTML과 조문 payload를 수정하지 않고 조문 reference/order, payload SHA-256/artifact, 이미지 등장 순서·원 src·resolved URL을 새 reader manifest에 기록한다. 공식 HTTPS flDownload.do?flSeq 주소만 취득 대상으로 허용한다. 다른 주소는 위치와 미확보 상태를 보존한다. 앱이 인용을 해석해 법령 요청을 만들지 않는다.

CurrentLawgo는 조문 내용과 이미지 위치를 먼저 보존한다. worker는 기존 ACQUIRE_IMAGE_BATCH(all_urls)→REFRESH_CURRENT_READER_IMAGES를 연결하고 follow_up_job_id를 UI에 전달한다. 50 URL 단위 checkpoint·ledger와 terminal dependency를 재사용한다. 조문 reader ID를 child 등록 전에 checkpoint에 저장하여 재개 시 같은 파생 revision과 child job을 사용한다. 성공 bytes·실패·대기·시도 이력을 위치별로 연결하고, 이미 보존된 성공 bytes는 계승한다. 이미지 실패가 조문이나 본문 수집 실패를 뜻하지 않는다.

본문 이미지 재취득 명령은 조문 이미지만 있는 CURRENT_SOURCE도 지원한다. 내부 조문 이미지 endpoint는 실제 보강된 parsed_statutes를 기준으로 위치를 검증한다. 최초 scourt HTML의 미보강 링크만으로 검증하면 새 조문 이미지가 거절되는 문제를 수정했다. 적용 법령 버전 미확인 표시는 유지한다.

## 관찰된 기존 ID의 명시적 재수집

관리자 POST /api/admin/deltas/{artifact_id}/scourt-details에 선택 인자 refresh_source_id를 추가했다. 해당 delta에서 NEW/CHANGED/UNCHANGED/LEGACY_KNOWN으로 실제 관찰된 숫자 ID 한 건만 허용한다. 기본 요청은 기존 신규·변경 후보 정책을 유지한다. 목록 밖·부재 ID는 400, 미인증·권한 없는 계정은 기존 인증 정책을 따른다. 이 선택 인자는 관리자 API에 있으며 별도 프런트 선택 UI는 아직 없다. 정기 실행이나 전체 corpus 재수집을 만들지 않는다.

## 실제 로컬 표본

서울행정법원 2010. 10. 21. 선고 2010구합13975 판결. scourt 2138807, lawgo 172290. 판례 frame의 실제 제공 링크에서 상속세 및 증여세법 시행규칙 제10조의2 popup과 flSeq=10099327 이미지를 관찰했다.

- 관리자 inventory: 9c9a4f66-2f65-4daf-aa2d-fd9be74d7ed1. 관찰 2건 모두 LEGACY_KNOWN.
- 선택한 2138807 한 건 상세 재수집: 18b045e6-472e-4b4a-bbd6-b0645266c3d7.
- lawgo: 6b91419b-cf82-4b90-8206-6b8db32318f5, EXACT.
- 이미지: 7a112cd8-ee83-4764-8efd-1ecdf823fe9c. URL 1개·조문 이미지 위치 2개. 기존 검증 bytes 재사용(SKIPPED 1)이며 이번 새 다운로드는 0바이트.
- reader refresh: a8f6f033-bb47-4390-ae37-e48ea1732741.
- 최종 reader: 60ccad0e3ed2896ae793bb598b9f8a665176d1950b48698535b1d9eeac856ed9.

일반 검색→현재 수집 본문에서 조문 11곳 중 10곳 보강, 두 조문 위치(article_order 6/10)의 425×33 이미지 로딩을 확인했다. 내부 이미지 응답은 각각 1,695바이트이고 SHA-256 a8f44e2f482d258edc44bbe760fdf2b4c853d2c0bba4c93fa9ca301553483a09가 ledger와 일치한다. 무인증 이미지 요청 401, 원문 HTML hash 불변을 검증했다. 실행·검증 증거는 data/statute-current-live-20260914.json과 data/statute-current-verified-20260914.json, provider 응답은 statute-live-20260914:frame/:article artifact에 보존한다.

## 회귀와 한계

실제 PostgreSQL 합성 provider popup 시험에 반복 이미지 성공·네트워크 실패·미허용 주소 대기, 이전 revision 불변, 새 조문 이미지 endpoint와 렌더링 검증을 추가했다. 관찰된 기존 ID만 상세 재수집하는 API도 검증했다. 전체 715개 회귀, ruff check/format 및 mypy를 통과했다.

현재 fncLawPop JO 형식에 대한 구현이다. 다른 popup 형식과 연결 문구가 달라 일치하지 않는 조문은 여전히 미연결로 남긴다. 제공자 연결의 추가 형식 대응은 후속 단계다. 실제 표본은 취득된 bytes 재사용이며 제공자에서 새 이미지 bytes를 받는 실증과 구분한다. AWS 변경·환경파일 수정·자동 schedule·commit/push는 하지 않았다.


날짜 지정 JO 팝업(precYYYYMMDD)의 후속 지원과 현재 검증 한계는 [별도 기록](lawgo-popup-variants.md)을 따른다.
