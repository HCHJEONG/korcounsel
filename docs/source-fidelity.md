# Source fidelity와 artifact 보존 계약

**이미지 실물 보존 — 2026-09-10 사용자 확정:** 기존 corpus 정비·Parquet 전환의 이번 작업 범위에 이미지 참조 전수 점검, 취득 가능한 이미지 bytes 저장·검증, 원문 위치 연결 및 실패/재시도 관리를 포함한다. 신규 판례에도 URL과 실물 파일 병행 보존을 적용한다. 저장 용량은 현재 선행 장애로 두지 않으며 실측은 운영 계획을 위해 수행한다. 원문 HTML은 유지하고 이미지 파일·SHA-256·원 src/name·제공자 매핑·취득 시각·반복 위치를 manifest로 연결한다. Parquet에는 참조·상태를 담는다. 기존의 binary 취득을 먼 후속으로 미룬 범위보다 이 결정이 우선한다. OCR·이미지 해석은 별도이며 실제 전수 취득 완료를 의미하지 않는다. [확정 계약](image-preservation-review.md). 아래 Stage C의 후속 표기는 이전 계획이며 이번 범위에 포함된 것으로 갱신한다.

2026-09-09 추가 지시 반영. 텍스트 외 시각·구조 요소도 판결의 의미를 담을 수 있다. 최초 범위는 Detect → Preserve Reference이며 Acquire → Reconstruct Position → Interpret는 별도 단계다.

## 구조와 결측

Tier 1(구조화), Tier 2(전문+metadata), Tier 3(scan/image)는 처리 요구의 차이다. 법률적 중요도·정확성·gold 등급이 아니다. source 전체에 하나의 tier를 고정하지 않고 관찰한 판례 버전/representation별로 분류한다. 혼합 PDF·텍스트와 내장 이미지는 함께 존재할 수 있고 미확인 유형은 UNKNOWN이다.

issues=[], summaries=[], reasoning=None, full_text=None도 artifact와 유효한 식별/provenance를 가진 정상 LegalCase에서 허용한다. field 상태는 PRESENT/ABSENT_IN_SOURCE/NOT_FETCHED/PARSE_FAILED/UNKNOWN 등으로 구분한다. 표식만 있고 본문이 비었는지 별도로 검증한다. NO_EDITORIAL_ISSUE_DATA는 원문 확인을 통해 해당 데이터가 없다고 판단한 상태이며 모든 parser 실패의 대체값이 아니다.

구조화된 판시사항↔요지는 seed/evaluation 후보다. 부재한 경우 현재 pipeline이 추측해 만들지 않는다. full-text only는 보존·검수 경로, scan은 artifact/향후 OCR 경로로 유지한다. LegalCase 수집 성공과 gold 쟁점 생성 가능 여부는 별도다.

## Stage별 범위

| Stage | 산출물 / 경계 |
| --- | --- |
| A Detect | 제공된 HTML/XML/JSON의 image/PDF reference, artifact 유형, has_visual_assets·visual_asset_count·requires_ocr 및 detection status |
| B Preserve Reference | original_src, source page, 안전한 resolved URL, DOM locator/field, document_order, alt, before/after text, parent artifact 참조; asset manifest |
| C Acquire | binary와 별도 metadata, asset_id, MIME 검증·실제 size/hash/path, timeout/retry와 failure manifest. 후속 milestone |
| D Reconstruct Position | ordered DocumentBlock과 자산 연결, 실제 관찰 위치; 복잡한 layout engine은 최초 범위 아님 |
| E Interpret | OCR·vision·multimodal LLM 및 의미 추출. 초기 제외, 후속 별도 범위 |

SourceArtifact는 JSON/XML/HTML/PDF_TEXT/PDF_SCAN/PAGE_IMAGE/EMBEDDED_IMAGE/OTHER/UNKNOWN을 수용한다. 취득한 artifact에는 source·source_url·retrieved_at·mime_type·sha256·file_size·storage_path와 부모/순서를 둔다. 미취득 reference에는 hash·MIME·size를 만들어 넣지 않는다. 원 URL과 정규화 URL을 구분하며 credential·서명 URL은 공개 manifest/로그에 노출하지 않는다.

PDF 링크나 확장자만으로 PDF_SCAN/ requires_ocr=true를 확정하지 않는다. text layer 조사 전에는 PDF 유형/ocr 필요 여부 UNKNOWN이다. 확인된 scan은 requires_ocr=true, OCR=NOT_YET_PROCESSED로 저장한다. 내장 그림이 있다는 이유만으로 문서 전체를 OCR 대상으로 만들지 않는다.

has_visual_assets는 true/false/null과 detection scope를 함께 표현한다. null은 미확인이다. API 텍스트에 img가 없다는 사실은 실제 판결문에 그림이 없다는 증거가 아니다. count는 관찰한 reference 수이며 미확인을 0으로 꾸미지 않는다. 참조 발견, 다운로드 성공, 위치 복원, 의미 해석 상태를 분리한다.

DocumentBlock은 heading/paragraph/image/table/page_image/unknown과 안정적 block_id, order, parent artifact, text span 또는 asset reference를 수용한다. DOM 위치는 특정 artifact 버전에 종속되며 정규화된 텍스트 offset과 동일하지 않다. 누락 이미지는 원래 순서의 placeholder로 남기고 alt나 주변 문장을 이미지의 법적 해석으로 바꾸지 않는다.

## Source 취득 전략

공식 API → direct HTTP → browser-session-assisted HTTP → browser automation 순으로 실제 source의 원문 충실도와 접근 조건을 검증한다. 이 순서는 실패할 때 무조건 우회하라는 뜻이 아니다. 동적 DOM·popup·iframe·세션·download가 필요하면 browser는 정식 adapter가 될 수 있다. 현재 scourt endpoint 동작이나 자동화 허용 조건은 이번 코드 조사로 확정하지 않는다.

Playwright/Selenium 선택은 Python 3.12·uv, headless 안정성, download/popup/iframe, network/DOM/resource 추출, Windows/Linux, testability를 같은 표본에서 비교한 뒤 고정한다. 새 문서 작성 때문에 브라우저 패키지를 설치하거나 수집을 시작하지 않는다. small EC2의 worker/브라우저 메모리·CPU·디스크를 측정하고 다중 브라우저 프로세스를 기본으로 늘리지 않는다.

## 독립 실패와 검증

case ingestion=SUCCESS, visual acquisition=PARTIAL_FAILURE, OCR=NOT_YET_PROCESSED를 함께 표현할 수 있다. 이미지 한 건 실패로 판례 전체를 폐기하지 않는다. 반대로 시각자료가 중요한 evidence인데 확보되지 않은 issue를 complete gold로 표시하지 않는다. gold eligibility는 identity·text evidence·필요 visual evidence·fidelity 상태를 별도로 평가하고 부족하면 후보로 남긴다.

취득 URL은 허용 source·scheme/redirect를 검증하고 SSRF·경로 탈출·무제한 다운로드를 막는다. 보존 HTML을 실행하거나 임의 remote image를 검수 UI에서 자동 로드하지 않는다. raw와 reference는 유지하되 인증된 viewer에는 안전한 파생 표현을 제공한다. 이 보존 정책은 원문·DB와 함께 백업/복구해야 한다.


## Legacy bootstrap 관찰

최종 corpus 89,130행 모두 저장 HTML 문자열·추출 문자열이 있으나 이것이 원문 완전성을 보증하지 않는다. 판시사항/요지 부재와 숫자 0 sentinel이 실제 존재하며 parser 부재/실패 여부를 mapper에서 구분해야 한다. 보강된 HTML, lnfd 표식이 있는 추출 필드, 실제 HTTP 원본 bytes를 같은 representation으로 취급하지 않는다. 표본 img 태그에는 장식이 포함될 수 있고 외부 image URL의 현재 취득 가능 여부는 확인하지 않았다. 기존 자료를 보존한 후 탐지·fidelity 검증을 덧붙인다.

## 이미지 주소와 조문 보강

scourt 상대 src를 scourt 절대주소로 보완한 실제 전후 표본과 lawgo jtable 삽입을 [전략 보고서](legacy-enrichment-and-incremental.md)에 기록했다. 이는 이미지 binary 다운로드나 전체 fidelity 검증이 아니다. 기본 HTML·조문 source artifact·보강 HTML을 분리하고 원래 src/base/해석 URL과 위치를 보존한다.
