# Step 3 / 3A 수집 구현과 현행 표본 검증

2026-09-10. Step 3 client와 양 출처 상세 취득을 구현했다. Step 3A 전체 완료는 아니다. 전체 inventory, 넓은 fidelity 표본, 자동 조문 보강과 대량 수집은 아직 실행하지 않았다.

## 구현과 경계

- sources/law_api.py: CaseSource protocol, LawOpenApiCaseSource, JSON/XML 목록·상세. singleton/배열/빈 페이지, total/page/count, 중복 ID·반복 페이지·total 변화·최대 10페이지 표본 제한을 검증한다. 제한 표본을 COMPLETE inventory로 만들지 않는다.
- Python 3.12 표준 urllib를 선택했다. 직접 HTTP가 작동했고 runtime 패키지 추가 없이 timeout, 제한된 read, redirect 차단, 원본 보존이 가능했다. ambient proxy·cookie·자동 redirect·request URL logging을 사용하지 않는다.
- 요청 전 최소 1초 대기. 법제처 요청은 최대 3회와 1/2/4초 대기, HTTP 408/429/500/502/503/504 및 transport 실패만 재시도한다. socket timeout 15초, read loop 30초 deadline, 최대 16MiB. deadline 검사 사이 socket read 시간은 추가될 수 있다. 이는 자체 정책이며 공식 quota가 아니다.
- sources/scourt.py: 현재 포털 metadata·본문 POST를 각각 보존하고 두 응답의 jisCntntsSrno를 요청 ID와 대조한다. 빈 orgdocXmlCtt·오류 schema는 정상 필드 부재가 아니다. 재시도는 영속 job 실패 예산에 맡긴다.
- sources/persistence.py: parse 전에 HTTP 응답과 별도 시도 receipt를 저장한다. 검증된 상세만 source_versions에 연결한다. metadata·본문은 별개 artifact이며 SCOURT_ACQUISITION manifest가 둘과 run/job을 연결한다.
- FETCH_LAW_DETAIL / FETCH_SCOURT_DETAIL, handler_version=source-1을 기존 단일 worker에 추가했다. 0005_source_jobs.sql을 추가하고 0001–0004는 변경하지 않았다. idempotency, 단일 claim, heartbeat·lease, drain·종료·재시도 예산을 공유한다.
- canonical registry·legacy 연결을 자동 변경하지 않는다. 법제처 본문으로 scourt 본문을 교체하거나 조문 내용을 자동 합치지 않는다.
- 포털 응답 envelope의 timestamp도 raw 바이트이므로 요청마다 hash가 달라질 수 있다. raw hash 변화는 법률 내용 변화와 다르다. 추출한 metadata/body 내용 hash와 증분 판정은 후속이다.

## 실제 확인한 표본

[API 실측](step3-live-api.json), [포털 실측](step3-live-scourt.json), [브라우저 관찰](step3-browser-observations.json)에 시각·hash·필드·크기·범위를 기록했다. HTTP 원본은 data/source-smoke/blobs에 보존하고, 8개의 작은 응답을 backend/tests/fixtures/sources에 정확한 바이트로 연결했다. manifest hash를 테스트한다.

| 출처 | 표본 | 결과 |
| --- | --- | --- |
| lawgo | 195490 / 2017도953 | JSON·XML 상세 성공, 빈 판결요지 보존 |
| lawgo | 240889 / 2023도11810 | JSON·XML 상세 성공, 빈 판결요지 보존 |
| scourt 현재 포털 | 2252318 / 2017도953 | metadata·본문 성공, 세션 없는 직접 HTTP |
| scourt 현재 포털 | 3328392 / 2023도11810 | metadata·본문 성공, 세션 없는 직접 HTTP |
| lawgo 목록 | nb=2017도953, display=1, page=1 | credential 감지로 저장 차단; 성공으로 세지 않음 |

이 두 건의 대응을 전체 legacy contId와 현재 jisCntntsSrno의 동일성 증명으로 확대하지 않는다. 전체 재번호·자동 relink·89,130행 import는 하지 않았다.

## 현행 경로와 선택 근거

기존 glaw.scourt.go.kr는 이번 브라우저와 WSL DNS 검사에서 해석 실패했다. 폐쇄 원인을 추정하지 않는다. [법제처 공식 안내](https://www.moleg.go.kr/board.es?act=view&bid=0010&list_no=135193&mid=a10504000000)와 법원 공식 링크에서 현재 portal.scourt.go.kr를 확인했다.

현재 [포털](https://portal.scourt.go.kr/pgp/index.on)은 WebSquare 화면이다. 종합법률정보 m=PGP1001M01에서 pgp1001/selectTotalSrchLst.on, 상세 popup에서 pgp1011/selectJdcpctDtl.on 및 selectJdcpctCtxt.on을 관찰했다. 과거 URL·selector를 현재 계약으로 복사하지 않았다. 검색은 본문 인용까지 반환하므로 첫 결과를 자동 identity 확정에 사용하지 않는다.

상세 두 endpoint는 Python 직접 POST로 검증했으므로 runtime Selenium/Playwright를 설치하지 않았다. inventory·popup 자동화에 browser가 필요해질 때 비교한다. 브라우저 검증 도구 사용을 앱 runtime browser 채택으로 취급하지 않는다.

법제처 [240889 상세](https://www.law.go.kr/precInfoP.do?precSeq=240889)의 제공 fncLawPop 링크를 클릭했다. 조문 창은 lsLinkProc.do, lsId=prec20231116, efYd=20231116, joNo=001300을 사용했고 조문 표 1개와 시행 2023-10-12 / 법률 제19337호 표시가 관찰됐다. lnkJoNo=undefined도 관찰 그대로 기록했다. 판결에 적용될 정확한 법령 버전을 앱이 독자 확정한 결과가 아니다.

관찰한 상세·조문 창에는 iframe이 없었다. 이 표본과 과거 구현의 차이이며 전체 사이트에 iframe이 없다는 결론이 아니다. DOM fragment는 HTTP 원본이 아니다. img 부재/UI 이미지로 원문 완전성·OCR 필요 여부를 단정하지 않는다.

## 목록 OC 포함과 사용자 결정

Step 0의 목록 credential 포함이 재현됐다. client는 literal·URL encoding·JSON escape 표현을 검사하고 SENSITIVE_RESPONSE_NOT_PRESERVED로 중단한다. redaction한 바이트를 RAW로 저장하지 않으며 credential 응답을 일반 artifact·fixture·로그로 보내지 않는다. 상세 네 응답은 검사 후 보존됐다.

2026-09-10 사용자 확정: LAW_GO_KR_OC/LAW_OPEN_API_OC(OC)는 비밀값이 아니며 응답에 포함되는 값이다. OC 포함만으로 저장을 차단하거나 마스킹하지 않고 원본 바이트를 그대로 보존한다. 별도 민감 원본 보존 정책은 선행 조건이 아니다. 위 차단은 과거 실행 사실이다. 후속 구현에서 OC 차단을 제거하고 목록 live 재검증을 완료했다. docs/source-path-validation.md 참조. 고정 quota·계정별 운영 승인·재배포 조건도 추정하지 않는다. [공식 계약과 출처](law-open-api-contract.md) 참조.

## 실행과 검증

migration·worker 기동은 루트 README를 따른다. 로컬 scourt 소량 등록 예:

    docker compose --env-file .fordeploy/compose.env.example -f compose.yaml -f compose.dev.yaml exec api klegal ops submit-scourt-detail my-stable-request-key 2252318

응답의 job_id를 유지하고 klegal ops job 명령으로 조회한다. 법제처는 klegal ops submit-law-detail REQUEST_KEY SERIALNO를 사용한다. worker에 명시적 LAW_OPEN_API_OC/LAW_GO_KR_OC가 준비돼 있어야 한다. 현재 Compose에 사용자 env를 자동 복사·mount하지 않았다. credential 없는 worker는 법제처 job을 실패·제한 재시도 처리한다. 같은 DB의 host worker와 Compose worker를 중복 실행하지 않으며 DB와 DATA_DIR의 저장소를 일치시킨다.

scripts/smoke_law_source.py는 backend에서 uv run python으로 실행한다. KLEGAL_ENV_FILE을 명시하며 local data/source-smoke 원본과 docs의 비밀값 없는 보고서만 저장한다. DB·corpus는 수정하지 않는다.

오프라인/실제 PostgreSQL 테스트와 live HTTP/브라우저 관찰은 구분한다. [검증 기록](step3-verification.json) 참조. 프런트·인증 UI·AWS는 변경하지 않았다.

## 다음 완료 항목

1. 완료: OC 저장 차단 제거·JSON/XML 목록 live 재검증.
2. scourt 목록 page·scope·per-ID hash·완전성 구현. 관찰한 검색 endpoint만으로 전체 inventory 완료를 주장하지 않는다.
3. 병합 번호·판결/결정·이미지/첨부·full-text-only·부분 실패 등 표본 확대 및 자원 측정.
4. Step 4/4A bootstrap·inventory·fetch ledger·delta/refresh 연결. 기존 corpus 보존 import를 우선한다.

최종 확인: ruff check/format·mypy, pytest 185건(실제 PostgreSQL 34건)이 통과했다. 기존 upstream warning 2건은 남아 있다. 로컬 Compose migration 0005·전체 health가 통과했고 scourt 2252318 작업이 첫 시도 SUCCEEDED, 저장 blob 재해시도 일치했다. [Compose 증거](step3-compose-verification.json) 참조.

현재 후속 상태는 [목록·현행 경로 확대 검증](source-path-validation.md)을 따른다. scourt bounded snapshot·worker와 이미지 참조 매핑은 구현했으며 전체 inventory 완전성은 별도다.
