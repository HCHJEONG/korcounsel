# 기존 89,130행 보강 열람 전수 확대 — 2026-09-11

사용자가 확정한 세 단계 중 첫 단계다. 기존 corpus의 본문·이미지·조문 열람을 완성하고, 그다음 신규·변경 수집, 이후 쟁점·답변·근거 구조화와 검수/GOLD 생산으로 진행한다. 이번 범위는 기존 corpus이며 원문 pickle·corrected Parquet·기존 canonical/검토 이력을 바꾸지 않는다.

## 전수 적용 후 최종 대조

기본 892배치로 등록한 89,130행 모두에 일반 검색의 보강 reader를 적용했다. scourt 19개 wave와 추가 이미지 취득 후, 현재 본문 근거가 있는 1,806행을 새 제목·이미지 이름 규칙과 최종 취득 상태로 19배치 재등록했다. 19배치 모두 성공했다. 원문 문자열·corrected Parquet·기존 import·ID는 유지하고 보강 revision을 추가했다.

[최종 전수 검증표](legacy-reader-final-verification.json)는 89,130행 모두 `STAGED_VERIFIED`, 오류 0, 예상 밖 위치 0을 확인했다. 고유 artifact/blob 320,460개의 SHA-256과 이미지 5,356개의 decode를 검증했다. 원 Parquet SHA-256과 기존 PostgreSQL import 89,130행 fingerprint는 전후 동일했다.

| 최종 일반 검색 reader의 위치 집계 | 수 |
| --- | ---: |
| 보강 reader 검증 통과 행 | 89,130 / 89,130 |
| 본문 이미지 실물 연결 | 7,561 |
| 본문 이미지 취득 실패 | 593 |
| 본문 이미지 식별·연결 불일치 | 1,639 |
| 본문 이미지 미취득·미연결 대기(제공자 정적 표식 포함) | 96,000 |
| 조문 내부 이미지 실물 연결 | 4,698 / 4,698 |
| 내용이 보존된 조문 인용 위치 | 702,035 |
| 과거 조문 보강 실패 위치 | 25,937 |
| 조문 내용 미연결 위치 | 913,796 |

본문 img 전체 105,793곳에는 ‘폐지/변경/위헌조문 표시’의 제공자 정적 표식 94,916곳이 포함된다. 실물 없는 표식도 원래 alt·위치·출처와 미취득 상태를 유지한다. 조문 내용이 있다는 사실은 해당 재판 시점 법령 버전이 확인됐다는 뜻이 아니다. 전수 등록·해시 검증과 모든 이미지 취득·법령 버전 확정·사람의 시각 검수·GOLD 완성은 구분한다.

최종 실행 계획은 `legacy-reader-plan:165a880e6768d1e276d8a840abb137d68e3575628e0bb889afeb6db0c43d3517`, 결과는 `legacy-reader-run:45f276157f782fa22a9d83b2328e957d12617c4e84e95f6d1ad2d46e4c30fc48`다. `include_statute_images=true`와 취득 상태 revision을 고정해 scourt 본문 갱신 후에도 조문 이미지 4,698곳이 유지됨을 전수 확인했다.

행별 검증표는 `data/legacy-reader-coverage-20260911-final-v1/reader-coverage.jsonl`(63,195,705bytes, SHA-256 `6dbb803f766424c0ddb9f5245fbbf0b9f6f4df5d016ede4ed46d5e75af3665ce`)과 `.parquet`(7,488,353bytes, SHA-256 `8b55d7c9862c754166f9691d0a3f31f235f90b9d443dfb6edd0fd9cae1755166`)으로 보존하고 round-trip을 확인했다. 원본에 연결하는 sidecar이며 원 Parquet을 덮어쓰지 않는다.

아래 실행 중·표본 기록은 단계별 이력이다. 최종 상태는 이 절, 실제 브라우저·정적 검사는 [QA](legacy-reader-scale-qa.md)를 따른다.

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

기본 등록에 대한 전수 coverage 검증은 통과했고, scourt 본문 이미지 확대 취득을 진행한다. 등록 성공과 모든 이미지/조문 보강 완료는 다르다. 일반 검색·실제 조문 이미지의 desktop/mobile 검증과 정적 검사 결과는 [QA](legacy-reader-scale-qa.md)에 기록했다.

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

## scourt 첫 100개 출처 적용

첫 wave는 현재 출처 100개 모두의 근거를 보존했다. 이미지 280URL 중 272URL을 취득했고(1,119,111bytes), 제목 대조를 통과한 89행의 새 보강 revision에 본문 이미지 494곳을 연결했다. 추가 감사에서 서울중앙지법/서울중앙지방법원 약칭만 다른 두 행을 확인해, 기존 위치/문맥 조건을 유지하는 제목 규칙 v2로 보완했다.

후속 작업은 새 후보와 실패 URL만 포함한 14URL/22참조를 처리했다. 새 이미지 6URL(9,288bytes)을 취득해 14곳에 추가 연결했고, 나머지 8URL은 재시도에서도 빈 응답(0bytes, Content-Type 미제공)을 반환했다. 빈 응답도 원문 hash와 취득 시각/job/attempt를 연결한 별도 HTTP_RESPONSE artifact로 보존했다. [실패 응답 계약](image-decode-failure-evidence.md).

후속 결과는 91행 새 보강 성공·9행 현재 이미지 동일성 미확인이다. 9행도 전수 기본 보강 열람은 유지하며, 기존/현재 제목의 추가 사건번호·재판부 차이를 자동 병합하지 않는다. 후속 91행의 본문 이미지 연결은 508곳이다. `data/legacy-reader-scale-20260911-v1/scourt-wave1-repair-result.json`과 `wave1-rejected-responses.json`에 실제 결과를 남겼다. 이 시점에 남은 1,725개 출처의 2~19번째 wave를 진행한다.

## 세 번째 wave 중단 원인 조사

source 3247457(position 7520)의 세 차례 요청은 metadata/body 모두 HTTP 200이었으나, 본문 orgdocXmlCtt는 빈 문자열이었다. 원응답 6개는 보존했으며 이 상태를 정상 본문이나 source 미조회로 간주하지 않는다. 이 실패를 해석하는 보조 도구가 모든 과거 HTTP_ATTEMPT를 순회하다 2026-09-10의 무관한 receipt 파일 누락을 만나 전수 wave를 중단했다. 누락 파일은 이번 89,130행 baseline coverage 대상과 별개다. 기존 프로젝트 안에서 해당 hash 파일을 찾지 못했으며 이력을 삭제하거나 가짜 응답으로 채우지 않았다.

`data/legacy-reader-scale-20260911-v1/wave3-source-failure-review.json`에 관련 원응답·실패job·무관한 누락 artifact와 조사 범위를 보존했다. 실패 분류는 새 receipt의 명시적 run_id, 과거 receipt의 해당 job 실행 구간과 실제 run_id를 사용하도록 보완한다. 해당 job의 근거 파일이 없거나 hash가 다르면 평범한 source 실패로 숨기지 않는다.


## scourt 현재 본문과 실물 보존의 전수 확대

1,825개 gmeta 출처 ID를 19개 wave로 처리했다. 현재 본문 근거 1,803개를 보존해 기존 1,806행과의 대조에 사용했다. 21개 ID는 미조회, 1개 ID는 metadata 조회 후 빈 본문으로 실패했다. 제목·재판 종류·병합 사건번호 또는 이미지 위치의 불일치를 자동 병합으로 해소하지 않았다. 제목 표시와 `ImageIdN`→`imgN`의 제한적 이름 변화는 실제 원문·완전한 번호·파일명·문맥·순서를 검증하는 [연결 규칙](legacy-image-name-display-v1.md)으로만 허용했다.

19개 wave가 보존한 현재 본문에서 유효 다운로드 URL 7,839개 전부에 취득 결과가 있다. 성공 7,399URL/9,372등장 위치이며 고유 5,720파일의 SHA·크기·decode를 확인했다. 실패 440URL/743위치, URL 매핑 미확인 28위치다. 마지막 5개 추가 job은 미시도 2,110URL 중 1,929개를 취득했고 181개는 decode 실패를 기록했다. 상세 독립 집계는 [제목·이미지 전수 대조](legacy-reader-title-review.md)에 있다. 현재 본문 9,372위치의 실물 보존 수를 과거 corpus의 7,561위치 연결 수와 섞지 않는다.

gmeta가 비어 있던 별도 43행은 원 이미지 URL의 출처 번호를 후보 근거로 조사했다. 2개 현재 본문을 보존했고 41개는 미조회였다. 그 2개 본문의 36URL/37위치(고유 36파일, 427,593bytes)는 전부 취득·검증했다. 후보 ID를 gmeta/canonical에 채우거나 기존 43행과 자동 연결하지 않았다. [미해결 목록과 후보 조사](legacy-reader-unresolved-images.md)를 따른다.

## 기존 등록 원본의 저장 루트 점검

전수 열람 검증과 별도로 전체 등록 blob의 host 경로를 감사했다. 호스트 `data/`에서 미발견된 178,314개 중 178,262개는 과거 corrected bundle FileStore, 52개는 기존 Docker `korcounsel_case_data` 볼륨에 있었다. 원본이 없어진 것으로 판단하거나 데이터를 다시 생성하지 않았다. [저장 루트 감사](registered-blob-storage-root-audit.md)에 위치·크기·표본 hash 및 복구 전 근거를 보존했다.

Compose API/worker는 이제 `LOCAL_DATA_DIR`(기본 `./data`)를 `/data`로 공유하고, 호스트 실행도 같은 `DATA_DIR`를 사용한다. 비-root UID/GID는 host 소유자에 맞춘다. PostgreSQL과 기존 Docker 원본 볼륨은 보존한다. 원본 bytes의 exact copy 및 전수 사후 점검 결과는 아래에 기록한다.


## 공통 저장소를 사용하는 로컬 Compose 검증

수정된 Compose config와 API/web image build가 통과했다. API·worker는 모두 host `data/`의 같은 bind mount와 비-root `1000:1000` 사용자로 실행되며 두 서비스 health가 정상이다. worker의 임시 파일 쓰기·읽기·삭제로 공통 폴더 접근을 확인했고 DB나 기존 파일을 검증용으로 고치지 않았다. PostgreSQL named volume과 과거 `korcounsel_case_data` volume은 유지했다.

`http://127.0.0.1:8080`의 Nginx 정적 프런트와 API health는 200, 미인증 검색은 401이었다. 실제 허용 계정으로 일반 검색에서 `95후1944`의 45,898행을 열어 새 revision의 본문과 원래 이미지 2개의 내부 URL을 200으로 읽고 hash를 대조했다. 고정 revision 재열기 200, 외부 이미지 URL 0, 로그아웃 후 두 이미지 접근 401이었다. 사용자 환경파일의 비밀값이나 로그인 토큰을 보고서에 기록하지 않았고 검증 세션은 로그아웃했다.

결과는 `data/legacy-reader-scale-20260911-v1/compose-storage-config-verification.json`, `compose-storage-build.json`, `compose-storage-runtime-verification.json`이다. 이는 로컬 Compose 실행 검증이며 AWS 운영 배포가 아니다.


## 원본 경로 복구 완료와 최종 회귀

분리된 저장 루트에서 발견한 178,314개 파일·14,813,884,622bytes를 원래 hash/size가 일치하는 독립 bytes 복사로 공통 `data/`에 복구했다. Docker 52개와 corrected bundle 178,262개 모두 오류 0이다. 파일·디렉터리의 원자적 저장과 fsync를 유지했고 기존 보존본은 남겼다. 복구 후 이번 전체 파일을 다시 읽어 SHA-256을 검증했으며, 새 DB snapshot의 등록 blob 529,551개 모두 공통 경로의 일반 파일·크기가 일치했다. 기존 blob 178,314행 및 artifact 178,315행의 전체 metadata fingerprint도 전후 동일했다. [복구 입력·실행·전수 검증](exact-blob-store-recovery.md)에 근거를 기록했다.

최종 Python/PostgreSQL 회귀는 **688개 통과**(기존 경고 4개, 65.76초), Ruff check/format과 mypy도 통과했다. 실제 대상은 `korcounsel_test`의 격리 schema다. 프런트 타입·lint·build와 실제 일반 검색 desktop/mobile **28개 검사**가 통과했고, 테스트 종료 보완 후 해당 2개 시나리오 재검사와 임시 schema·서버 정리를 확인했다. 이 2개를 신규 시나리오 수로 합산하지 않는다. [QA 전체 기록](legacy-reader-scale-qa.md)을 따른다.

최종 코드 검토에서 공백만 다른 current title을 name-v3 재검증 시 legacy raw title로 바꾸는 경계 오류를 발견해 수정했다. 보존 current-reader metadata 및 실제 h2/strong을 재대조하며, 새 제목을 추정하지 않는다. 관련 164개 회귀와 실제 1,806행 중 name-v3가 있는 299행/1,186위치의 재검증도 통과했다. 기존 원문·reader·proof·연결 개수는 그대로이며 다시 등록하지 않았다.

일반 그림은 1,872행/10,877위치 중 7,561곳을 연결했다. 남은 3,316곳은 취득 실패 593·대응 미확정 1,557·대기 1,166이다. 그림이 있는 행 중 최소 한 곳 연결은 1,370행(전부 연결 977·일부 연결 393), 연결된 그림이 없는 행은 502다. 제공자 정적 표식 94,916곳은 별도이며 대기 94,834·대응 미확정 82다. 초기 `PROVIDER_UI` 분류는 alert만 포함했으므로 최종 분류는 원 src의 정확한 세 정적 파일 경로로 전수 재대조했다. [상태별 행 수와 근거](legacy-reader-title-review.md)를 참고한다.

## API 갱신 후 로컬 프록시 재시작

마지막 backend image 갱신 때 API/worker는 정상이었지만 기존 Nginx가 이전 API 주소를 유지해 `/api/health`가 502를 반환했다. 같은 web 컨테이너에서 현재 `api:8000`을 직접 조회하면 200이었으므로 데이터 문제와 구분했다. 기존 web을 한 번 재시작해 복구했고, Compose web의 API 의존성에 `restart: true`를 지정했다. 명시적인 `docker compose restart api`에서 web의 실제 시작 시각도 바뀌고 health 200이 유지되는 것을 확인했다. PostgreSQL의 컨테이너 ID·시작 시각은 그대로였다.

최종 backend image로 일반 검색→본문→이미지 2개→고정 revision 재열기→로그아웃 후 차단을 다시 통과했다. 추가 근거는 `compose-api-recreate-proxy-before.json`, `compose-api-recreate-proxy-after.json`, `compose-storage-build-v2.json`, `compose-storage-runtime-verification-v2.json`이다. 이 결과도 로컬 검증이며 AWS 변경은 없다.
