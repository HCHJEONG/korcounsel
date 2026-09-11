# 이미지 URL 접근과 실물 보존 검토 — 2026-09-10

**본문 열람 후속 구현 — 2026-09-11:** 실제 4건의 현재 본문에서 13개 등장 위치를 reader manifest로 보존했고 8곳은 저장 파일로 연결했다. 5곳은 실패 위치를 표시한다. 인증된 내부 API·안전한 viewer를 구현했으며 과거 corpus 자동 연결은 하지 않았다. 아래 URL 그룹 ledger 설명과 별도로 [reader 위치 계약과 검증](image-reader-validation.md)을 따른다.

**전수 검증 후속 — 2026-09-10:** 89,130행 날짜 교정 후보와 이미지 inventory를 생성했다. 선고일 89,130행, 변론종결일 13,518행 READY이며 복수 날짜 45행은 적용 보류다. 교정 변경분 Parquet의 Python·Node 전수 왕복을 검증했고 현재 이미지 38 URL의 bytes를 취득했다. 이후 전체 60컬럼 corrected Parquet, corrected bundle v2, 로컬 개발 PostgreSQL 보존 import, Parquet 직접 검색 UI를 완료했다. 이미지 전수 취득과 canonical 등록은 미완료다. [결과와 한계](legacy-repair-and-images-progress.md).

## 영속 ledger와 worker 취득 경로 — 2026-09-11

이미지 취득을 분석용 스크립트에만 두지 않고 PostgreSQL job/worker 경로에 연결했다. migration 0010은 세 테이블을 추가한다. `image_references`는 부모 manifest hash, source_system/source_id, row_position, 원래 src, image_name, resolved_url, 등장 순서, 상태와 사유를 불변 이력으로 저장한다. `image_acquisitions`는 URL별 현재 취득 상태와 blob hash, 크기, content type, 이미지 header metadata, 마지막 오류를 저장한다. `image_acquisition_attempts`는 job별 ACQUIRED/FAILED/SKIPPED 시도를 불변 이력으로 남긴다. 같은 URL이 이미 ACQUIRED이면 새 job은 재다운로드하지 않고 SKIPPED/ALREADY_ACQUIRED attempt를 남긴다.

worker job kind는 `ACQUIRE_IMAGE_BATCH`이고 handler_version은 `asset-1`이다. payload에는 보존된 image manifest artifact ID, `max_urls`, `max_total_bytes`만 들어간다. 임의 URL payload를 worker에 직접 넣지 않는다. 직접 취득 URL allowlist는 현재 portal 제공자 매핑 방식 `portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on?pgmId=PGP1011M04&jisCntntsSrno=...&atchImgFileNm=...`로 제한한다. 기존 8,418개 대상의 레거시 glaw 방식 `glaw.scourt.go.kr/wsjo/cm/imgDownload.do?contId=...&attachImgNm=...`은 원참조로 보존하고, 현재 scourt 본문/provider mapping을 다시 관찰해 portal URL로 재해석해야 한다. 응답은 16 MiB per-image 상한, batch 총량 상한, timeout, signature/header 검사 후 SHA-256 blob으로 저장한다. HTTP 200이나 Content-Type만으로 성공 처리하지 않는다.

`reference_status`는 RESOLVED, NAME_ONLY, ID_MISMATCH, UNRESOLVED를 구분한다. name-only는 제공자 name 값은 있지만 안전한 URL을 만들 수 없는 상태이고, ID_MISMATCH는 행의 source ID와 이미지 URL/매핑의 contId가 다른 관찰이다. 둘 다 자동 성공이나 자동 병합으로 처리하지 않으며 원문 참조와 context를 보존한다.

8,418개 레거시 URL 대상의 제한 확대를 위해 `scripts/stage_image_acquisition_manifest.py`를 추가했다. 이 스크립트는 레거시 glaw URL을 `resolved_url`로 넣지 않는다. 대신 원래 URL, 파일명, legacy contId, row_position과 그룹 context를 보존하고 현재 portal mapping 재관찰이 필요하다는 이유를 남긴다. 수정된 50개 표본 manifest는 `data/repair-audit-20260910/image-acquisition-manifest-legacy-unresolved-sample-50.json`이며 `image-manifest:legacy-unresolved-sample-50` artifact로 보존했다. SHA-256은 `0cd3f7426a20be8c08073b40cda68cbd74dcb27930183ef7174a7df3aae5a54a`, 크기는 64,085 bytes다.

로컬 개발 DB에서 0010을 적용하고 새 worker로 실행한 job `c5c585d0-f324-4554-a930-de2cad384d5d`는 처리 경로 검증을 마쳤다. 결과는 references 50, urls_considered 0, acquired 0, skipped 0, failed 0, bytes_stored 0이다. DB 집계는 NAME_ONLY 50건, image_acquisition_attempts 0건이다. 즉 레거시 glaw 참조는 보존했지만 현재 취득 가능한 URL로 간주하지 않았다.

이전에 glaw URL을 직접 `resolved_url`로 둔 job `4087f002-1579-4ca0-9b31-d998c760c32d`는 SUCCEEDED였지만 50개 attempt가 모두 `IMAGE_NETWORK_ERROR`였다. 대표 URL의 `curl -I`도 현재 WSL 환경에서 `glaw.scourt.go.kr` DNS 해석 실패를 보였다. 이 이력은 레거시 URL 직접 재시도 방식의 한계로 보존하고, 최종 방식은 현재 portal provider mapping 재관찰 후 취득이다. 첫 제출 job `675bb53a-83cd-4de1-839c-7ed0d2015be6`은 Docker의 구버전 worker가 먼저 claim하여 `ARTIFACT_INTEGRITY_FAILED`로 3회 실패했다. image batch 확대 전에는 실행 중 worker가 새 코드인지 확인하거나 worker 이미지를 재빌드해야 한다.

로컬 저장 용량 실측은 `/dev/sdd` 기준 전체 1007G, 사용 72G, 여유 885G, data/ 24G였다. 따라서 용량은 현재 선행 차단 사유가 아니지만, 실제 전수 취득은 HEAD/소량 GET, per-file 16 MiB, batch 총량, SHA dedupe, ledger 재시도, 실패 집계를 유지하면서 단계적으로 넓힌다.

## 실측과 한계

사용자 질문에 따라 기존 절대주소의 접근 가능성과 현재 name 매핑의 의미를 검토했다. [이전 조사](source-path-validation.md)의 2029039 표본에서 파일 2개를 골라 과거·현재 공식 주소에 각 1회 GET했다. 전체 corpus나 최신 판례 전체를 조사한 결과는 아니다. 이 자료는 중앙해양안전심판원 재결이며 일반 법원 판결로 일괄 분류하지 않는다.

| 경로 | 이번 관찰 |
| --- | --- |
| glaw.scourt.go.kr/wsjo/cm/imgDownload.do | 로컬 WSL에서 도메인 이름 해석 실패. HTTP 응답을 받지 못함 |
| portal.scourt.go.kr/pgp/pgp003/downloadImgFile.on | 두 파일 모두 HTTP 200, GIF signature 및 header 크기 확인 |

현재 파일은 11w0401-009-01.gif(9,351 bytes, 530×425), 11w0401-009-02.gif(13,154 bytes, 289×185)다. cookie·Referer 없이 직접 GET으로 받았다. 응답 Content-Type은 image/gif가 아닌 application/x-octetstream이었다. 확장자·HTTP 200·Content-Type만으로 이미지 성공을 판정하면 안 된다. 이번에는 signature/header를 확인했으며 전체 이미지 decode 검증·OCR·과거 binary와의 동일성 대조는 하지 않았다.

실제 응답 bytes는 data/image-url-audit/의 SHA-256 이름 파일로 보존했고 [요청·결과·해시](image-url-live-audit.json)에 기록했다. 기존 source-path 조사에서 binary 미취득이라고 한 시점과 이번 2개 조사용 파일 취득을 구분한다. 운영 worker 기반 영속 ledger와 제한 batch 취득 경로는 2026-09-11 구현했다. 다만 이 문단의 2개 파일 취득은 별도 조사 이력이며, 8,418개 전수 bytes 취득 완료를 뜻하지 않는다.

과거 주소는 현재 이 환경에서 접근할 수 없었다. 이를 전 세계 DNS 폐지·모든 과거 링크의 실패·파일 자체 소실이라고 단정하지 않는다. 현재 경로에서 같은 파일명이 조회돼도 과거 이미지 bytes와 동일하다는 증거는 아니다.

## name 방식과 URL의 관계

현재 관찰은 src 없는 img name과 contImagePath name/value 매핑으로 파일명을 찾고, 문서 ID·파일명으로 다운로드 URL을 구성하는 방식이다. name이 영구 asset ID라는 뜻이 아니며 문서 내부 매핑 문맥에 속한다. 실제 전송에는 URL이 사용된다.

기존의 상대 src를 절대 URL로 만드는 처리는 base 주소 해석만 해결한다. 도메인·endpoint·문서 ID·파일명이 바뀌거나 제공자가 파일을 내리면 절대주소도 실패할 수 있다. 이번 현상은 “최신 판례만 name 방식”으로 단정하기보다 현재 사이트가 과거 문서도 새 방식으로 제공하는 경우로 해석해야 한다.

## 사용자 확정: URL과 이미지 bytes를 함께 보존

**2026-09-10 사용자 확정:** 이미지 확보 문제도 이번 corpus 정비·Parquet 전환 과정에서 해결한다. 아래 URL+실물 파일+위치 연결 방식을 채택하며 기존 자료 복구와 신규 수집에 적용한다. 저장 용량은 현재 큰 문제가 아니라는 사용자 판단에 따라 용량 우려를 이유로 취득을 미루지 않는다. 실제 용량·중복률은 저장·백업 운영을 위해 측정한다. 이는 범위·방식의 확정이며 전수 다운로드 구현·실행 완료를 뜻하지 않는다.

장기 재현과 안정적인 검수 화면이 목적이면 URL 참조만으로는 충분하지 않다. 취득 가능한 이미지 bytes를 관리하는 영속 저장소에 보관하고 원래 참조와 함께 연결하는 것이 적합하다. “로컬”은 개발자 PC 한 곳만을 뜻하지 않으며 서비스 데이터 디렉터리와 백업까지 포함한다. 이를 위해 별도 서버나 새로운 클라우드 서비스를 기본 도입할 필요는 없다.

확정 처리 흐름:

1. 기존/신규 HTML에서 src·name·제공자 매핑·문서 안의 위치·중복 사용을 inventory로 기록한다.
2. 제공자 매핑에 근거해 URL을 해석하고, 제한된 크기·timeout·동시성·retry로 bytes를 취득한다. 필요한 경우에만 공식 페이지 세션을 사용한다.
3. MIME·signature·decode·실제 크기와 SHA-256을 확인하고 hash 기반 파일로 저장한다. 내용이 같은 파일은 공유하되 모든 등장 위치를 보존한다.
4. manifest에 부모 HTML hash, 원 src/name, 제공자 파일명·출처 ID, 요청/최종 URL, 취득 시각, asset hash, 상태·실패 사유를 기록한다.
5. 기준 HTML 문자열은 그대로 두고, 검수용 파생 화면에서 asset 연결을 통해 내부 파일을 표시한다. 원본 HTML의 URL을 덮어쓰지 않는다.
6. Parquet에는 이미지 참조·상태·manifest/asset hash를 담고, binary는 별도 파일로 둔다. 모든 이미지를 base64로 본문·Parquet에 삽입하는 방식은 기본안으로 삼지 않는다.

이미지 취득 성공, 현재 제공 이미지와 과거 이미지의 동일성, 문서 위치 연결, OCR 해석은 별개의 상태다. 현재 이미지를 뒤늦게 취득한 경우 실제 취득 시각을 기록하고 과거 수집본으로 가장하지 않는다. 본문은 우선 보존하고 이미지 실패는 대기/부분 실패로 남기며, 중요한 이미지가 빠진 문서를 시각적으로 완전하다고 표시하지 않는다.

## 기존 이미지 복구의 범위

기존 HTML 주소를 문자열 치환으로 일괄 수정하면 출처 ID 변경·파일명 변경·문서 연결 오류를 숨길 수 있다. 기존 ID가 현재도 연결되는지 확인하고 현재 응답의 제공자 매핑에서 파일 후보를 얻는다. ID가 달라진 경우는 기존 identity 검토 계약을 먼저 따른다. 찾지 못한 이미지의 과거 위치와 URL은 보존하고 복구 미확인으로 남긴다.

이번 범위는 corpus 이미지 참조 전수 inventory → 소수 문서의 binary 취득·decode·위치 연결 검증 → 취득 가능한 기존 이미지의 전수 확보 및 실패/재시도 관리 → 신규 수집 경로에 같은 보존 방식 적용이다. 날짜 교정과 함께 처리할 작업으로 관리하며, 단순 URL 점검이나 소수 표본 취득만으로 완료 처리하지 않는다. 현재는 조사용 2개 파일 확보와 worker 기반 ledger/제한 batch 경로 구현까지 수행했다. 8,418개 전수 bytes 취득은 아직 완료하지 않았다.


## 완료 기준

- 기준 원문 HTML 문자열이 변하지 않고 모든 관찰 이미지 위치가 inventory에 연결된다. 파일을 중복 제거해도 반복 등장 위치는 유지한다.
- 취득 성공 파일의 bytes·SHA-256·decode·크기와 부모 문서 연결을 검증하고 영속 저장·백업 대상에 포함한다.
- 전체 참조를 성공·대기·실패·연결 미확정 등으로 집계하고 누락 없는 처리를 대조한다. 접근 불가 자료는 실패 근거와 재시도/검토 상태를 남기며 삭제하거나 완료로 위장하지 않는다.
- 기준 HTML을 덮어쓰지 않고 내부 asset을 이용한 표시 경로와 Parquet/manifest 참조를 검증한다. 기존 ID 변경 후보는 identity 검토를 거쳐 연결한다.
- 중단 후 재개·동일 파일 재사용·부분 실패를 검증한다. OCR·이미지 의미 해석과 신규 AWS 인프라 변경은 이 결정에 포함하지 않는다.

## 본문 위치 연결의 실제 완료 범위 — 2026-09-11 점검

이미지 파일 보존과 본문 내 개별 등장 위치 연결은 별도 완료 기준이다. 현재 제한 batch는 URL 그룹에서 만들어져 source_id, 대표 row_position, URL 목록의 occurrence_order, 원참조와 그룹 context를 저장한다. staging은 URL을 중복 제거하고 positions의 첫 행을 대표로 사용하므로 이 occurrence_order를 본문 내 img 등장 순서로 해석해서는 안 된다. 반복 등장 및 여러 행의 각 위치를 개별 reference로 저장한 상태가 아니다. manifest_hash도 이미지 목록의 hash이며 본문 artifact hash를 대신하지 않는다.

observe_html은 관찰 대상 HTML hash와 각 img의 실제 등장 순서·HTML 행/열·원 src/name·제공자 매핑을 산출하지만, 기존 corpus의 그룹 기반 batch와 해당 위치 관찰을 연결하여 전수 검증하는 단계는 남아 있다. 태그 있는 보존 본문에서 위치를 다시 추출할 수 있으며, 현재 ledger만으로 정확한 본문 위치 연결 완료를 주장하지 않는다.

다음 위치 연결 작업은 본문 snapshot/행 locator 및 본문 artifact·필드·hash, img별 등장 순서·태그 위치·전후 문맥, 개별 reference ID와 취득 blob hash를 연결한다. 같은 이미지가 여러 번 나오면 파일 bytes는 재사용해도 등장 reference는 모두 보존한다. 원문과 위치를 전수 대조하고 반복 등장 표본의 재구성까지 검증한 뒤 완료로 기록한다. HTML 위치는 정규화 텍스트 evidence offset과 구분한다.

## 이미지 포함 판례 열람 — 2026-09-11 사용자 확정

사용 목적은 판례를 열었을 때 다운로드하여 보존한 이미지를 해당 본문의 원래 등장 위치에 표시하는 것이다. 취득 건수나 ledger 저장만으로 작업을 완료하지 않는다. 기존 corpus와 신규 판례 모두 같은 기준을 적용한다.

- 특정 보존 본문 버전의 각 이미지 등장 위치를 개별 reference로 연결하고, 검증된 취득 파일의 hash를 따라 표시한다. 같은 파일의 반복 등장은 각각 유지한다.
- 기준 HTML은 그대로 보존하며 안전한 열람용 표현을 생성한다. 문단·표·이미지의 순서와 의미 있는 배치를 유지하고, 저장된 이미지는 인증된 내부 제공 경로로 읽는다. 개발 PC의 절대 파일 경로를 화면에 넣지 않는다. AWS에서도 같은 참조 계약과 영속 저장소로 제공한다.
- 이미지가 미취득·실패·연결 미확정이면 해당 위치에 상태를 표시한다. 외부 이미지로 조용히 대체하거나 빈자리로 누락시키지 않는다.
- 대표 실제 판례를 검색에서 열어 다운로드한 이미지가 원래 위치에 표시되는지 브라우저에서 검증한다. 반복 이미지·표 안의 이미지·name-only·ID 불일치·취득 실패를 포함하고, 저장된 이미지의 표시가 외부 제공자 접속 없이 동작하는지 확인한다.

현재 검색 UI는 목록 조회 단계이며 위 이미지 포함 본문 열람의 구현·브라우저 검증은 미완료다. 다음 검증 단위는 소수 실제 판례에 대해 위치 추출 → 현재 제공자 매핑 확인 → 파일 취득 → 내부 제공 → 본문 렌더링을 끝까지 연결하는 것이다. 그 결과를 확인한 뒤 같은 경로로 전체 corpus 처리를 확대한다. OCR은 표시의 선행 조건이 아니다.
