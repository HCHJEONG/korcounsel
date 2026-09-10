# Step 3A 후속 — 목록·레거시·현행 원문 비교

2026-09-10 사용자 승인 범위: OC 차단 제거, 현재 scourt 목록 구현, 레거시 대비 대표 표본 확대. 전체 재수집·기존 registry 재연결·corpus import·AWS 변경은 하지 않았다.

## 결과

1. 법제처 OC 응답 저장 차단을 제거했다. OC가 포함된 목록 원본을 그대로 보존한다. JSON/XML에서 2017도953의 첫 페이지 1건과 다음 빈 페이지를 확인했다. 요청 URL 요약의 OC 생략과 config의 SecretStr wrapper는 출력 형식 선택일 뿐 응답 저장 금지가 아니다.
2. scourt 현재 목록 POST, 페이지·건수·중복·total 변화 검사와 per-ID metadata hash·scope hash·원본 페이지 연결을 구현했다. 사건번호 검색 2건의 페이지 이동과 일반 목록 3페이지·15건을 실제 확인했다.
3. 기존 ID 12개를 조사했다. scourt 11개는 기존 ID로 취득됐고 1개는 제공자의 notExtist 응답이었다. 법제처 기존 ID 2개도 명시적 미조회 응답을 보였다. 모두 실패 원본을 보존하고 SOURCE_NOT_FOUND로 분류하며 공식 철회·삭제로 단정하지 않는다.
4. 원본의 제공자 매핑으로 이미지 참조를 복원한다. 중앙해양안전심판원 표본 2029039의 34개 이미지 위치를 실제 브라우저와 대조했다. 33개 파일이 34곳에서 사용되며 반복 위치를 보존한다.

[실측 전체](step3a-validation.json), [이미지 브라우저 관찰](step3a-image-browser.json), [검증 요약](step3a-verification.json), [Compose 결과](step3a-compose-verification.json)를 함께 읽는다.

## ID가 유지되는 경우와 바뀐 후보

| 기존 source ID | 현재 관찰 | 처리 |
| --- | --- | --- |
| scourt 2064767 / 2063727 | 같은 2008재도11 아래 서로 다른 날짜의 전원합의체 판결·결정 | 개별 문서 구분 유지 |
| scourt 2036595 / 2036768 | 같은 2001나60578의 판결·중간판결 | 강제 병합하지 않음 |
| scourt 3325500 | csNoLstCtt=2020다296741, mrgCsNoCtt=2020다296741, 296758 | 대표 번호와 병합 번호를 함께 보존 |
| scourt 2061329 | 기존 ID 미조회, 85후40 검색으로 2025000017702 후보 발견·상세 취득 | REVIEW_REQUIRED, registry 변경 없음 |
| lawgo 194079 | 기존 ID 미조회, 607465 후보 상세는 85후40, 41 | 추가 병합 번호까지 대조 필요 |
| lawgo 192890 | 기존 ID 미조회, 601365 후보 상세는 82도2078 | REVIEW_REQUIRED, registry 변경 없음 |

새 후보들의 법원·대표 사건번호·선고일을 확인했지만 전체 후보/본문에 대한 identity resolver를 실행한 것은 아니다. 과거 ID를 삭제하거나 새로운 ID로 덮어쓰지 않는다. 기존 저장본을 우선 수용하고 신규 연결 revision을 남기는 후속 정책이 필요하다. 검색 결과는 본문 인용도 포함하며 강조용 HTML이 사건번호에 붙기도 한다. 첫 결과·substring만으로 연결하지 않는다.

## 이미지 접근 방식의 실제 변화

레거시 2029039에는 다음 형태의 src가 있다.

    /wsjo/cm/imgDownload.do?contId=2029039&attachImgNm=11w0401-009-01.gif

현재 selectJdcpctCtxt.on의 orgdocXmlCtt에는 src 없는 img name 표식과 contImagePath 클래스의 name/value 매핑이 들어 있다. 공식 화면 PGP1011M04.xml의 처리와 브라우저 DOM을 확인했다. 현재 URL 형태는 다음과 같다.

    /pgp/pgp003/downloadImgFile.on?pgmId=PGP1011M04&jisCntntsSrno=2029039&atchImgFileNm=11w0401-009-01.gif

documents/observe.py는 원래 src 부재, img name·순서, 제공된 파일명 목록과 해석 URL을 별도로 기록한다. 원본 HTML에는 src를 써 넣지 않는다. 동명 매핑이 상충하면 URL을 추정하지 않는다. 34곳 전체가 브라우저의 주소·순서와 일치했고 브라우저에서는 로드됐다. KorCounsel의 binary archive 취득·내용 검증·OCR 완료를 의미하지 않는다. 이 기관의 재결을 법원 판결로 일괄 분류하지 않는다.

이 매핑을 HTTP 원문에서 읽을 수 있으므로 현재 범위에는 browser runtime 의존성을 추가하지 않았다. 브라우저는 현행 경로·fidelity 확인에 사용했다. 나중에 실제 browser runtime이 필요해지면 Selenium/Playwright를 비교한다.

## 레거시 본문 비교의 범위

명시적 archive root 아래 20240723·20241126 파일을 읽었다. metadata projection과 기존 보강 HTML을 보존하고 대형 pickle을 다시 읽지 않았다. 과거 파일이 없는 표본은 본문 비교 미실행으로 남겼다.

비교 가능한 HTML은 markup/text hash·길이·이미지·조문 연결·jtable 표식을 관찰했다. 여러 표본의 레거시 UI 경고 이미지가 현재 API 본문에는 없으며, 전체 text hash도 다르다. 이 차이를 법률 내용 손실이나 완전한 동일성으로 자동 판정하지 않는다. 과거 jtable 보강과 현재 기본 본문은 서로 다른 representation이다. 본문 영역만 분리한 정밀 비교와 gold/evidence 적합성 검증은 후속이다.

## 목록 snapshot과 worker

- 신규 migration 0006은 FETCH_SCOURT_INVENTORY와 DOCUMENT_OBSERVATION/INVENTORY_PAGES manifest 종류를 추가한다. 이미 적용된 0001–0005는 변경하지 않았다.
- CLI: klegal ops submit-scourt-inventory REQUEST_KEY --query QUERY --max-pages 2 --display 5. query 생략은 현재 관찰한 판례 검색 category 범위이며 다른 모든 포털 자료를 뜻하지 않는다.
- 최대 10페이지·페이지당 최대 100이라는 앱 한도를 둔다. live는 1·5건 크기로 검증했고 모든 크기를 공식 보장한다고 주장하지 않는다.
- 완료한 페이지마다 snapshot과 페이지 원본 hash를 저장한다. 단일 worker·lease·drain·idempotency 정책을 공유한다.
- 제한에 도달하면 PARTIAL이다. 보고된 모든 행을 받았어도 제공자 고정 snapshot token이 없으므로 UNKNOWN이며, COMPLETE로 승격하지 않는다. 작업 SUCCEEDED는 요청한 제한 관찰의 성공이지 전체 목록 완전성이 아니다.
- 중단 시 완료 페이지는 남긴다. 재시도는 새 bounded observation을 1페이지부터 만들며 변하는 검색 결과를 과거 snapshot에 이어 붙이지 않는다. 대규모 cursor/checkpoint·delta·ledger 통합은 Step 4A 후속이다.
- per-ID hash는 버전이 명시된 식별·metadata 필드 집합에 기반한다. popularity·검색 snippet·HTTP envelope timestamp가 바뀌었다고 법률 본문 변경으로 판단하지 않는다.

## 재현과 검증

backend에서 uv 품질 명령을 실행한다. 실제 PostgreSQL 테스트는 임시 test schema를 만들고 자기 schema만 정리한다. 운영 DB·기존 데이터 reset은 하지 않는다.

제한 live audit는 명시적 KLEGAL_ENV_FILE과 함께 scripts/validate_source_paths.py --legacy-root /mnt/i/VSCodeBases/web2df/saved를 사용한다. 이 Windows/WSL 경로는 조사자가 고른 입력이며 앱 runtime 필수값이 아니다. 보고서는 최신 실측으로 갱신되고 raw 파일은 hash 경로로 보존한다. 이번 실행 뒤 추가한 후보 상세·브라우저 대조는 보고서의 별도 항목이다.

기존 185건에서 목록·원본·미조회·15종 HTML 진단·중복 매핑·DB worker 회귀를 추가했다. 최종 수치는 검증 요약에 기록한다. 기존 upstream warning 2건은 별도로 남아 있다.

## 남은 범위

- 기존 corpus 보존 import, old/new source ID 연결 검토 이력, 안정된 metadata 정규화 및 delta/refresh ledger 연결.
- 법률 본문 영역의 정밀 비교, source 제공 조문 보강의 항목별 재현, image binary 보존.
- PDF/scan 실물, 운영 부하·메모리 측정, 전체 corpus나 전체 inventory의 완전성 검증. 이번 표본 결과를 운영 부하 검증으로 확대하지 않는다.
