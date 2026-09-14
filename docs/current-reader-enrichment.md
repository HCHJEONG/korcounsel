# 현재 scourt 본문의 이미지·lawgo 후속 보강 — 2026-09-14

관리자의 명시적 증보 명령에서만 실행한다. schedule/cron은 만들지 않는다. 기존 raw/source HTML/reader manifest는 수정·삭제하지 않는다.

## 처리와 재개

`FETCH_SCOURT_DETAIL`은 먼저 현재 본문과 이미지 위치 manifest를 보존하고 checkpoint를 기록한다. 중단 후에는 해당 reader에서 후속 job 등록을 재개하며 본문을 다시 요청하지 않는다. 이미지가 있으면 `ACQUIRE_IMAGE_BATCH`와 `REFRESH_CURRENT_READER_IMAGES`를 각각 idempotent하게 등록한다. 후자는 PostgreSQL에서 선행 image job의 `SUCCEEDED` 또는 최종 `FAILED`를 확인해야 claim된다. 재시도 대기 중 선행 job을 건너뛰어 갱신하지 않으며 대기만으로 시도를 소진하지 않는다.

갱신 handler는 immutable image manifest와 reader의 연결을 확인하고 `image_acquisitions` ledger를 읽는다. 저장 blob의 SHA-256·decode를 검증해 내부 reader image artifact로 연결한다. 성공·실패·대기는 각 등장 위치에 반영한다. 동일 URL의 반복 등장은 별도 위치로 유지한다. 같은 입력·같은 ledger의 재실행은 같은 reader ID를 반환한다. 취득 job의 일부/최종 실패가 이미 보존한 판례 본문을 실패로 만들지 않는다.

source_id별 검색은 가장 최근 기본 본문의 revision을 우선한다. 늦게 완료된 과거 본문의 보강이 새 본문을 가리지 않도록 root reader 생성 시각, 파생 revision 생성 시각, artifact ID 순서로 선택한 뒤 제목 필터를 적용한다. 이전 revision은 직접 ID로 계속 열 수 있다. 현재 자료는 제목·사건번호 일치를 우선 조회하고, 제목 일치가 없으면 최신 본문을 페이지별로 대조한다. 이 본문 fallback은 파일 순회이므로 대규모 검색 projection은 후속 과제다. legacy Parquet 검색은 계속 함께 제공한다.

## lawgo 제공 연결

`ENRICH_CURRENT_LAWGO`는 이미지 reader 갱신의 완료/최종 실패 뒤 실행한다. 이미지 없는 본문은 detail job의 완료 뒤 실행한다. 후보 목록 최대 20건에서 법원/지원, 전체 병합 사건번호, 재판 종류를 정확히 비교하고 선고일도 일치하는지 대조한다. 날짜는 identity key에 추가하지 않는다. 후보가 여러 개이거나 목록이 제한을 넘으면 AMBIGUOUS, 일치가 없으면 UNMATCHED, 상세와 목록이 충돌하면 CONFLICT다. canonical 병합이나 출처 ID 재번호는 수행하지 않는다.

현재 lawgo `precInfoP.do`의 판례 ID·날짜를 검증하고, 실제 `fncLawPop(..., JO, ..., prec)` 링크만 사용한다. scourt의 현재 `linkPrvs`와 과거 `linkContJomun` 인용 위치를 관찰한다. 두 제공자의 인용 표시문구가 정확히 일치하고 lawgo 요청 대상이 하나일 때만 연결한다. 같은 문구가 상충하는 대상으로 연결되면 자동 선택하지 않는다. 앱이 인용문에서 법령 이름/조항을 추론해 법령 API를 호출하지 않는다.

실측한 제공자 `lsLink.js`의 mode 11·판례 날짜 처리에 따라 `lsLinkProc.do`를 호출한다. `summary=조문정보` 표, `lsLinkTable`, 조문 내용이 확인되어야 보존 성공이다. 원 응답과 추출 표를 분리하고 source frame/원래 태그/부모 HTML hash/위치/법제처 판례 ID/규칙 버전을 기록한다. provider가 반환한 연혁 표시를 보존하되 적용 법령 버전은 UNVERIFIED로 둔다. 기존 보강 내용은 재실행과 이미지 revision 갱신에서도 계승한다. 실패·미연결은 각 조문 위치에서 연결된 보강 영역에 표시한다.

job별 immutable plan과 조문 응답 artifact가 checkpoint 역할을 한다. 완료 응답은 재사용한다. 별도 재확인은 관리자 전용 `POST /api/admin/readers/{document_id}/lawgo`에 UUID `request_id`를 전달한다. 같은 요청 ID는 같은 job을 반환하고, 새로운 요청 ID로 미완료분을 재확인한다. 본문 수집을 다시 하지 않는다. 현재 수집 본문에는 관리자 전용 ‘조문 보강 재확인’ 버튼을 제공한다. 요청 ID와 job ID를 현재 본문의 URL에 보존하여 새로고침 후 상태를 복구하고, 등록 응답 유실 시 ‘같은 요청 확인’으로 기존 job을 재확인한다. 완료된 본문은 사용자가 ‘보강 결과 본문 열기’를 선택할 때 이동한다. 다른 문서 선택·로그아웃 후에는 늦은 응답이 현재 화면을 변경하지 않도록 컴포넌트를 정리한다. 숨겨진 탭에서는 상태 polling을 멈춘다. 일반 증보 실행의 후속 보강은 자동 등록된다.

Compose worker에 OC 별칭을 전달하며 기존 환경파일은 수정하지 않는다. migration 0012/0013은 새 job 종류를 추가하며 기존 migration은 변경하지 않는다.

## 실제 로컬 검증

- 관리자 로그인 → 1건 inventory → `NEW 1` delta → 상세 등록으로 `2025000022379`(2021두59908, 2025-09-18)를 수집했다. 이 신규 표본은 이미지 0건이다. 이미지 포함 신규 판례 검증 완료로 세지 않는다.
- 이미지 체인은 현재 scourt `1970841`(대법원 2009다47340)의 재취득 **1건**으로 검증했다. detail job은 `98ae40fe-a657-4ca4-93dc-3d22ddbb90c6`, image job은 `88c97733-51d8-437b-8274-32e652d0c546`, refresh job은 `4313824f-768d-4213-9e71-ca87afd88b72`다.
- 이미지 6위치 중 4위치는 검증된 2개 저장 파일을 재사용했다. image job은 SKIPPED 2 URL이며 새로운 bytes 다운로드를 수행한 것으로 세지 않는다. 나머지 2위치는 img3 제공자 매핑이 없어 PENDING이다.
- lawgo 판례 연결 후 현재 scourt 조문 표식을 보완하고 관리자 재보강 job `3cc0c64f-fda6-42bc-bb70-56a9f6f0d0db`를 실행했다. 상표법 제51조의 4개 인용 위치에 법제처 제공 표를 연결했다. 표의 시행일·법률번호는 그대로 보존하고 적용 버전은 미확인으로 표시한다.
- 최종 reader는 `8ea903fe7c339f0983d57ab289db1a9d40bae2a7860c3b3f1f619565d5180f12`다. 일반 `/api/cases/search?q=2009다47340`에서 CURRENT_SOURCE 최신 1건을 확인했다. legacy 결과는 별도로 유지된다.
- 사용자가 관리자 로그인한 브라우저에서 일반 검색 → 해당 결과의 본문 열기 → 이미지 4곳 실제 표시(naturalWidth 132/205, naturalHeight 81/75) → 미확보 2곳 표시 → 인용 클릭 → 법령 표 이동을 확인했다. 이미지 URL은 모두 내부 `/api/reader/.../images/...`다.
- 실제 API HTML 200, 4개 이미지 응답의 SHA-256 일치, 미인증 검색/HTML/이미지 401을 확인했다. 제목 조회 최적화 후 합산 검색은 약 9.32초, 호스트의 CURRENT_SOURCE 제목 쿼리는 약 0.02초였다. 본문 fallback 성능은 별도 한계다.
- 실측 응답·스크립트·job 기록은 `data/current-enrichment-audit-20260914/`에 hash 기반으로 보존했다. `verified-reader.json`이 최종 API/브라우저 결과다. lawgo 형법 제246조의 별도 1건 popup 관찰도 포함되며 그 관찰을 corpus 보강 완료로 세지 않는다.

## 신규 이미지 bytes 취득 실증 — 2026-09-14 추가

커밋 `e289c32` 이후 코드 변경 없이 로컬 Compose에서 관리자 API로 1건을 실행했다. 후보 목록 2회와 상세 구조 3건을 제한적으로 관찰한 뒤, 이미지가 확인된 대법원 2025. 11. 20. 선고 **2024도8174** 판결(scourt `2026000035319`)만 증보 등록했다.

- inventory job `f86f41c5-cd41-4b17-935c-7d6d5d19cd61`의 1건은 legacy 기준 delta에서 NEW 1건이었다.
- detail job `ca47e75a-3290-4abe-8a87-21e22894ecde` → image job `e15d064f-2ee6-405b-99cf-2bb6deb5501d` → refresh job `6b394a01-23c0-4213-a025-e0ac2cf535a1` → lawgo job `3aa2a615-762c-4346-9a1f-a59642a302e4` 모두 SUCCEEDED했다.
- image ledger에 새 ACQUIRED 시도 6건, 총 13,086바이트가 기록됐다. 재사용(SKIPPED)·실패는 0건이며 원문 이미지 6위치를 모두 연결했다.
- 기본 reader `bec8e52b3d90d11f9041fb85a74fa3905740745521e2be0eedf0ca9d702cb3a8`, 이미지 reader `838d0371fcb768a72dec0c7fb7ede4680882911a7dd685494ab08ea61295d1b1`, 최종 reader `5511243c54d51426c48e2c99ecd4d02a226cfd69738f609fee43a2d5511941fe`를 각각 보존했다. 세 revision의 기준 HTML SHA-256은 `382c4deed9e173d357b9a69109cc844cb40ff6022735530be8ed3eb5f10c3f25`로 같다. 기본 manifest는 이미지 미취득 상태로 그대로 남아 있으며, 원문 slice와 이미지 태그 6곳의 일치를 확인했다.
- lawgo 판례 `618293`이 제공한 상표법 제108조·제230조·제235조의 5개 인용 위치가 PRESERVED다. 제공된 시행일 2025-11-11을 보존하며 적용 버전은 UNVERIFIED다.
- 로그인된 실제 브라우저의 일반 검색 `2024도8174` → 결과 1건 → 최종 본문에서 내부 이미지 6곳(각 132×20)이 모두 로딩됨을 확인했다. 조문 5 클릭 후 해당 법제처 표로 이동하고 적용 버전 미확인 표시를 확인했다.
- 내부 이미지 응답 6개의 SHA-256이 manifest와 일치했다. 미인증 검색·본문·이미지 요청은 각각 401이다. 검색 응답은 약 10.13초였으며 성능 개선 필요는 남아 있다.
- 응답 원본과 job·검증 결과는 `data/current-enrichment-new-image-20260914/`에 보존했다. `chain.json`, `verified-reader.json`이 실행 근거다. 코드 변경이 없어 전체 단위 테스트·빌드는 재실행하지 않았고, 이번 변경은 실행 기록 문서에 한정한다.

## 검증 및 한계

Python ruff check/format·mypy, 실제 PostgreSQL을 포함한 전체 회귀 706건(경고 4건), pnpm lint/build, git diff --check를 통과했다. HTTP 실패/연결 미확정, 늦은 과거 revision, 재실행 idempotency, 조문 부분 실패는 합성 fixture 회귀와 실제 표본을 구분한다.

신규 등록 판례 1건의 새 이미지 bytes 취득과 일반 열람 실증은 위 추가 실행으로 완료했다. 최초 2009다47340 표본은 기존 저장 bytes 재사용이며 두 실행을 구분한다. lawgo 지원 문법은 현재 실측한 JO/prec 호출이며 다른 popup 형식·표 없는 자료·조문 내 추가 이미지 실물 취득은 확대 검증이 필요하다. 제공되지 않은 연결은 만들지 않는다. 전수 신규 lawgo 보강 완료, canonical 연결 완료, 법적 적용 버전 확인을 주장하지 않는다. commit/push·AWS 변경·정기 실행은 하지 않았다.

## 웹 재확인과 검색 캐시 — 2026-09-14 추가

- legacy 검색의 모든 컬럼·Unicode casefold·행 순서·결과 한도 계약을 유지한다. Arrow batch를 256→4096으로 조정하고 한글/숫자 literal 경로는 regex 대신 substring을 사용한다.
- 프로세스당 최대 64개의 검색 결과 tuple만 캐시한다. 전체 corpus를 메모리에 보관하지 않는다. 경로·device/inode·크기·mtime/ctime ns·검색어·한도로 구분하며 파일 교체/수정 후 재조회는 다시 스캔한다. 반환 list는 매번 분리한다. API 인증은 캐시 접근 전 그대로 적용한다.
- 로컬 합산 검색 실측: 최초 18.661초, 동일 검색 재조회 0.057초. 별도 batch 비교는 256행 19.349초, 4096행 17.718초였다. 앞선 실행의 약 10초와 환경/부하가 달라 최초 검색 개선 완료로 해석하지 않는다. 검색 전용 PostgreSQL projection/index가 다음 과제이며 CURRENT_SOURCE의 본문 fallback도 별도 개선이 필요하다.
- 실제 관리자 브라우저에서 재확인 job `8d843693-48fc-4e3e-a88a-9a4dd184d269`를 등록하고 새로고침 후 완료 상태를 복구했다. job ID가 없는 요청 ID URL로 등록 응답 유실 상태를 재현해 ‘같은 요청 확인’을 눌렀고, 동일 job을 반환하며 DB 등록 건수 1건임을 확인했다.
- 결과 reader `5809fa102337d5382213b0c997f50284a804f39d8d5ddc5e195020a2722f1e32`의 이미지 6곳·조문 5곳과 기준 HTML hash가 계승됐다. 새 본문 열기와 이미지 6곳 로딩을 브라우저에서 확인했다. 재확인 API는 미인증 401·편집자 403이며 합성 PostgreSQL 회귀에서 동일 request ID·다른 Origin 거부도 검사했다.
- 최종 실제 PostgreSQL 포함 708개 회귀, ruff check/format, mypy, pnpm lint/build, git diff --check 통과. 실측 기록은 `data/current-enrichment-new-image-20260914/web-retry.json`이다.
- 최초 회귀 중 Compose가 PostgreSQL도 재시작해 테스트 연결이 끊겼다. 영속 볼륨은 유지됐고 `compose.dev.yaml`의 loopback 55432 포트를 복구한 뒤 전체 회귀를 다시 통과했다. 실패 traceback에 로컬 DB 접속정보가 출력되어 이후 테스트 출력은 secret 마스킹을 적용했다. 환경파일은 변경하지 않았다. 이후 앱 갱신은 `--no-deps`로 DB 재시작을 피한다.
- 이 버튼은 lawgo 조문 재확인용이다. 이미지 미확보 재취득용 관리자 UI, 다른 lawgo popup 형식, 조문 내부 추가 이미지의 취득은 남은 범위다. commit/push와 정기 실행은 수행하지 않았다.

검색 전용 PostgreSQL 색인과 현재 본문 이미지 재취득 UI의 후속 구현·실측은 [검색 색인과 이미지 재취득](search-index-and-image-retry.md)을 따른다. 위의 해당 기능 미구현 표시는 당시 실행 이력이다.


신규 조문 내부 이미지의 후속 취득·reader 발급과 실제 표본 검증은 [2026-09-14 추가 기록](current-statute-images.md)을 따른다.
