# 기존 89,130행 보강 열람 전수 확대 — 2026-09-11

사용자가 확정한 세 단계 중 첫 단계다. 기존 corpus의 본문·이미지·조문 열람을 완성하고, 그다음 신규·변경 수집, 이후 쟁점·답변·근거 구조화와 검수/GOLD 생산으로 진행한다. 이번 범위는 기존 corpus이며 원문 pickle·corrected Parquet·기존 canonical/검토 이력을 바꾸지 않는다.

## 전수 조사 완료

[기계 판독 집계](legacy-reader-scale-inventory.json)는 실제 89,130행을 모두 읽은 결과다. HTML 파싱 오류 0, 고유 locator 89,130개, Parquet 전후 SHA-256 동일(`3fa3a55e5d126e2f2d413c2a6cb1ab2215e135197533899f6c981d54c4d586e2`). 행별 관찰, 이미지 위치, 조문 위치, 실패 목록과 해시는 `data/legacy-enrichment-inventory-20260911-v1/`에 보존했다.

| 관찰 | 행/위치 수 |
| --- | ---: |
| 전체 행 | 89,130 |
| 이미지 확인 대상 행 | 3,953 |
| 위 대상 중 사용할 scourt ID 없는 행 | 45 |
| 알려진 alert UI 이미지를 제외한 img 위치 | 15,448 |
| alert_img_01.png 위치 | 90,345 |
| 저장 조문 내용이 있는 행 | 84,785 |
| 조문 인용 위치 전체 | 1,641,768 |
| 저장 표 내용이 있는 인용 위치 | 702,035 |
| 과거 보강 실패 표식 위치 | 25,937 |
| 조문 내용이 연결되지 않은 인용 위치 | 913,796 |
| 서로 다른 보존 조문 표 payload | 136,850 |

위 행 분류는 서로 겹친다. 이미지 위치 수는 고유 이미지 파일 수·법적 그림 수가 아니다. alert 외의 분류에는 flag_01/03.gif 표식 4,571위치도 포함된다. 실제 원래 alt는 각각 ‘폐지’·‘변경’이며, alert_img_01.png는 ‘위헌조문 표시’다. 장식으로 간주해 삭제하지 않으며 현재 법률 상태를 확인했다는 뜻으로 해석하지 않는다. 유효 attachImgNm가 있는 원래 다운로드 URL은 기존 조사와 같은 8,418종이다. 원래 URL의 contId와 행의 ID가 다른 위치는 결측을 포함해 451곳/48행이며 자동 연결하지 않는다. src 없는 본문 이미지 17곳/3행도 별도 상태다.

실제 HTML table DOM 안의 img는 전수에서 0개였다. 이는 표 안 이미지의 실물 브라우저 검증을 통과했다는 뜻이 아니다. CSS 배경, PDF·스캔 내부, 조문 payload 속 그림까지 없다고 판단하지 않으며 해당 구조 계약은 합성 회귀와 구분한다.

## 처리와 재개

[배치 계약](legacy-reader-batches.md)에 따라 1~100행 입력을 고정하고 기존 단일 worker가 처리한다. 본문 hash와 snapshot에 맞는 보강 기록, 원래 이미지·조문 위치, 실패 상태를 저장한다. 전수 계획은 892개 배치다. 현재 본문 근거 취득과 이미지 다운로드는 별도 source/image job을 사용한다.

- `scripts/audit_legacy_enrichment.py`: 읽기 전용 전수 목록과 해시 작성. 병렬 분석 결과는 순차 분석과 같은 JSONL 순서를 유지한다.
- `scripts/run_legacy_reader_batches.py plan`: 전체 또는 명시 위치를 hash 고정 입력으로 등록한다.
- `scripts/run_legacy_reader_batches.py run`: 한도 안에서 기존 worker로 실행하고 중단된 자기 작업을 재개한다. 다른 실행 중 작업을 대신 처리하지 않는다.
- `scripts/run_legacy_image_waves.py`: [source ID별 100건 실행·재개](legacy-image-waves.md)로 현재 근거→이미지 취득→본문 연결을 이어서 실행한다.
- `scripts/prepare_legacy_image_sources.py`: 이미지 대상 판례의 현재 제공 근거만 취득·보존한다. source ID 미조회와 구조 오류는 구분하며 연속 구조 오류 3회에서 중지한다.

이미지 취득 결과가 바뀌면 acquisition_revision을 포함한 새 배치 입력을 만들어 보강 revision을 갱신한다. 동일 입력·요청 재시도는 기존 결과를 재사용한다. 기본 등록이 기존 확보 이미지 연결을 지우지 않으며 새 연결도 제목·source ID·파일명/이름·주변 문맥·등장 순서의 기존 보수적 규칙을 따른다.

## 실제 적용 중 발견한 migration 정합성

로컬 DB에 적용된 0009의 SHA-256은 `8f55655ceb320882fd6ac30649de63905a706e5e618245a2558287aa25e2ef75`였다. 후속 Git commit에서 gin_trgm_ops를 public.gin_trgm_ops로 바꾸며 과거 파일 내용이 달라져 다음 migration이 거절됐다. 적용 당시 commit `0a527b269131a672f8294849d9532be553caf6ed`의 원본 바이트를 복구했다. DB 이력 checksum을 고치거나 기존 migration을 재실행하지 않았다.

새 테스트 DB에서도 pg_trgm이 일회성 schema에 설치되지 않도록 미적용 0009 실행 전에 public에 확장을 설치한다. migration 이력 테이블은 대상 schema를 명시하며, migration transaction 동안 대상 schema를 먼저, public을 다음으로 명시해 확장 연산자를 찾는다. 일반 runtime의 search_path는 변경하지 않는다. 이후 0011 보강 ledger·조회 색인을 로컬 개발 DB에 적용했고 기존 import의 PRESERVED 89,130행/고유 position 89,130개를 확인했다.

## 실행 상태

기본 보강 manifest 등록은 892개 배치/89,130행 성공, 0행 실패로 완료했다. 전수 계획 `legacy-reader-plan:bc47976d81a667c729f1b211c4761316b62ee41143ad45f323bf4724224c5948`의 최종 실행 기록은 `legacy-reader-run:0227252f7f924971d18ca2a49c6a104dff827bbae2059e5334f7893081510fde`다. 먼저 완료했던 192개 배치를 재사용한 뒤 나머지 700개는 2,182.41초에 처리했다. `data/legacy-reader-scale-20260911-v1/baseline-registration-counts.json`에 전체 결과 재집계를 보존했다.

현재 전수 coverage 검증과 scourt 본문 이미지 확대 취득을 진행한다. 등록 성공과 모든 이미지/조문 보강 완료는 다르다. 일반 검색·실제 조문 이미지의 desktop/mobile 검증과 정적 검사 결과는 [QA](legacy-reader-scale-qa.md)에 기록했다.

## 조문 내부 이미지 추가 발견

[별도 전수 점검](legacy-statute-image-audit.md)에서 651개 판례의 조문 2,550개 위치에 이미지가 있음을 확인했다. 반복을 포함해 4,698개 이미지 위치이며 고유 URL은480개, 모두 www.law.go.kr이다. 기존 본문 img 집계와 별개이므로 새 보강 경로에 포함한다. 조문 내부의 원래 이미지 src·조문 payload hash·인용/이미지 순서를 유지하고, 공식 flDownload 경로의 파일을 취득·검증한 뒤 인증된 내부 URL로 표시한다.

## 조문 이미지 실제 전수 취득·연결 검증

651행의 조문 이미지 URL 480개를 모두 취득했다. 서로 다른 파일 hash는 473개이며, 다운로드한 응답 합계는 1,979,107bytes다(동일 bytes의 다른 URL 포함). 첫 표본 3URL과 나머지 477URL 모두 실패 0이었다. 전체 4,698개 등장 위치에 실물을 연결했고 과거 조문 본문/실패/미연결 상태와 법령 버전 미확인 표시는 유지했다.

- `data/legacy-reader-scale-20260911-v1/statute-image-all-download.json`: 나머지 477URL 취득 job과 입력 manifest, 실측 97.17초.
- `statute-image-all-linked-rows.json`: 651행의 새 reader revision과 조문 이미지 4,698/4,698 연결 결과.
- `statute-image-all-verification.json`: 독립 감사의 모든 위치와 부모/조문/취득 metadata 대조, 7,396개 고유 blob hash·473개 이미지 decode 검증. 오류 0, 미연결 참조 0. 이것은 조문 이미지 범위 검증이며 전체 corpus 이미지 완료를 뜻하지 않는다.

새 reader v3는 조문 인용 order와 조문 내부 이미지 order를 함께 사용한다. 반복 조문/이미지의 원래 위치를 유지하고 인증된 내부 URL에서 파일을 제공한다. 기본 본문 이미지 재보강도 기존 v3 조문 이미지 연결을 계승한다.

## scourt 본문 이미지 범위

공통 제공자 표식 3종(alert_img_01.png, flag_01.gif, flag_03.gif)은 원래 alt·src·등장 위치와 함께 보존한다. 이 세 정적 파일을 제외한 본문 그림은 10,877개 위치/1,872행이다. 사용할 scourt ID가 있는 1,829행은 1,825개 출처 번호로 묶이며, 나머지 43행은 식별·연결 미확인 상태로 남긴다. 이 분류는 표식을 제거하거나 임의의 현행 이미지로 대체하는 규칙이 아니다.

첫 현재 근거 50건 확대에서 56개 URL을 취득했고, 앞서 보유한 표본을 포함하여 23행의 74개 등장 위치에 본문 그림을 연결했다. 제목 차이 12행 중 제한적 약칭·별표 규칙으로 6행이 제목 검증을 통과했으며 그중 8개 위치는 추가 연결 후보가 됐다. 실제 후속 취득·연결 결과는 별도 실행 기록을 따른다. [제목 대조 근거](legacy-reader-title-review.md).

레거시 저장소 `I:\VSCodeBases\web2df`와 `I:\VSCodeBases\df2preproc`에서 Git·가상환경·node_modules를 제외하고 이미지 확장자를 점검했으며 각각 0개였다. 정적 표식 3종도 없었다. 외부 경로·압축 내부·확장자 없는 파일의 부재를 의미하지 않는다. source ID 미확보/원 URL 후보와 src 누락의 전수 예외는 [미해결 원인 감사](legacy-reader-unresolved-images.md)에 기록했다.

## 기본 등록 완료 시점의 전수 coverage

[검증 집계](legacy-reader-baseline-verification.json)는 scourt 본문 이미지 추가 wave를 적용하기 전의 고정된 등록 상태다. 89,130행 전부 STAGED_VERIFIED, 검증 오류 0, 예상 밖 position 0이었다. 원래 PostgreSQL import 89,130행의 fingerprint와 Parquet SHA-256은 전후 동일하다. 원문/manifest/조문/이미지의 고유 artifact 및 blob 315,630개 해시와 이미지 526개 decode를 확인했다.

조문 인용 1,641,768곳 중 저장 내용 702,035곳·과거 보강 실패 25,937곳·미연결 913,796곳이 원래 전수 감사와 일치했다. 조문 내부 이미지는 4,698/4,698곳 연결이며 참조 누락 0이다. 이 시점의 본문 이미지 연결은 78곳이고, 이후 scourt wave에서 확대한다. 공통 제공자 표식 위치까지 포함하는 전체 본문 img 105,793곳의 취득 완료를 뜻하지 않는다.

검증표는 `data/legacy-reader-coverage-20260911-baseline-v1/reader-coverage.parquet`(7,476,398bytes)와 같은 이름의 JSONL로 보존했고 두 표현의 round-trip을 확인했다. 원래 Parquet을 덮어쓰지 않으며 snapshot+position으로 연결하는 sidecar다. Parquet SHA-256은 `1f6ab08606a11ee37facd367d8343289446088c984e8524463ed74dc833b43a3`이다.
