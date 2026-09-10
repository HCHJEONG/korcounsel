# Provenance와 재현성 계약

2026-09-09 추가 지시 반영. 원본과 파생 결과, source identity와 canonical identity를 구분한다.

- 원본 바이트 SHA-256과 source_system/source_document_id, 취득 UTC 시각, credential 없는 source URL, parser/normalizer/schema/dataset version을 보존한다.
- source 간 연결은 후보 metadata versions, 결정 신호·사유·점수·resolver version과 identity link revision으로 추적한다. canonical 필드마다 어느 source에서 왔는지 남긴다.
- source raw, 렌더링 DOM snapshot, 추출 텍스트, 보강 HTML, normalized 결과를 서로 다른 artifact로 식별한다. 렌더링 DOM을 서버 응답 원본이라고 부르지 않는다.
- 같은 source ID의 새 raw hash는 이전 원문을 덮어쓰지 않는다. inventory metadata 변화와 source body 변화는 별도 관찰이다.
- Text evidence는 특정 artifact/field의 Python Unicode code point [start,end) 기준이다. source_text[start:end] == evidence.text를 검사한다. JSON/XML byte offset·DOM locator·PDF 좌표·JavaScript UTF-16 인덱스를 혼용하지 않는다.
- 시각자료는 original reference, 부모 artifact, block/order/page·실제 취득 artifact hash로 연결한다. 이미지에 text offset을 억지로 부여하지 않는다. OCR은 향후 별도 derived artifact와 engine/version·부모 scan을 기록한다.
- asset 다운로드 실패·source disappearance·metadata 충돌은 삭제가 아니라 상태/이벤트다. source가 제공하지 않은 필드와 파싱 실패를 구분한다.
- dataset release는 input inventories와 completeness/scope, source versions, canonical registry/link snapshot, asset manifest, 코드·설정·규칙 versions와 출력 checksum을 고정한다. 이후 merge/split/refresh가 과거 release를 바꾸지 않는다.
- source/identity/artifact 변경 시 이전 사람 승인을 자동 승계하지 않는다. review는 정확한 issue revision과 evidence를 참조한다.

공개 manifest에는 비밀값이 있는 URL·env·session을 넣지 않는다. 원본이 credential을 포함하면 격리된 저장 정책과 redacted 파생본을 분리하며 변조된 raw를 원본이라고 보고하지 않는다. 최초 Step 0 smoke의 저장 범위 예외는 [API 메모](law-open-api-contract.md)에 남아 있다.


## 기존 corpus의 provenance — 2026-09-10

최종 pickle의 snapshot SHA-256, 원래 행 index/position, 필드명과 기존 공식 ID를 유지한다. 분석 projection은 원본의 대체물이 아니며 snapshot hash에 연결한다. `folder_file_name`의 과거 절대경로는 원래 locator로 보존하되 현재 파일 존재·원래 취득시각을 증명하지 않는다.

`case_txt_scraped_with_tags`도 레거시 조문/이미지 보강을 거친 저장 문자열일 수 있다. 이를 과거 서버의 원본 HTTP bytes로 다시 이름 붙이지 않는다. 기존 필드 그대로 보존한 legacy artifact와 새 API response artifact를 구분하고, 이번 import 시각을 역사적 수집 시각으로 기록하지 않는다. 역사적 raw hash가 없으면 없는 것으로 유지한다. 0/empty/parser 객체 등 원래 값은 원 archive에 남기고 mapper의 변환/결측 사유를 별도로 남긴다.

현재 domain 0.1.0의 일반 source Provenance는 과거 취득시각·URL·raw hash를 아는 흐름의 초안이다. legacy artifact origin/unknown acquisition을 표현하는 import 계약을 완성하기 전, 기존 89,130행을 이 schema에 맞추려고 가짜 값을 채우지 않는다. 이 보완은 Step 2 완료의 선행 조건이다.

새 issue content revision은 내용·출처 버전·evidence·규칙으로 계산하며 run/release metadata를 제외한다. registry/link revision은 별도로 고정한다. 자동 검증과 사람의 검토는 둘 다 정확한 issue 및 link revision을 참조한다.

## 출처를 결합한 보강 결과

기존 corpus는 scourt 기본 본문에 lawgo 조문 표를 붙인 보강 표현을 포함한다. import에서 이 가치를 보존하며 출처·취득/법령 버전 미확인을 함께 기록한다. 이후 보강은 scourt 부모 artifact/hash·원래 조문 링크/위치, lawgo 판례일련번호·조문 artifact/version 및 보강 규칙을 연결한다. base 원문과 보강 결과를 덮어 합치지 않는다. 세부 사항은 [계승 전략](legacy-enrichment-and-incremental.md)을 따른다.
