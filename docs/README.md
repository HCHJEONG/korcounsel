# docs 안내

Step 0 및 추가 조사 반영일: 2026-09-09. 구현과 함께 필요한 문서를 추가하고 실제 상태를 갱신한다. 미래 문서를 빈 내용으로 생성해 완료로 표시하지 않는다.

| 현재 문서 | 내용 |
| --- | --- |
| [migration-from-legacy.md](migration-from-legacy.md) | 원 지시서 36항의 아홉 분석 항목, 규칙 판정표, 회귀 fixture 연결 |
| [law-open-api-contract.md](law-open-api-contract.md) | 공식 API 계약·인증 alias·실측·미확인 조건 |
| [step0/api-smoke.json](step0/api-smoke.json) | credential 없는 네 건의 조회 metadata와 원본 hash |
| [step0/legacy-source-manifest.json](step0/legacy-source-manifest.json) | 분석 당시 레거시 루트 Python 파일 hash·행 수 |

[회귀 fixture](../tests/fixtures/legacy/regression-cases.json)는 합성 입력·기대 계약이며 구현 단계의 테스트로 연결해야 한다. 실제 원본 응답은 Git에서 제외하는 data/raw에 일부만 보존했으며 상세 범위는 API 메모에 기록했다.

루트 [PLAN.md](../PLAN.md)가 단계와 완료 기준, [README.md](../README.md)가 사용자 진입점, [AGENTS.md](../AGENTS.md)가 작업 지침, [DESIGN.md](../DESIGN.md)가 UX 기준이다. architecture.md, dataset-schema.md, provenance.md는 추가 지시로 설계 계약을 먼저 작성했으며 구현 시 실제 schema와 동기화한다. 실제 배포 준비 때 deployment.md와 operations.md를 추가한다. 현재 앱·DB schema·운영 명령이 구현되어 있다고 설명하지 않는다.

## 추가 지시 문서

| 문서 | 역할 |
| --- | --- |
| [legacy-case-identity-and-assets.md](legacy-case-identity-and-assets.md) | 지시서 A–G 실제 코드·저장 자료 조사 및 미확인 사항 |
| [case-identity.md](case-identity.md) | source/canonical 분리, resolver 상태·결정 이력 |
| [incremental-ingestion.md](incremental-ingestion.md) | inventory·delta·fetch ledger·refresh·disappearance |
| [source-fidelity.md](source-fidelity.md) | optional 구조, artifact, Detect→Preserve→Acquire→Reconstruct→Interpret |
| [architecture.md](architecture.md) | 모듈 책임과 처리 분기·운영 연결 |
| [dataset-schema.md](dataset-schema.md) | 모델·결측·상태·gold·DB 계약 |
| [provenance.md](provenance.md) | source/identity/asset 버전과 evidence·release 재현 |
| [legacy-fidelity-inventory.json](step0/legacy-fidelity-inventory.json) | 8,482개 저장 파일의 표식 관찰·표본 hash |
| [identity-fidelity-cases.json](../tests/fixtures/legacy/identity-fidelity-cases.json) | 추가 최소 15종을 포함한 합성 회귀 사례 30건 |

기존 API 실측과 source 해시 기록은 당시 증거다. 추가 문서 작성이 scourt live 수집·PDF 실물 분류·이미지 취득·resolver 구현 완료를 의미하지 않는다.
