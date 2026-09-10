# Legacy 보존 import 계약

2026-09-10 Step 2. 이 계약은 기존 snapshot을 보존하는 staging과 문서 identity 후보를 정의한다. 전체 corpus import, DB registry 확정, 신규 source 취득은 별도 단계다.

## 사건과 문서 대표값

canonical_id의 단위는 **개별 판결·결정 문서**다. CourtCaseKey는 사건 업무키이며 하나의 사건에 여러 문서가 연결될 수 있다. 병합 번호는 원래 전체 표기를 보존하고 Step 5의 명시적 번호 파서가 각 CourtCaseKey alias를 만든다. 현재 staging의 business_key는 앞뒤 공백만 제거한 전체 번호 표기이며 alias 분해가 끝났다는 뜻이 아니다.

신규 registry 등록의 대표값 정책은 다음과 같다.

1. 이미 확정된 registry 연결이 있으면 대표값과 연결 revision을 재사용한다. lawgo-only 자료에 scourt ID가 나중에 붙어도 기존 대표값을 바꾸지 않는다.
2. 미등록 문서는 검증된 scourt ID의 `scourt:<contId>`를 우선하고, 없으면 검증된 lawgo ID의 `law_go_kr:<serialno>`를 사용한다. 숫자 원값과 namespace를 각각 유지한다.
3. 공식 ID가 없으면 `legacy-row:<snapshot SHA-256>:<position>`을 최초 로컬 후보값으로 사용할 수 있다. 이것은 행 보존용 locator에서 유래한 로컬 후보이며 법적 identity나 가짜 정부 ID가 아니다. 사건 업무키로 기존 문서를 대조한 뒤 registry가 확정하고, 이후 snapshot 위치가 달라져도 확정 대표값은 유지한다.
4. legacy mapper는 이 정책의 **document_id_proposal**만 생성한다. 두 ID를 관찰했다고 동일 문서로 확정하지 않으며 LEGACY_OBSERVED를 EXACT로 승격하지 않는다. source 중복·상이한 key/date/disposition은 원행을 모두 보존하고 충돌 보고서에 넣는다.
5. 동일 업무키만으로 merge하지 않는다. 동일 source ID의 같은 metadata도 여러 행/본문 버전 보존을 허용하며, source ID가 다른 중복 표현은 별도 후보 대조 대상이다. 결측 신호로 충돌이 발견되지 않은 경우도 연결 확인 완료가 아니다.

source key 유일성은 registry의 활성 문서 연결에 적용하고 legacy 행 테이블에는 적용하지 않는다. 문서 테이블에 court+docket UNIQUE를 걸지 않는다. 사건 key registry와 문서 연결을 분리한다. registry snapshot은 대표값, 모든 source aliases, 업무키 aliases, link revision을 저장하며 입력 manifest에 hash를 고정한다. 재수집으로 registry를 재발급하지 않는다.

MERGE는 대표 생존값을 명시하고 이전 대표값을 alias/이력으로 유지한다. SPLIT은 이전 문서/새 문서의 출처 배분을 명시하며, RELINK는 대상 source와 사유를 기록한다. 기존 IdentityLinkEvent에 이전/이후 전체 identity·증가하는 revision·actor·시각·사유를 남긴다. 이전 release와 review는 이전 snapshot을 유지한다. DB 트랜잭션과 registry의 재현·동시성 검증은 Step 2A다.

## 보존 모델과 변환

`domain/legacy.py`의 LegacyRow → `ingestion/legacy.py`의 map_legacy_row → LegacyCaseRecord가 이번 범위다. 보존 모델은 실제 HTTP response가 필요한 RawLegalCase/LegalCase와 별도다. 이를 live Provenance에 강제로 넣거나 legacy hash로 raw_content_hash를 채우지 않는다. legacy에서 LegalIssueUnit을 생성하는 연결·위치 mapping은 후속 import/구조화 단계에 추가해야 한다.

| 입력 | 보존 및 변환 규칙 |
| --- | --- |
| 모든 원필드 | LegacyField의 이름·원래 타입·값을 유지. 문자열은 줄바꿈·lnfd·Unicode를 변경하지 않음 |
| empty·빈 문자열·정수 0·null | 원래 타입/값 유지. editorial은 UNKNOWN 사유, source 부재/parse 실패를 단정하지 않음 |
| source ID의 문자열 0 | legacy ID sentinel로 처리. 일반 본문의 문자열 0과 구분 |
| parser 객체 | OPAQUE + 원래 타입 + snapshot/행/필드 locator. 객체를 실행·캐스팅하거나 repr 주소를 보존값으로 쓰지 않음 |
| dict/list 등 | JSON 문자열로 명시 직렬화하거나 OPAQUE로 archive를 참조. 자동 타입 변환을 하지 않음 |
| 날짜 | 보존 gmeta/lmeta 날짜와 인용문을 비교. 지원 형식만 엄격하게 파싱하고 유효 값이 일치할 때만 날짜 후보 생성 |
| 날짜 충돌·잘못된 날짜 | null + 원필드별 이유. 하나의 정상 값으로 다른 오류를 덮지 않음 |
| 문서 종류 | 보존 인용문 끝의 판결/결정/중간판결/명령을 추출. 역사 catalog와 재대조되기 전 공식 확정 metadata가 아님 |
| 보강 HTML | ENRICHED_HTML/PRESERVED_UNVERIFIED. jtable·이미지 주소를 그대로 보존하며 조문별 성공·법령 버전·이미지 취득을 추론하지 않음 |

row_from_metadata_projection은 기존 audit projection 자체를 보존한다. 이 projection에서 ID 결측이 null로 정리된 경우 과거의 empty를 복원했다고 주장하지 않는다. 원래 sentinel은 전체 snapshot에 남아 있으며 FULL_ROW adapter 단계에서 읽는다. projection에는 본문과 일부 공식 metadata가 없으므로 전체 60컬럼 보존 완료 자료로 사용할 수 없다. 예를 들어 행 8499의 인용문은 판결이나 별도 역사 catalog의 중간판결 관찰은 별도 정보다. 표본 mapper가 누락 catalog 정보를 만들어 보충하지 않는다.

## Provenance와 hash

- snapshot_sha256은 보존 pickle 파일의 기존 실측 checksum, original_index/position은 해당 snapshot의 행 locator다.
- imported_at은 현재 변환 실행 시각이다. 과거 retrieved_at, HTTP raw hash, 검증되지 않은 source URL은 null과 결측 이유로 남긴다.
- LegacyStoredText의 utf8_sha256은 **저장 문자열을 UTF-8로 인코딩한 hash**다. 실제 파일을 strict UTF-8 decode한 경우에만 별도 file_sha256을 기록하며 재인코딩 hash와 대조한다. 서버 응답 hash가 아니다.
- legacy_content_revision은 원행·변환 결과·규칙 버전을 포함하되 imported_at을 제외한다. 원문/보강 값이 바뀌면 다른 revision이며 실행 시각만 바뀌면 동일하다.
- source URL, 이미지 binary hash, 조문 취득시각/적용 법령 버전, 텍스트 evidence offset을 생성하지 않는다. 기존 원본과 보강의 연결이 관찰된 범위만 보존한다.

## 이번 검증과 다음 단계

실제 metadata projection 15행: 일반·ID 없음·lawgo-only·scourt-only·동일 ID 중복·동일 사건 다문서·역사적 충돌 후보를 포함한다. 확인된 저장 HTML 4개(기본 1, 보강 3)는 기존 manifest SHA-256과 대조했고 정확한 문자열의 JSONL round-trip 및 실행 시각이 다른 재변환의 content revision 일치를 확인했다. 본문 실파일은 Git에 복사하지 않았다. [실행 보고서](step0/legacy-contract-verification.json)에 범위·hash·미실행 항목이 있다.

재현은 backend에서 실행한다. archive-root는 사용자가 선택한 기존 snapshot 디렉터리이며 생략하면 metadata 15행만 검사한다.

```bash
uv run python scripts/verify_legacy_samples.py \
  --archive-root /mnt/i/VSCodeBases/web2df/saved/20241126 \
  --report ../docs/step0/legacy-contract-verification.json
```

전체 89,130행의 FULL_ROW adapter·보존 파일 저장·import ledger·quarantine manifest·DB 등록은 후속이다. imported/quarantined 합계와 source/row locator coverage를 맞추고, unknown provenance를 지원하는 legacy 구조화 경로를 먼저 연결해야 한다. 일반 schema를 만족시키려고 역사적 response를 꾸미지 않는다. Parquet exporter, 현재 scourt/lawgo 호환성, 법률 내용 검수, 조문 버전 검증, AWS 운영 변경은 수행하지 않았다.

2026-09-10 최종 검증: backend에서 uv ruff check·ruff format --check·mypy 통과, 로컬 PostgreSQL 연결 포함 pytest **105건 통과**. 기존 upstream deprecation warning 2건 유지. 실제 metadata 15행·저장 HTML 4개 검증 및 git diff --check 통과. 프런트·분석 전용 도구는 변경하지 않았으며 해당 테스트를 이번 작업에서 재실행하지 않았다.
