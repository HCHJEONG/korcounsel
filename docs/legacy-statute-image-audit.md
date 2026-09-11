# 보존 조문 내부 이미지 전수 점검 — 2026-09-11

기본 본문의 img 태그 목록과 별도로, 89,130행의 lawgo jtable payload를 전수 점검했다. 조문 내용 안에도 실제 이미지가 있으므로 기본 본문만의 이미지 목록으로 전체 보강 열람 범위를 설명할 수 없다.

## 결과

| 항목 | 전수 결과 |
| --- | ---: |
| 원래 corpus 행 | 89,130 |
| 조문 인용 위치 | 1,641,768 |
| 비어 있지 않은 payload 등장 | 727,972 |
| 고유 nonempty payload | 136,853 |
| 실제 img가 있는 고유 payload | 626 |
| 해당 payload 내부 img 위치 합계 | 1,087 |
| 이미지 있는 조문을 보유한 판례 | 651 |
| 이미지 있는 payload의 부모 인용 위치 | 2,550 |
| 본문 인용별 반복을 포함한 이미지 등장 | 4,698 |
| 고유 해석 URL | 480 |

480개 URL의 host는 모두 www.law.go.kr이다. img src 결측과 srcset은 0이었다. SVG/image/picture/source, CSS url/background, object/embed/iframe 관련 표식도 검사했으며 별도 참조 후보 없이 실제 img만 관측됐다. 이는 정적 HTML 참조 점검이며 취득 성공을 뜻하지 않는다.

원본 Parquet 1,215,542,924 bytes의 점검 전후 SHA-256은 모두 `3fa3a55e5d126e2f2d413c2a6cb1ab2215e135197533899f6c981d54c4d586e2`였다. 4개 spawn 프로세스로 104.8초 동안 분석했으며 원본 파일·DB·제공자 상태를 변경하거나 다운로드하지 않았다.

전체 위치 결과는 `data/legacy-statute-image-audit-20260911.json`에 보존했다. 결과 파일 SHA-256은 `d65cc919a4174b59916937e82d5791422fe447ce66214bc3753f96207215a196`이다. payload hash와 원래 판례 position, 부모 HTML hash, 조문 인용 order·tag offset, payload 내 img tag·src·위치·문맥을 함께 기록한다.

## 실제 사례

- 57행, 대법원 2011. 2. 24. 선고 2007두21587 판결: 구 법인세법 제55조 payload에 /flDownload.do?flSeq=6238586, 6238603 이미지가 있고 인용 34·37·38에 반복된다.
- 124행, 서울고등법원 2011. 2. 15. 선고 2009누41099 판결: 지방세법 시행령 제101조 payload에 /flDownload.do?flSeq=4667901 이미지가 있다. ‘지역별 적용배율은 다음과 같다’ 뒤에 이미지가 배치되며 인용 1·3·8·9·11·13에 반복된다. 이미지 내용을 OCR하거나 표로 해석한 결과는 아니다.

현재 reader는 이 이미지들을 미확보 위치로 표시한다. 완전한 보강 열람을 위해서는 조문 payload를 부모로 하는 별도 이미지 취득·manifest·반복 위치 연결을 후속 revision으로 반영해야 한다. 새 조문을 독자 추론하여 보강하는 작업과 구분한다. 이미 보존한 제공자 조문 안의 이미지 참조를 계승하는 범위다.

## 제공자 표식은 의미를 유지

alert_img_01.png의 0·1·3행 원태그는 alt ‘위헌조문 표시’를 가진다. 참조조문 바로 뒤에 위치한다.

추가로 `data/legacy-flag-image-context-20260911.json`에 다음 원문 3건의 정확한 img 태그·offset·앞뒤 500자·부모 hash를 보존했다.

| 이미지 | 원래 alt | 실제 위치 |
| --- | --- | --- |
| flag_01.gif | 폐지 | 557행 광주고법 2010나110, 본문 참조판례 96다14661 뒤 |
| flag_01.gif | 폐지 | 6594행 대법원 2008도7143, 원심판결 2008노577 앞 |
| flag_03.gif | 변경 | 160행 대법원 2010후2698, 참조판례 2007후1053 뒤 |

이 파일들을 UI 표식으로 분류하더라도 의미 있는 원래 표시를 삭제하거나 숨기지 않는다. 과거 제공자 표식과 alt를 보존하며, 현재 판례·법령 상태를 새로 확인한 결과로 표시하지 않는다. 실제 분류 변경·삭제는 이 점검에서 수행하지 않았다.

## 도구와 검증

`scripts/audit_legacy_statute_images.py`는 statute_occurrences를 재사용하며 payload SHA-256별로 중복 검사한다. 보수적인 문자열 guard 이후 image_occurrences와 별도 정적 시각 참조 parser로 위치를 기록한다. 모든 부모 인용 위치를 남기고 기존 결과 파일을 덮어쓰지 않는다.

탐지 fixture 2개에서 대문자 img, srcset, SVG image, picture/source, entity가 들어간 CSS url, style URL 및 같은 payload의 여러 부모 위치 보존을 검증했다. ruff 검사도 통과했다.
