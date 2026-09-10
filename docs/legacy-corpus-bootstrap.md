# 기존 corpus 식별 체계·bootstrap 조사

2026-09-10. 사용자 요청에 따라 ID 설계를 먼저 고정하지 않고 기존 자료를 초기 자산으로 계승할 수 있는지 전수·표본 조사했다. 원본 저장소 수정, crawler 실행, 외부 source 호출, AWS 변경, 운영 DB import는 하지 않았다.

## 범위와 방법

- 최종 저장본: `I:\VSCodeBases\web2df\saved\20241126\df_glaw_corpus\df_glaw_corpus_fullest_gmeta_lmeta.pickle` (6,525,441,901 bytes).
- 실제 DataFrame을 읽어 **89,130행·60컬럼**, index 0~89,129 및 유일성을 확인했다. 동일 snapshot의 CSV 89,130행에서 case_full_no가 위치별로 모두 일치했다.
- pandas 2.2.3·NumPy 1.26.4의 분석 전용 임시 환경을 사용했다. 레거시 Python 코드는 import하지 않았다. pickle은 허용한 데이터 클래스만 읽는 unpickler로 열었으며 예상하지 못한 global은 차단했다. 이 도구는 신뢰하는 지정 snapshot 분석용이며 임의 pickle 파일을 안전하게 실행하는 일반 도구가 아니다.
- 전 컬럼의 타입/결측, source IDs, 업무키·행 중복, 출처 연결 cardinality를 전수 집계했다. seed 20260910의 균등 무작위 100행에 editorial/ID 결측·중복 ID를 과표집해 **195개 서로 다른 행**의 metadata·필드 길이·제한된 editorial 발췌·img 태그 수를 기록했다. 195행을 모두 법률 내용 검수했다는 뜻은 아니다.
- 대표 중복/문서 차이 12개 행은 별도 저장 scourt/law_go_kr metadata catalog와 직접 대조했다. 결측·editorial 조합 대표 표본도 읽었다. 본문 전체 수작업 검토·현행 웹 원문 대조·모든 충돌의 확정 판정은 수행하지 않았다.
- 전체 본문을 Git에 복사하지 않았다. 89,130행 metadata projection은 Git 제외 `data/legacy-audit/metadata-20241126.jsonl`이며 원 snapshot hash와 원래 row locator를 갖는다. 이는 import 완료 자료가 아니라 반복 조사용 projection이다.

근거: [전수/층화 표본 JSON](step0/legacy-corpus-analysis.json), [업무키·catalog 대조 JSON](step0/legacy-identity-analysis.json). 각 원본 파일의 SHA-256을 포함한다. 재현 스크립트는 루트 scripts/analyze_legacy_corpus.py, analyze_legacy_identity.py, inspect_legacy_pickle.py다.

## 기존에 실제로 쓰던 식별자

최종 60컬럼에 canonical_id, case_id, 별도 UUID 대표값은 **없다**. 실제 필드는 `gmeta_contId`, `lmeta_serialno`, `case_full_no`, `court_name`, `case_no`, DataFrame index 및 `folder_file_name`이다. 이는 이번 최종 corpus와 관련 코드를 확인한 범위의 결론이며 다른 애플리케이션 DB에 대표 ID가 절대 없다는 뜻은 아니다.

| 필드 | 값이 있는 행 | 서로 다른 ID | 중복 ID 그룹 |
| --- | ---: | ---: | ---: |
| scourt gmeta_contId | 88,676 | 88,607 | 68 (137행) |
| law_go_kr lmeta_serialno | 88,003 | 87,660 | 323 (666행) |

두 ID는 모두 문자열이며 없는 값은 `empty`다. 동일 숫자를 서로 다른 namespace 사이에서 합치지 않는다.

| ID 보유 상태 | 행 수 |
| --- | ---: |
| 양쪽 모두 | 87,957 |
| scourt만 | 719 |
| law_go_kr만 | 46 |
| 양쪽 모두 없음 | 408 |

- `_02_crawl_glaw_updated_panre.py:20–34`는 기존 gmeta_contId 집합과 목록을 비교해 신규를 식별한다. **scourt 공식 ID가 증분 수집의 실질 기준키였다.**
- `_05_create_df_lmeta.py`는 metadata 복합 조건으로 법제처 ID를 기존 행에 붙인다. 별도 canonical ID 생성 코드가 아니라 source 간 연결이다.
- `_04_concat_old_and_new_df_corpus_then_create_fullest.py:515`의 concat은 ignore_index=True다. index는 snapshot 행 locator로 보존해야 하며 영구 대표 ID로 취급하지 않는다.
- `_08_case_df_summary2full.py`는 case_full_no로 요약과 corpus를 연결하고 두 공식 ID를 추가한다. 모든 기존 연결이 source ID 직접 join은 아니었다.
- `util_df_standard_case.py:149–155`는 **court_name + case_no**를 결합해 중복을 판별한다. 사용자 설명과 일치하는 기존 업무키 사용 근거다.

**결정:** 새로운 UUID를 89,130행 전체에 일괄 발급하지 않는다. 기존 공식 ID와 업무키·행 locator를 보존한다. canonical 대표값의 공식 ID 활용을 허용하고, 사건/개별 결정 문서의 대표 단위를 먼저 구분한다. source ID를 대표값으로 사용하는 경우에도 모든 alias와 출처를 잃지 않는다.

## 업무키와 개별 문서의 구분

저장 court_name + 전체 case_no에 앞뒤 공백 제거만 적용하면 전 89,130행에서 값이 있고, 조합은 88,720개다. 중복 업무키는 367그룹·777행이다. 이 숫자는 고유한 법적 판례 수 또는 수작업 오류 수가 아니다. 법원 alias·병합 번호 분리 등은 아직 적용하지 않았다.

| 중복 업무키의 진단 분류 | 그룹 수 |
| --- | ---: |
| 앞뒤 공백 제거 후 인용문 동일 | 247 |
| 인용문은 다르지만 표시 날짜 동일 | 74 |
| 표시 날짜가 다름 | 46 |

대표 확인:

| 업무키 | 실제 관찰 | 의미 |
| --- | --- | --- |
| 서울동부지방법원 2010고정2761 | 행 190/232의 contId 1984981 및 serialno 230257 동일. 행 86671은 contId 2123108, 같은 serialno·날짜 | 재수집/표현 중복과 복수 source document alias 후보. 자동 삭제하지 않음 |
| 대법원 2008재도11 | scourt 2064767·lawgo 166330 = 2011-01-20 판결, scourt 2063727·lawgo 224141 = 2010-10-29 결정 | 보존된 양쪽 공식 catalog에서도 구분되는 문서. 단순 오타로 취급하지 않음 |
| 춘천지방법원영월지원 2010고합50 | 2011-01-20 판결과 2011-01-21 결정, 양쪽에서 서로 다른 ID | 같은 사건 업무키 아래 여러 결정 문서 보존 필요 |
| 서울고등법원 2001나60578 | 법제처 159795 판결, 224121 중간판결 | 문서 종류 구분을 유지 |
| 의정부지방법원 2007나10840 | 2009/2010 표기가 섞이고 일부 ID가 해당 역사 catalog에 없음 | 미해결 충돌 표본. 임의 날짜 정정·병합 금지 |

법원명+사건번호는 사용자 결정대로 고유 **사건 업무키**로 유지하며 LawnB 등 정부 ID 없는 자료도 이 키로 등록·대조한다. 사건→개별 판결/결정 문서→출처 representation을 구분한다. 기존 문서 행 전체에 업무키 UNIQUE를 곧바로 걸어 데이터를 없애지 않는다. 드문 수작업 키 오류는 이 정상 다문서 관계와 별개의 예외 이력이다.

## 출처 연결의 신뢰도와 catalog

한 scourt ID가 여러 lawgo ID와 연결된 경우는 1개(2059521→216043/223907), 한 lawgo ID가 여러 scourt ID와 연결된 경우는 271개다. 중복 표현 또는 과거 매칭 문제일 수 있으므로 모두 오류/모두 EXACT로 단정하지 않는다. 기존 연결을 먼저 보존하고 필요한 그룹만 검증한다.

역사 catalog는 scourt 88,493개, law_go_kr 87,658개이며 각 catalog 내부 ID 중복은 없다. corpus에서 ID가 있지만 이 catalog에 없는 행은 scourt 116행, lawgo 208행이다. 목록 범위·시점 차이이므로 삭제나 철회로 처리하지 않는다. 양쪽 날짜가 있는 87,957행은 보존 gmeta/lmeta 날짜를 숫자 8자리로 비교하면 모두 같다. 이것만으로 연결의 정확성을 입증하지는 않는다.

최종 corpus의 site 값은 전부 glaw다. 따라서 이 필드만으로 각 본문·보강 조문·이미지의 최종 출처를 단정할 수 없다. 408개 ID 결측 행 역시 자동으로 LawnB 자료라고 분류하지 않는다. LawnB 자체 보유 corpus의 별도 전체 범위는 이번 89,130행과 구분해 후속 조사한다.

## 기존 데이터 품질과 그대로 보존할 정보

| 관찰 | 전수 건수 / 처리 |
| --- | --- |
| 저장 HTML 문자열·추출 문자열 | 각각 89,130행 존재. HTTP 원본 bytes·fidelity 완전성을 뜻하지 않음 |
| 판시사항과 요지 모두 | 64,364행 |
| 판시사항만 | 9,849행 |
| 요지만 | 69행 |
| 둘 다 없음 | 14,848행 |
| reasoning | 문자열 89,126행, 숫자 0 4행 |
| decision_date | **parser 객체 89,129행**, datetime 1행 |

editorial 숫자 0을 원문 부재로 자동 확정하지 않는다. 기존 파서의 실패일 수도 있으므로 원 필드와 사유를 보존한다. `lnfd` 등 레거시 표식도 원 추출 표현을 따로 남기고 새 normalization을 적용한다. editorial 없는 자료를 버리거나 0개 쟁점을 오류로 만들지 않는다.

날짜 객체 문제는 `_04`의 `parser.parser(temp_date_string)` 호출과 일치하는 실제 관찰이다. parser 객체를 날짜로 캐스팅하지 않는다. 보존 gmeta_sngoDay/lmeta_sngoDay 및 인용문을 명시 규칙으로 대조·복구하고 불일치는 별도 검토한다. 과거 값을 원 archive에서 지우지 않는다.

195행 중 img 태그가 관찰된 표본은 85행이다. 과표집 표본이며 장식 이미지도 포함할 수 있어 전체 판례 이미지 비율로 외삽하지 않는다. 누락 asset 탐지/취득은 원본 보존 이후 별도 작업이다.

## 실행 순서와 완료 조건

1. **완료:** 최종 corpus·CSV·두 metadata catalog 전수/표본 audit, checksum, 분석 projection 및 이 보고서.
2. **다음:** 대표 ID/업무키/개별 결정 문서 관계와 legacy provenance schema 확정. 원래 key를 모두 유지하고 충돌 fixture를 연결한다.
3. 기존 snapshot→versioned artifact·source aliases·업무키 registry로 옮기는 bootstrap mapper와 dry-run manifest 구현. 첫 표본 import에서 원문·행 locator·hash·건수·재실행 동일성을 확인한다.
4. 전체 89,130행 import와 duplicate representation/미해결 충돌 보고서. 실패 행은 격리해 보존하며 전체 건수와 맞춘다. imported·quarantined 합계, ID coverage·checksum을 검사한다.
5. 기존 공식 ID 목록을 기준으로 신규/실패 재시도만 수집하고, 기존 본문 변화는 별도 refresh로 다룬다. 전량 재수집은 기본안이 아니다.

Step 2의 일반 domain 모델은 초안으로 구현했지만 legacy provenance와 대표 문서 단위가 아직 고정되지 않았다. Step 2 전체 완료나 실제 DB import 완료로 기록하지 않는다. 구현된 Python 검사 84건은 합성 계약·기존 로컬 연결 검증이며 89,130행 전체를 새 domain으로 변환했다는 뜻이 아니다.

재현(WSL, 레포 루트):

```bash
uv run --no-project --with pandas==2.2.3 --with numpy==1.26.4 python scripts/analyze_legacy_corpus.py \
  --root /mnt/i/VSCodeBases/web2df/saved/20241126 \
  --output docs/step0/legacy-corpus-analysis.json
uv run --no-project --with pandas==2.2.3 --with numpy==1.26.4 python scripts/analyze_legacy_identity.py \
  --root /mnt/i/VSCodeBases/web2df/saved/20241126 \
  --projection data/legacy-audit/metadata-20241126.jsonl \
  --output docs/step0/legacy-identity-analysis.json
```

입력 경로는 분석 명령의 명시적 인자이며 앱 런타임에 hard-code하지 않는다. 대형 pickle 분석은 충분한 메모리가 있는 개발 환경에서 수행한다. 이 pandas 분석 작업을 bastion small의 상시 작업으로 배포하지 않는다.

## 내용 보강·증분 목적의 추가 확인

2026-09-10 후속 조사에서 scourt 기본 HTML→이미지 주소 보완→lawgo 조문 jtable 보강의 실제 전후 저장 표본을 확인했다. 신규 contId 차집합 및 보강 미완료/재개 코드도 확인했다. [내용 보강·증분 계승 전략](legacy-enrichment-and-incremental.md)을 bootstrap 이후 구현의 기준으로 추가한다.
