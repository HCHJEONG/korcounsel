# docs 안내

Step 0 완료일: 2026-09-09. 구현과 함께 필요한 문서를 추가하고 실제 상태를 갱신한다. 미래 문서를 빈 내용으로 생성해 완료로 표시하지 않는다.

| 현재 문서 | 내용 |
| --- | --- |
| [migration-from-legacy.md](migration-from-legacy.md) | 원 지시서 36항의 아홉 분석 항목, 규칙 판정표, 회귀 fixture 연결 |
| [law-open-api-contract.md](law-open-api-contract.md) | 공식 API 계약·인증 alias·실측·미확인 조건 |
| [step0/api-smoke.json](step0/api-smoke.json) | credential 없는 네 건의 조회 metadata와 원본 hash |
| [step0/legacy-source-manifest.json](step0/legacy-source-manifest.json) | 분석 당시 레거시 루트 Python 파일 hash·행 수 |

[회귀 fixture](../tests/fixtures/legacy/regression-cases.json)는 합성 입력·기대 계약이며 구현 단계의 테스트로 연결해야 한다. 실제 원본 응답은 Git에서 제외하는 data/raw에 일부만 보존했으며 상세 범위는 API 메모에 기록했다.

루트 [PLAN.md](../PLAN.md)가 단계와 완료 기준, [README.md](../README.md)가 사용자 진입점, [AGENTS.md](../AGENTS.md)가 작업 지침, [DESIGN.md](../DESIGN.md)가 UX 기준이다. 구현 단계에 architecture.md, dataset-schema.md, provenance.md를 작성하고 실제 배포 준비 때 deployment.md와 operations.md를 추가한다. 현재 앱·DB schema·운영 명령이 구현되어 있다고 설명하지 않는다.
