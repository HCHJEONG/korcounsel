# 같은 DB를 공유하던 FileStore 경로의 정확 복구

2026-09-11 host runtime의 등록 blob 경로를 PostgreSQL REPEATABLE READ / READ ONLY snapshot으로 검사했다. 등록 527,626개 중 349,312개는 host 일반 파일과 기대 크기가 일치했고, 178,314개가 host의 `data/blobs`에 없었다. 크기 불일치는 0이었다. 이는 이미 통과한 89,130행 보강 reader coverage와 구분되는 전체 등록 저장소 경로 점검이다.

누락은 원본 소실을 뜻하지 않았다. 중지된 `korcounsel-api-1`의 기존 `korcounsel_case_data` volume에는 52개·3,253,285 bytes가, `data/corrected-legacy-bundle-20260911-v2` 아래에는 나머지 178,262개·14,810,631,337 bytes가 동일 storage key의 일반 파일로 남아 있었다. source 경로/크기 전수 대조 후 원본 bytes는 실제 복사 단계에서 각각 SHA-256으로 검증한다. 기존 개별 2개 복구는 이 snapshot 이전에 끝났으므로 이번 178,314개에 중복 포함되지 않는다.

## 입력과 실행 경계

`scripts/restore_exact_docker_blobs.py`는 DB나 제공자 HTTP를 사용하지 않는다. 원감사 파일의 SHA와 별도 source-present 대상 목록의 SHA를 확인하고, 대상 hash·storage key·size가 원감사에 정확히 포함되는지 대조한다. source별 고정 목록은 서로 겹치지 않는다.

- 원감사: `registered-blob-host-path-audit-20260911.json`, SHA `40b5828b37931628b43b6b92455dec6bd05df8e46b632fcd2017e657c4b8305d`.
- Docker 52개: `registered-blob-source-present-targets-20260911.json`, SHA `a9be22230b983199a6debec57acd85960aec3fd74b62a3cbe6807811dcb0532c`.
- Bundle 178,262개: `registered-blob-bundle-present-targets-20260911.json`, SHA `62d202b4a7de2906699d95db7f46fce20128622087c5ce1d22dc67c668751b80`.

자료 경로는 모두 `data/legacy-reader-scale-20260911-v1` 아래다. 기본 모드는 `preflight`, 기본 한도는 100파일·64 MiB다. 복사는 명시적인 `--mode restore`에서만 수행한다. Docker 실행은 stopped container ID·volume binding·다른 running container의 해당 volume 사용 여부를 검사하고 tar stream의 정확한 일반 파일만 읽는다. tar를 filesystem에 풀지 않는다. Bundle은 고정된 절대 root 아래의 `blobs/<prefix>/<sha>`만 읽고 symlink를 거절한다.

원본 bytes의 크기와 SHA가 등록값과 같아야 `FileStore.put`으로 host에 독립 복사한다. 이 API의 원자적 설치와 설치 후 hash 검증을 사용한다. 원본 volume/bundle을 수정하거나 연결하는 symlink·source hardlink를 만들지 않는다. 기존 host 파일은 재검증하고 재사용하며, 손상이 있으면 덮어쓰지 않는다. CLI는 첫 결함에서 중지한다. 전원 중단 등으로 설치 후 journal 쓰기가 끝나지 않았어도 같은 입력·범위를 다시 실행하면 실물 파일 검증으로 재개할 수 있다. 이전 journal의 성공 상태만 믿고 건너뛰지 않는다.

각 실행은 독립 UUID의 append-only JSONL과 summary JSON을 남긴다. 행마다 `RESTORED_VERIFIED`, `REUSED_VERIFIED`, 원본 미발견·크기/hash 불일치·host 손상·미처리 상태를 기록한다. journal은 각 행을 flush하고 100개마다 및 종료 시 fsync한다. 설치된 blob 자체는 FileStore의 파일·디렉터리 fsync를 따른다.

## 실제 실행

Docker 52개는 run `242d78fe-4760-4b99-a348-473b35733c19`에서 전부 `RESTORED_VERIFIED`로 완료했고 오류가 없었다. source container ID·exited 상태·volume binding의 전후 값이 일치했다. 이후 root가 공통 host `./data:/data` Compose 전환을 담당하며, 기존 volume은 그대로 보존한다.

Bundle은 `exact-blob-bundle-recovery-ranges.json`에 offset 순으로 최대 20,000개씩 9개 범위와 각 범위의 정확한 총 byte 상한을 고정했다. 9개 범위가 모두 오류 없이 완료됐으며 bundle 실행 시간은 763.518초였다. Docker와 합쳐 178,314개 전부 `RESTORED_VERIFIED`로 확인했고, 각 journal 대상의 중복·누락 없이 원감사 목록과 정확히 일치함을 다시 대조했다. host의 최초 여유 공간은 932,795,801,600 bytes였고 이번 복사 총량은 14,813,884,622 bytes다.

DB 복구 전 fingerprint는 대상 blob 178,314행과 기존 연결 artifact 178,315행의 전체 JSON metadata를 정렬해 계산했다. 복구 후 같은 기존 행을 비교해 두 fingerprint가 완전히 일치했다. 기존 blob 178,314행·artifact 178,315행의 전체 metadata가 불변이며 추가 target artifact는 0이었다. 복구 도구 자체는 DB 연결 코드가 없다.

## 검증

37개 synthetic fixture 회귀가 통과했다. exact copy·원본 inode/mtime 보존·source와 destination의 별도 inode·재사용·tar 경로 탈출/비대상·symlink/hardlink·크기/hash 오류·기존 host 손상·부분 실패와 중단·동일 범위 재개·첫 오류 중지·입력 SHA와 subset 변조·실행 journal 분리를 포함한다. Ruff check/format과 MYPYPATH=src의 도구 strict mypy가 통과했다. 복구 후 새 READ ONLY snapshot의 등록 blob 529,551개 전부가 host 일반 파일·기대 크기와 일치했고 경로 문제는 0이었다. 복구 178,314개·14,813,884,622 bytes는 111.376초 동안 독립적으로 전부 재읽어 SHA-256이 일치함을 확인했다.

최종 전체 Python/PostgreSQL 회귀는 `127.0.0.1:55432/korcounsel_test`에서 **688 passed, 4 warnings, 65.76초**로 통과했다. 경고는 기존 Starlette/AnyIO 및 multiprocessing fork deprecation이다. backend `src`/`tests`와 이번 복구 도구의 Ruff check·format(105파일), mypy(56 source files)가 통과했다. 같은 DB를 가리키는 corpus DSN은 설정 읽기 외 테스트에 사용하지 않았다.

최종 합본은 `data/legacy-reader-scale-20260911-v1/registered-blob-exact-recovery-final-20260911.json`에 입력·코드·각 journal·사후검증·DB fingerprint·전체 회귀 보고서의 실제 hash와 함께 보존했다. 이 결과는 snapshot 시점에 등록된 파일의 host 경로 정합성 및 이번 복구 bytes의 동일성을 뜻하며, 이후 신규 등록이나 전체 corpus canonical/GOLD 완료를 뜻하지 않는다.
