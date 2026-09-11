# 이미지 job 재개와 운영 지표

이미지 worker의 최종 checkpoint에 있는 `image_acquired`, `image_skipped`, `image_bytes_stored`는 마지막 실행 시도의 수치다. 같은 job이 일부 URL을 취득한 뒤 중단되면 다음 실행은 기존 ACQUIRED URL을 다시 요청하지 않고 SKIPPED로 기록한다. 따라서 마지막 checkpoint만 합산하여 전체 job의 신규 취득량으로 보고하면 이전 시도의 성공분이 빠진다.

전체 job의 신규 취득 URL은 `image_acquisition_attempts`에서 해당 `job_id`의 `outcome='ACQUIRED'`인 고유 URL을 집계한다. 실패·skip은 별도로 유지하고, job 실행 횟수와 HANDLER_FAILED 이력은 `job_attempts`에서 확인한다. 마지막 시도의 skip을 새 취득으로 다시 합산하지 않는다.

예를 들어 첫 시도에서 325개를 취득하고 다음 시도에서 325개를 skip하며 162개를 새로 취득했다면, 마지막 checkpoint의 acquired는 162지만 전체 job의 신규 취득은 487개다. 실제 판례 이미지 연결 수는 URL 취득 수와 별개로 reader 등장 위치를 집계해야 한다.

`tests/integration/test_image_job_partial_resume.py`는 두 URL의 합성 fixture로 이 경로를 고정한다. 첫 URL 성공 뒤 둘째 URL에서 의도적으로 OSError를 발생시키고, 동일 job을 새 worker로 재개한다. 첫 URL 재요청 없음, 원 blob·취득 이력 불변, job 시도 FAILED→SUCCEEDED, 전체 ACQUIRED 2개와 최종 checkpoint acquired 1개/skip 1개를 검증한다.

이 OSError는 **합성 복구 재현**이며 실제 wave 9의 HANDLER_FAILED 원인을 확정하는 증거가 아니다. core를 변경하지 않았으며 `korcounsel_test` UUID 격리 스키마에서 새 회귀 1개가 통과했다. ruff format/check도 통과했다.
