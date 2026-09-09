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
