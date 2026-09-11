# 레거시 본문 이미지 wave 실행

`scripts/run_legacy_image_waves.py`는 기존 source 준비, reader 계획/worker, 이미지 다운로드 job을 순서대로 연결한다. core와 DB schema를 추가하지 않는다. 실제 실행은 별도 worker가 없는 상태에서 한 CLI 프로세스로 수행한다.

## 입력과 범위

`--targets`는 감사한 `scourt-body-image-targets.json`, `--inventory`는 원래 전수 `image-targets.jsonl`이다. inventory SHA-256을 `d5effca374825cf877b8710e35442b7105439bf83424d7005dfcc3855e79e990`에 고정하고 선택 행의 position/source/body hash/snapshot을 대조한다. 2026-09-11 읽기 전용 확인 결과는 1,872행 중 usable 1,829행, 고유 source 1,825개, 100 source씩 19 wave다. usable하지 않은 43행도 결과에 남긴다.

같은 source ID의 모든 선택 행을 한 wave에 둔다. reader job은 최대 100행씩 나누므로 source와 행 수가 다른 경우도 처리한다. 현재 source job key는 기존 inventory hash와 source ID를 그대로 사용하여 이미 취득한 표본을 재사용한다.

기본 실행 한도는 1 wave다. 전체 19 wave는 명시적으로 선택한다.

```bash
cd /home/hchjeong/IntelliJProjects/korcounsel
KLEGAL_ENV_FILE="$PWD/.fordeploy/aws-backup/.env" \
  DATA_DIR="$PWD/data" \
  LEGACY_PARQUET_PATH="$PWD/data/corrected-parquet-20260911-v1/legacy-corrected-full.parquet" \
  backend/.venv-reader/bin/python scripts/run_legacy_image_waves.py \
  --targets data/legacy-reader-scale-20260911-v1/scourt-body-image-targets.json \
  --inventory data/legacy-enrichment-inventory-20260911-v1/image-targets.jsonl \
  --output-dir data/legacy-reader-scale-20260911-v1/scourt-image-waves \
  --max-waves 19
```

## 진행과 재개

각 wave는 현재 source 증거 준비 → 검증된 current reader mapping으로 stage → pending references를 고유 URL 최대 500개씩 다운로드 → 새 acquisition fingerprint로 reader restage 순서다. URL이 반복되어도 모든 row/order/context를 다운로드 manifest에 보존한다. 원래 source ID, 제목·문맥 매칭과 v3 조문 이미지 계승 규칙을 바꾸지 않는다.

각 source 결과 및 각 phase의 계획·job ID·결과는 SHA 기반 `legacy-image-wave:...` artifact와 출력 디렉터리의 JSON receipt로 보존한다. 로컬 파일의 존재로 작업을 완료 처리하지 않는다. 이미 성공한 reader job도 실제 job 상태·입력 plan·결과 manifest를 다시 읽어 대조한다.

중간 wave의 최종 `receipt_artifact` 또는 phase 직후 저장된 `wave-<sha>.json`의 `artifact_id`로 재개한다. 위 명령에 `--resume-wave legacy-image-wave:<sha>`를 추가한다. receipt는 DB/artifact에서 읽고 동일 입력 hash·wave 선택·retry generation을 검증한다. 이미 완료한 source/phase는 보존 증거를 다시 확인한 뒤 다음 phase로 넘어간다. 중단된 다운로드 job도 같은 manifest와 request key로 재개한다.

`--start-wave N`은 명시한 wave부터 시작한다. `--max-waves`는 시작 위치부터 이번 호출에서 처리할 wave 수다. `--retry-generation N`은 reader 행 실패 또는 다운로드 재시도를 위한 새 계획을 만들 때 사용한다. 기존 receipt 재개는 원래 generation을 유지해야 한다. source 취득 key 자체는 변경하지 않는다.

## 부분 완료와 중단

- `SOURCE_NOT_FOUND`는 원래 source job이 FAILED여도 기록하고 계속 진행한다.
- `SOURCE_FETCH_FAILED` 또는 `CURRENT_STRUCTURE_UNCONFIRMED`가 연속 세 번이면 중단한다. 다른 결과는 연속 수를 초기화한다.
- reader job이 성공하면서 일부 행만 실패하면 실패 행을 보존하고 다른 행의 다운로드·restage를 계속한다.
- 이미지 URL별 실패도 job이 성공한 경우에는 보존하고 restage하여 실패 상태를 표시한다.
- reader/download job 자체가 FAILED이거나 완료되지 않은 QUEUED/RUNNING 상태, 종료 준비, 다른 활성 job이 있으면 다음 phase를 시작하지 않는다.
- 모든 wave 행은 최종 row 결과에 포함한다. 처리하지 못한 행을 성공으로 세지 않는다.

CLI의 `COMPLETED`는 선택한 wave의 orchestration 완료다. 모든 이미지 취득 또는 모든 행 매칭 성공을 뜻하지 않는다. 개별 source/row/download 결과와 최종 coverage 검증을 함께 확인한다. 중단 시 종료 코드는 2다.

## 검증

`backend/tests/unit/test_image_wave_tools.py`의 15개 독립 테스트로 source 묶음, 501 URL 분할·반복 위치 보존, inventory hash/행 대조, NOT_FOUND/행 실패/URL 실패, stage·download job 중단, drain·foreign job, 연속 구조 실패, immutable phase 재개를 검증했다. 실제 public DB worker 실행은 도구 작성 과정에서 하지 않았다.
