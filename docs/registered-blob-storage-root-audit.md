# 기존 FULL_ROW blob 저장 루트 읽기 전용 감사

2026-09-11. host 경로 감사의 미발견 178,314개 중 Docker source volume에 없는 178,262개를 조사했다. **178,262개 모두 기존 corrected bundle v2 폴더에서 발견했으며 정규 파일 여부·DB 기대 크기가 일치했다.** 파일을 새로 만들거나 복사·등록하지 않았다.

| 보존 유형 | 파일 수 |
| --- | ---: |
| FULL_ROW_INPUT | 89,130 |
| legacy 보존 record | 89,130 |
| 입력 bundle / import 결과 manifest | 2 |
| 합계 | 178,262 |

현재 host 조회 루트는 `/home/hchjeong/IntelliJProjects/korcounsel/data`이고, 발견한 실제 보존 루트는 `/home/hchjeong/IntelliJProjects/korcounsel/data/corrected-legacy-bundle-20260911-v2`다. 두 경로 아래의 상대 storage_key 규칙은 모두 `blobs/{sha256[:2]}/{sha256}`다. 178,262개 전체가 후자의 같은 상대 경로에서 발견됐다. 기대 크기와 실제 합계는 각각 14,810,631,337 bytes다.

[FileStore](../backend/src/klegal_gold/storage/files.py)는 절대 root에 상대 key를 붙이고, [Records](../backend/src/klegal_gold/db/records.py)는 blob의 hash·상대 key·크기를 DB에 기록한다. DB blob 행에는 생성 당시 FileStore root가 따로 없다. [기존 import 문서](legacy-full-row-import.md)는 corrected bundle v2 경로 및 성공 job `a2498da4-2321-480f-bbeb-fd3c278da1f6`를 명시하며, staging을 공유 DATA_DIR에 전달하고 host와 Compose volume을 구분해야 한다고 설명한다. 이 실제 결과는 과거 import 저장 루트와 현재 host 조회 루트가 다른 것으로 설명된다. hash 파일명·행 locator가 잘못됐다는 근거는 발견하지 못했다.

각 89,130개 그룹의 양끝·중간·균등 간격 표본과 두 manifest를 합한 36개(42,038,304 bytes)는 실제 파일 전체를 읽어 SHA-256까지 검증했다. 모두 DB 기대 hash와 일치했다. **전수 확인은 경로·정규 파일·크기이며, 전수 내용 hash 검증 완료를 뜻하지 않는다.** 향후 exact-copy를 수행한다면 대상마다 원본 hash와 크기를 검증해야 한다.

원래 pickle은 corrected Parquet metadata가 지정한 `I:\VSCodeBases\web2df\saved\20241126\df_glaw_corpus\df_glaw_corpus_fullest_gmeta_lmeta.pickle`에 실존하며 크기는 6,525,441,901 bytes다. web2df와 df2preproc 실제 루트도 확인했다. pickle 내용을 읽거나 실행하지 않았고 I 드라이브 전체를 검색·해시하지 않았다. 원 pickle 존재는 직렬화된 각 CAS 파일의 동일성을 대신 증명하지 않는다.

현재 설정에 남은 예시 DATA_DIR `/absolute/path/to/korcounsel/data`와 `backend/data`는 존재하지 않았다. 예시 설정은 과거 import 당시 환경의 직접 증거로 사용하지 않는다. 원본·DB·job·reader·코드는 변경하지 않았으며 reader coverage의 성공/실패 판정도 바꾸지 않았다.

증거: `data/legacy-reader-scale-20260911-v1/registered-blob-alternate-root-audit-20260911.json`, SHA-256 `cd30b768ee59db45b8fb1db31d825351e52bfe8ae8ad64cbf025a469aad4fad9`. 입력 host audit SHA-256과 source-volume-preflight SHA-256, 대상 집합 digest, 36개 표본의 정확한 원본 경로·hash·크기를 함께 기록했다.
