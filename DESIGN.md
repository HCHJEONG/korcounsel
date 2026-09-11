# KorCounsel Design Direction

이 문서는 제품 UX와 시각 설계 기준이다. 구현 순서·범위·완료 상태는 루트 PLAN.md를 따른다. 아래 화면과 컴포넌트는 구현 목표이며 현재 동작하는 기능이라는 뜻이 아니다.

인접 onju-ai-kr/DESIGN.md의 전문 법률 업무 화면, 절제된 색상, 문서 중심 3단 구조, 근거 검수, 정확한 revision 선택, 응답 불확실성 처리와 접근성 원칙을 최대한 계승했다. 대상 업무는 법령 주석 생성·출판에서 판례 데이터 생산·검수로 변경한다.

## 제품 성격과 범위

- 소수 사용자가 반복적으로 판례를 읽고 추출·연결 결과를 검수하는 업무 도구다.
- 주요 사용 흐름은 실행 선택 → 오류/검토 목록 → 판례 원문 → 쟁점/답변/근거 대조다.
- 로그인 후 첫 화면은 실제 작업 대시보드다. 공개 마케팅 페이지, 법률 상담 chatbot, 주석 열람 portal로 만들지 않는다.
- korcounsel.com은 일반 HTTPS 접속 경로이며 비공개 데이터에 대한 인증을 생략하는 이유가 아니다.
- Phase 1은 작업 등록·진행 조회와 읽기 중심 내용 검수, Phase 1.5는 사람의 수정·승인·반려·보류·실행 비교다.
- 구현하지 않은 메뉴나 버튼을 동작하는 것처럼 노출하지 않는다. 미래 메모·북마크·채팅·AI draft·email·출판 기능을 현재 필수 UI로 늘리지 않는다.

## 참조 충실도와 차별화

계승할 원칙:

- 문서가 중심인 3단 layout, 조밀한 목록/목차, 작은 toolbar와 명확한 선택 상태.
- 텍스트 중심, 얇은 경계선, muted palette, 작은 badge와 절제된 강조.
- 문서 내 검색, 원문 위치 이동, evidence와 인용 정보의 병렬 확인.
- immutable history, 정확한 검토 대상, 기존 결과와 변경안의 비교.
- 상위 메뉴 링크, 좁은 화면의 panel 전환, 키보드 접근성.

복제하지 않을 요소:

- Onju/LawnB/Thomson Reuters의 상표·로고·아이콘·고유 시각 자산·주석 텍스트.
- 공개 guest reader, 법령별 commentary 목차, AI 영향 분석·초안·출판 workflow.
- 참조 프로젝트의 실제 사용자·원고·대화·데이터·구현 완료 기록.

전문 법률 데이터베이스의 읽기 ergonomics를 참고하되 사용자가 출처·검증·원문을 판단하기 쉬운 구조로 바꾼다. 외부 브랜드와의 제휴나 법률적 정확성을 암시하지 않는다.

## 시각 원칙

- 차분하고 실무적인 한국어 문서 화면을 만든다. 화면 밀도와 글자 가독성을 함께 유지한다.
- white/off-white 문서, neutral 배경, dark 본문, restrained blue를 사용한다.
- 큰 hero, 장식용 gradient, glassmorphism, oversized KPI card, playful animation, nested cards를 피한다.
- 색이 넓은 면을 채우기보다 링크·선택·상태를 설명하게 한다. shadow보다 border·간격·행 상태로 구조를 표시한다.
- 긴 판례 본문은 기본 16~18px 범위, 목록·보조 조작은 대략 13~14px 범위부터 검증한다. 이는 초기 설계값이며 실제 화면에서 조정한다.
- 한국어 문단은 충분한 행간과 안정적인 읽기 폭을 유지한다. 전체 폭을 채우기 위해 본문을 과도하게 늘리지 않는다.

## 색상 token

| token | 초기 값 | 용도 |
| --- | --- | --- |
| page-bg | #f4f5f7 | 앱 배경 |
| panel-bg / document-bg | #ffffff | panel·문서 |
| border-subtle | #e1e4e8 | 행·영역 경계 |
| border-strong | #c8ced6 | 중요한 분리선 |
| text-primary | #1f2933 | 본문·제목 |
| text-secondary | #5f6b7a | 보조 설명 |
| text-muted | #8a96a3 | 비필수 장식·비활성 보조 요소, 작은 필수 텍스트에는 사용하지 않음 |
| accent-primary | #1f5f9f | 링크·선택·주요 액션 |
| accent-soft-bg | #eef5fb | 약한 강조 |
| active-row-bg | #eaf3fb | 선택 행 |
| hover-row-bg | #f3f7fa | hover |
| warning | #b7791f | 검토 필요·연결 모호, pale amber 배경 |
| destructive | #b42318 | 오류·반려·파괴 작업, pale red 배경 |
| success | #1f7a4d | 실제 통과·검토 승인, 의미를 텍스트로 구분 |

색상은 초기 token이다. 실제 foreground/background 조합의 대비를 검증하고 읽기 어려운 보조 텍스트는 더 진하게 조정한다. 자동 통과와 사람의 승인에 같은 색을 사용하더라도 label과 별도 상태 열로 반드시 구분한다.

## 화면 구조와 탐색

제안 route는 구현 시 최종 고정하되 안정적인 직접 링크와 상위 이동을 보장한다.

| 화면 | 제안 경로 | 핵심 작업 |
| --- | --- | --- |
| 로그인 | /login | 허용 계정 인증 |
| 대시보드 | / | 최근 실행, 검토 대상·오류와 작업 진입 |
| 실행 목록/상세 | /runs, /runs/:runId | 입력·버전·상태·건수·로그 요약 |
| 판례 검수 | /cases/:caseVersionId | 원문·구조·추출 결과 대조 |
| 쟁점 검수 | /issues/:issueUnitId | 쟁점·답변·근거·검증 사유 |
| dataset | /datasets/:datasetVersion | 포함 기준·manifest·허용 export |

- AppHeader는 제품명, 주요 작업 메뉴, 운영 상태와 계정 메뉴를 제공한다.
- 모든 secondary page 상단에 상위 메뉴 landmark와 안정적인 내부 링크를 둔다. history.back만 사용하지 않는다.
- 목록 filter·검색·선택 context는 URL에 안전하게 유지할 수 있다. 비밀번호·token·비공개 메모 본문은 URL에 넣지 않는다.
- 과거 revision 링크는 정확한 버전을 고정한다. 새 버전이 있어도 조용히 최신 내용으로 교체하지 않는다.
- 로그인 후 허용된 원래 내부 경로로 돌아간다. 외부 redirect를 허용하지 않는다.

## 대시보드

- source record·canonical 판례·구조화/full-text/scan·쟁점·gold 수를 구분하고 identity·inventory delta/완전성·asset 부분 실패를 별도로 집계한다.
- 각 수치는 같은 run/dataset 범위를 사용하고 집계 기준을 표시한다. 전체 누적과 최근 실행을 혼합하지 않는다.
- 상태 수치를 누르면 해당 filter가 적용된 목록으로 이동한다.
- 오류 유형, 근거 미확보, ambiguous/unmatched를 우선 탐색할 수 있게 한다.
- 자동 aligned 표본도 검수 대상에서 찾을 수 있게 한다. 오류 항목만 보는 흐름으로 고정하지 않는다.
- 차트는 유형 분포나 실행 비교에 필요한 경우에만 추가한다. 숫자 카드만 나열하는 화면으로 끝내지 않는다.
- 최근 실행에는 시작/종료 시각, 실행자, 상태, 입력 범위, 처리 단계와 상세 링크를 둔다.
- 일반 사용자에게 instance ID, hash, parser internals를 상시 노출하기보다 관련 상세 영역에 둔다. 검수 판단에 필요한 source·버전은 명확히 표시한다.

## 3단 판례 검수 화면

### 왼쪽 — 목록과 문서 구조

- 실행·법원·기간·사건번호·연결 상태·품질 상태 filter를 제공한다.
- 판례 목록은 행 중심이며 법원, 날짜, 사건번호, 짧은 제목, 상태를 표시한다.
- 선택 source version에 실제 존재하는 section·document block·asset reference를 표시한다. editorial 데이터가 없으면 정상 안내와 전문/artifact 보기로 연결한다.
- 병합 사건번호와 긴 제목은 상세 확인 경로를 유지한다. 중요한 식별자를 말줄임만으로 숨기지 않는다.
- pagination과 결과 수를 표시하며 데이터 전체를 한 번에 내려받지 않는다.

### 가운데 — 원문과 변환 비교

- 법원·선고일·사건번호·판결/결정·사건명, source와 판례 버전을 표시한다.
- 원문 / 정규화 / 구조화 보기로 전환한다. 원문은 보존한 기준 텍스트이며 편집할 수 없다.
- 규칙이 삭제·추가·변환한 부분을 표시하고 주변 문맥을 남긴다. 형식 정리를 법률 내용 변경으로 표현하지 않는다.
- 검색 match와 evidence 강조는 시각적으로 구별하고 문맥으로 이동한다.
- 원문 toolbar는 글자 크기, 문서 내 찾기, 기준 버전·출처 확인 등 실제 지원 기능만 제공한다.
- 긴 문서에서 선택 쟁점을 바꿀 때 읽기 위치와 새 evidence 이동을 예측 가능하게 처리한다.

### 오른쪽 — 쟁점·답변·근거와 상태

- issue_original/normalized와 answer_original/normalized를 대조한다.
- alignment 상태, 적용 규칙·사유, 자동 품질 검증, 사람 검토 여부를 각각 표시한다.
- evidence 목록에 요지/이유 유형, 발췌, 위치 유효성, 원문 이동을 제공한다.
- authority는 해당 판례 전체 인용인지 특정 쟁점에 직접 연결됐는지 구분한다.
- provenance 상세에서 source ID/URL, 수집 시각, raw hash, 규칙·schema·dataset 버전을 확인할 수 있게 한다.
- offset 또는 원문 연결이 없으면 근거 없음/위치 미확보 사유를 보여준다. 임의 구절을 강조하지 않는다.

## 상태와 용어

| 구분 | 표현 예시 | 주의점 |
| --- | --- | --- |
| 작업 실행 | 대기, 실행 중, 종료 준비, 완료, 실패, 재개 대기 | 실제 처리 상태와 HTTP 응답 상태를 구분 |
| Alignment | 연결됨, 연결 모호, 미연결 | 연결됨이 내용 정확성을 보증하지 않음 |
| 자동 품질 | 자동 검증 통과, 검토 필요, 검증 실패 | 사람의 승인으로 표시하지 않음 |
| 사람 검토 | 미검토, 검토 승인, 반려, 보류 | Phase 1.5 구현 후 실제 기록이 있을 때만 사용 |
| Dataset | 후보, gold 포함, 제외 | 포함 정책·버전·근거 수준을 표시 |
| Evidence | 판결요지 근거, 판결이유 근거, 위치 미확보 | 근거 종류와 위치 유효성을 구분 |

- 부정확한 최종 답변, 법률 결론 확정, AI 변호사, 정확성 보장 문구를 사용하지 않는다.
- 실패 후보가 보존됐다는 사실을 명확히 하고 검증 실패를 원본 삭제처럼 표현하지 않는다.
- 짧은 label과 상세 사유를 함께 제공한다. 중요한 상태는 색·아이콘만으로 전달하지 않는다.

## 검색과 관련 자료

- 목록 검색과 문서 내 검색을 구분한다. 현재 run/dataset 범위, 검색 결과 수와 표시 한도를 알린다.
- 결과 선택 시 해당 판례/section과 match로 이동한다. 키보드로 결과와 원문을 오갈 수 있게 한다.
- 초기 검색은 PostgreSQL 기반 metadata·indexed text 검색을 사용한다. 한국어 검색 품질과 성능을 확인하고 모든 형태소 검색이 기본 제공된다고 가정하지 않는다.
- 참조판례·참조조문은 원문 인용과 연결된 내부 자료를 구분한다. 내부에 수집되지 않은 자료를 검증된 연결처럼 표시하지 않는다.
- 외부 source 링크는 안전한 URL만 허용한다. 파일 다운로드는 API에서 권한 확인 후 제공한다.

## 작업 등록과 진행 조회

- 입력 범위, limit, source, 실행할 단계, 기존 결과 재사용/refresh 정책을 제출 전에 표시한다.
- 등록 시 job ID를 받고 목록·상세에서 진행 상태를 조회한다. 브라우저를 닫아도 작업은 worker에서 계속된다.
- double-click/응답 유실 시 같은 요청 식별자를 유지한다. 확인되지 않은 제출을 자동으로 새 작업으로 재등록하지 않는다.
- 응답 불확실 상태에서는 저장/등록 결과 확인과 명시적인 동일 요청 재시도를 제공한다.
- 화면을 읽는 것과 worker 상태 변경을 분리한다. 탭이 숨겨지면 불필요한 polling을 멈추고 복귀 시 갱신한다.
- 로그는 stage와 안전한 오류 요약을 표시하고 secret·DB URL·raw traceback을 그대로 사용자에게 노출하지 않는다.
- 완료·일부 실패·전체 실패를 구분하고 저장된 결과 및 보고서로 이동할 수 있게 한다.

## 운영 시간 UI

- 운영일은 한국 시간 월~금 10~17시이며 공휴일 제외는 아직 범위가 아니다.
- 17시 종료 준비 중에는 새 작업 실행 버튼을 비활성화하고 진행 중 작업·저장 상태를 보여준다. API도 동일 정책을 강제한다.
- 실제 종료가 유예될 수 있음을 간단히 알리고 작업이 끝났다는 표시를 서버 중지 완료와 혼동하지 않는다.
- EC2가 완전히 꺼지면 해당 앱의 안내 화면도 제공할 수 없다. 외부 서비스가 없는 상태에서 상시 운영 안내 페이지나 자동 시작 버튼을 설계하지 않는다.
- 앱의 시작 요청 시각과 실제 접속 가능 시각을 구분한다. 부팅 지연을 무조건 장애로 표시하지 않는다.

## Phase 1.5 검토·수정 흐름

- 선택한 정확한 쟁점 revision, 원본 버전과 evidence를 고정하고 수정 이유·기존값·제안값을 표시한다.
- 쟁점 연결 수정, evidence 재선택, 승인·반려·보류는 별도 명시적 액션이다. 단순 열람이나 export로 승인하지 않는다.
- 이전 자동 결과를 덮어쓰지 않고 사람의 변경 snapshot 및 검토 기록을 보존한다.
- 편집 중 대상 변경은 입력 손실을 설명하고 명시적으로 처리한다. 저장 결과 불확실 시 context를 고정하고 reconciliation/동일 요청 재시도를 제공한다.
- 과거에 승인했더라도 원본·규칙·내용이 달라졌으면 새로운 검토 대상으로 표시한다.
- 실행 비교는 같은 판례/쟁점 identity에 대해 내용·연결·evidence·검증 상태가 어떻게 달라졌는지 보여준다.
- 최종 dataset export와 개별 record 검토는 별도 사건으로 기록하며 변경 이력의 검토자·시각·사유를 확인할 수 있게 한다.

## 컴포넌트 방향

- AppHeader, AccountMenu, OperatingStatus, ParentNavigation.
- RunSummary, RunList, JobCreateForm, JobProgress, ErrorReportTable.
- WorkbenchLayout, CaseFilter, CaseList, CaseStructureTree.
- DocumentToolbar, FontSizeControl, SourceTextView, NormalizedDiffView, SearchMatchNavigation.
- IssueAnswerPanel, AlignmentBadge, QualityBadge, ReviewBadge, EvidenceList, AuthorityList, ProvenanceDetails.
- Phase 1.5: ReviewActionBar, RevisionComparison, ReviewHistory, ExactRevisionConfirmDialog.

이 목록은 역할 분해의 지침이다. 빈 컴포넌트를 일괄 생성하지 않는다. 행·table·tab·accordion·split pane을 우선하며 toast는 짧은 결과 알림에만 사용한다.

## 반응형과 접근성

- Desktop: 왼쪽 목록·중앙 문서·오른쪽 검수 3단. 중앙 읽기 면적을 우선하고 부가 panel은 접거나 크기를 조절할 수 있게 한다.
- Narrow/tablet: 왼쪽은 접고 오른쪽은 tab/drawer로 전환한다. 동일 본문을 중복 렌더링해 메모리를 낭비하지 않는다.
- Mobile: 목록 / 원문 / 검수 segment로 전환한다. 세 panel을 동시에 축소하지 않으며 긴 표는 필요한 열부터 재구성한다.
- 버튼·아이콘에는 접근 가능한 이름과 tooltip, keyboard focus를 제공한다. panel 전환 후 focus 위치를 예측 가능하게 유지한다.
- semantic heading, nav landmark, form label, 상태 텍스트를 사용한다. 로딩·오류·빈 목록을 구분한다.
- 긴 원문과 한글 입력, 병합 사건번호, 괄호·기호·비BMP 문자, 확대·좁은 화면을 검증한다.
- 원문 강조는 Python code point offset과 JavaScript 문자열 인덱스의 차이를 고려하고 실제 text slice와 일치해야 한다.
- 계정 변경·logout 시 private cache를 지우고 늦게 도착한 이전 요청이 다른 계정 화면을 채우지 않게 한다.

## 인증 화면과 제품 문구

- 차분한 제품명, 로그인 ID/비밀번호, 로그인 동작, 계정 안내와 오류·loading 상태를 제공한다.
- 계정 발급·비밀번호 재설정 경로는 구현된 운영 방식만 설명한다. 공개 회원가입이나 email 발송이 없는 상태에서 해당 버튼을 만들지 않는다.
- 로그인 화면에서 데이터 목록이나 검토 결과를 가져오지 않는다. 로그인 후 허용된 원래 context로 이동한다.
- 설명 문구는 공개 판례 데이터 생산·검수, 원문 근거 확인, 자동 검증, 사람 검토처럼 실제 기능에 맞춘다.
- About/도움말에는 데이터 출처와 자동 검증의 한계를 짧게 알린다. 반복적인 경고 배너로 문서 읽기를 방해하지 않는다.

## 구현과 검증 기준

- React UI 상태와 서버의 작업·검토 상태를 분리한다. 새로고침 후에도 job/검토 상태는 PostgreSQL에서 복구된다.
- typed API wrapper는 FastAPI OpenAPI 계약을 따른다. 화면에서 독자적인 gold 포함·권한·종료 정책을 정의하지 않는다.
- 프런트는 Vite production build를 정적으로 배포하며 Next route handler/Server Actions를 전제로 설계하지 않는다.
- 목록은 pagination, 문서는 필요한 범위 fetch, polling은 제한한다. 작은 EC2와 긴 판결문에서 실제 응답·메모리를 검증한다.
- 최소 브라우저 검증: 로그인/권한, 목록 filter, 직접 링크·새로고침, 원문 검색·근거 강조, 작업 등록·진행·실패, 계정 전환, 종료 준비 상태, 반응형.
- Phase 1.5 검증: 정확한 revision 고정, 입력 보호, 불확실 요청 확인, 승인·반려 이력과 변경 후 승인 미승계.

## onju-ai-kr에서의 주요 변환

| 참조 개념 | KorCounsel 적용 |
| --- | --- |
| 법령·주석 목차 | 판례 목록·판시사항/요지/이유 구조 |
| 중앙 주석 reader | 원문·정규화·구조화 비교 |
| AI/evidence/reviewer workspace | 쟁점·답변·원문 근거·검증 사유 |
| commentary version·publication | 판례/쟁점 revision·dataset release·검토 이력 분리 |
| 정확한 submission과 uncertain save 처리 | 정확한 issue revision과 job request identity |
| 역할별 공개 reader | 인증된 소수 사용자용 대시보드 |
| 제한된 색상·3단 레이아웃·상위 이동 | 그대로 계승하되 판례 검수 동선으로 조정 |
| Next.js frontend | React 19 + Vite + TypeScript SPA |
| SES·대화·원고 업로드·AI 초안·출판 | 현재 범위에서 제외 |

## Identity·inventory·source fidelity UX

- canonical 판례 상세 안에서 scourt/lawgo source ID와 정확한 source version을 선택한다. 버전별 원문을 임의로 합친 “완전 원문”을 만들지 않는다. source 선택 시 evidence도 그 artifact에 맞춰 표시한다.
- identity EXACT/HIGH_CONFIDENCE/AMBIGUOUS/UNMATCHED/CONFLICT는 issue alignment와 별도 badge다. 필드별 비교·충돌·사유를 열어 볼 수 있고 규칙 점수를 정확도 확률처럼 표시하지 않는다. Phase 1은 읽기, 연결 수정·merge/split은 Phase 1.5 이력 작업이다.
- inventory 상세에는 source·검색 범위·관찰 시각·완전성·NEW/UNCHANGED/CHANGED/MISSING·실패 page와 재개 상태를 보여준다. metadata 미변경을 본문 최신성 보장으로 표시하지 않는다.
- 작업 등록에서 신규 취득과 기존 ID refresh를 구분한다. 선고일 filter와 신규 등록 기준을 혼동하지 않도록 입력 범위를 설명한다.
- 구조화 데이터 없음, 아직 미취득, 파싱 실패, source 누락은 서로 다른 정상/오류 상태다. 이유만 있는 판례나 scan은 전문/artifact 중심 검수 흐름을 제공한다.
- 문서의 알려진 순서에 image placeholder를 두고 원래 참조·alt·전후 문맥·미확보 사유를 보여준다. asset 미취득 시 깨진 이미지 아이콘이나 생성된 대체 그림을 사용하지 않는다.
- PDF 유형 미확인·OCR 필요·OCR 미처리를 구분한다. 아직 없는 OCR 실행·해석 버튼은 노출하지 않는다. source tier는 품질 순위로 표시하지 않는다.
- 원문 HTML은 안전한 파생 viewer로 보여주고 script·임의 remote asset을 자동 실행/로드하지 않는다. asset 파일은 권한 있는 API 경로로 제공한다.
- case ingestion 성공과 visual acquisition 부분 실패가 동시에 보일 수 있다. 필요한 visual evidence가 부족한 gold 제외 사유를 쟁점 상세에서 설명한다.
- source/identity revision 변경은 기존 승인/검토 대상에 반영하되 과거 release와 직접 링크는 그대로 유지한다.

추가 브라우저 검증: source/version 전환, 정상 no-editorial/full-text/scan 화면, reference-only 이미지 문맥·순서, UNKNOWN 표시, identity 복수 후보·충돌, 부분 snapshot·asset 실패, 과거 identity revision 링크. canonical/source/issue 수를 혼동하지 않는 집계도 확인한다.

## 보존 이미지가 포함된 판례 본문 — 2026-09-11 사용자 확정

판례 열람은 다운로드하여 보존한 이미지를 본문 내 원래 위치에 함께 표시하는 것을 완료 기준으로 한다. 문단·표·이미지의 순서와 반복 등장을 유지한다. 기준 HTML을 보존하면서 안전한 열람 표현을 만들고, 이미지 파일은 인증된 내부 경로로 제공한다. 미취득·실패·연결 미확정 이미지는 해당 위치에 상태를 표시한다. 실제 판례를 검색하여 열고 외부 제공자 접속 없이 보존 이미지가 표시되는 브라우저 검증이 필요하다. 상세 계약과 미완료 범위는 docs/image-preservation-review.md를 따른다.
