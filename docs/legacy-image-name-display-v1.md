# 관찰된 이미지 이름 표시 변경

`image-context-link-3`는 과거 `ImageIdN`과 현재 제공자 `imgN`의 표시 차이를 다룬다. 이름 비교 증거는 `image-name-display-1`로 기록한다. 기존 exact 연결 `image-context-link-1`과 제목 표시 대조 연결 `image-context-link-2`는 그대로 유지한다. 제목 규칙 `image-title-display-3`와 이름 규칙은 별개이며 필요한 경우 두 증거를 함께 기록한다.

## 허용 범위

대소문자가 정확히 `ImageId`와 `img`이고, 뒤의 ASCII 십진 숫자 문자열이 동일한 경우만 허용한다. wave 17의 66784·66796행과 wave 18의 68248행에서 선행 0이 있는 `ImageId01`→`img01`도 실제 확인했다. `01`을 `1`로 바꾸지 않고 숫자 문자열 전체를 그대로 대조한다. 숫자 이동, 다른 대소문자·접두어, 역방향 변환, 전각 숫자, 선행 0을 지우는 정규화는 허용하지 않는다.

새 이름 연결은 선언된 두 제목이 같더라도 실제 유일한 현재 h2와 선두의 보이는 원 strong이 각각 해당 제목과 일치해야 한다. 누락·숨김·다중 제목은 보류한다. 정확히 같은 복수 사건번호 제목은 원 헤더가 일치하면 유지하며 단일 사건번호 표시 parser를 강제로 적용하지 않는다.

동일 source ID와 제목 조건, 원 URL의 contId·attachImgNm, 현재 제공자의 파일명 mapping, 양쪽 앞뒤 120자 문맥(각 최소 30자), 후보 유일성·미사용·등장 순서가 모두 기존 조건을 통과해야 한다. 이름이 같은 기존 경로는 변경하지 않는다. 변환한 이름을 원본 HTML이나 ref의 name/src에 덮어쓰지 않는다.

## 실제 근거와 한계

wave 14의 45898행은 source 2104419, `대법원 1996. 10. 11. 선고 95후1944 판결`이다. 기존·현재 reader와 두 HTML의 SHA-256을 직접 확인했다. ImageId0→img0, ImageId1→img1은 파일명과 양쪽 120자 문맥까지 대응하지만 ImageId2→img2는 문맥이 달라 계속 미연결이다.

이름에서 먼저 거절된 위치 수는 안전하게 연결할 수 있는 수의 상한이다. 기존 제목 대조를 통과한 행에 새 구현을 읽기 전용으로 적용하여 다음 후보 수를 독립 재현했다.

| wave | 이름 조건에서 먼저 거절된 위치 | 모든 기존 조건과 새 name span을 통과한 위치 | 해당 행 |
| --- | ---: | ---: | ---: |
| 14 | 571 | 455 | 77 |
| 15 | 220 | 208 | 75 |
| 16 | 별도 감사 참고 | 77 | 19 |
| 17 | 별도 감사 참고 | 182 | 45 |
| 18 | 별도 감사 참고 | 94 | 12 |
| 19 | 신규 후보 없음 | 0 | 0 |

합계 228행/1,016위치이며 원 name 값·tag span과 실제 양쪽 visible 제목 확인까지 포함한 구현으로 직접 재현했다. 이 수는 새로운 실물 취득이나 실제 reader 재적재 완료 건수가 아니다. 제목 v3로 별도 해소되는 행과의 결합 결과는 이 표에 포함하지 않는다. 제목 표시 후보 60행 중 10행에서는 추가로 53위치의 이름 변경이 대응하며, 기존 same-name 123위치와 합쳐 52행/176위치의 연결 근거가 통과한다. 현재 제공자 이미지와 과거 binary의 동일성은 미확인으로 유지한다.

원 감사는 `data/legacy-reader-scale-20260911-v1/image-link-gap-wave{14,15,16,17,18,19}-review.json` 및 `image-name-candidate-wave{14,15,16,17,18,19}-review.json`이다. 이름 후보 감사 SHA-256은 wave 14 `525e9b741bc7a102549ee0e39bd53eb025bb004af06e4200de8ec21b75801a06`, wave 15 `29fc06cd17ccad6184b6000d2f560d7d1716b0ac94fa8d18bfda8d78d1bd59bc`, wave 16 `98adfc15c1495ecf6c3876abf4d6847e16589526bec54754accd0ff103dc0735`다.

## 증거와 재검증

name_comparison에는 양쪽 선언 제목·원 헤더와 제목 hash를 담은 source_title_binding, 두 원 name, 동일 숫자 문자열, 원 tag, 양쪽 HTML hash, reference ID·order, 원문에 대한 name 값과 tag의 위치를 기록한다. 위치 계약은 Python Unicode codepoint `[start,end)`이며 원 HTML slice가 원 name/tag와 일치해야 한다. 같은 tag에 name이 중복되거나 entity를 해석해야만 이름이 맞는 미관찰 표기는 새 변환에서 거절한다.

ReaderStore 저장과 LegacyReaderBatch 재개 검증은 이 새 버전의 연결에 한해 현재 HTML artifact를 다시 읽고 hash를 확인하며 기존 연결 함수로 proof 전체를 재계산한다. name 값, 위치, 참조 또는 나머지 연결 근거가 달라지면 `INVALID_IMAGE_NAME_LINK`로 거절한다. 과거 v1/v2 proof는 원래 계약대로 유지한다.

합성 unit은 동일 숫자·원문 보존·반복 등장과 대소문자/숫자/파일명/문맥/중복/순서/출처의 거절을 다룬다. 전용 PostgreSQL 회귀는 원본과 이전 revision 보존, 제목·이름 규칙의 결합, 변조 proof의 저장 및 재개 검증 거절을 다룬다. wave 19 감사 완료 후 관련 234개 검증의 최종 성공을 확인했고 backend ruff·format107개·mypy55개도 통과했다. 새 이름 규칙의 PG 6개에는 일반 /api/cases/{position}/body→내부 이미지 응답·ACQUIRED 위치의 미연결 오표시 방지 회귀가 포함된다. 자세한 테스트 실행 범위는 [제목 v3 검증](legacy-title-display-v3.md#검증)을 따른다. 실제 corpus DB·worker·다운로드는 이 구현 검증에서 실행하지 않는다.
