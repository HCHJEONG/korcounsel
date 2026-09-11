# 이미지 decode 실패 응답 보존

2026-09-11 본문 이미지 wave에서 취득에 실패한 응답을 재검증할 수 있도록 `assets/images.py`에 격리 보존을 추가했다. 정상 이미지 검증 강도, 허용 URL, redirect 금지, 개별 16MB 및 배치 바이트 한도는 유지한다. HTTP 오류·timeout·크기 초과로 완전히 받지 못한 응답의 추가 수집은 이번 변경에 포함하지 않는다.

`fetch_image`는 한도 이내에서 완전히 받은 응답이 이미지 검증에 실패하면 `ImageResponseRejected`를 발생시킨다. 예외의 문자열은 기존 오류 코드이며, 별도 `response` 속성에 원래 바이트·Content-Type·final URL·취득 시각을 담는다. 주입된 fetcher가 잘못된 `DownloadedImage`를 반환하는 경우도 같은 격리 경로로 처리한다.

`ImageAcquirer`는 원래 응답 바이트를 변형하지 않고 다음 artifact로 보존한 후 FAILED 상태를 기록한다.

- ID: `image-failure-response:<metadata-sha256>`
- origin: `HTTP_RESPONSE`
- metadata.kind: `IMAGE_DECODE_FAILURE_RESPONSE`
- parent: 해당 image manifest artifact
- metadata: `job_id`, 기존 deterministic `attempt_id`, `url`, `final_url`, `retrieved_at`, `raw_content_hash`, `size_bytes`, `content_type`, `error_code`, `acquisition_status=FAILED`, `decode_verified=false`

실패 attempt와 acquisition의 `blob_hash`는 계속 NULL이다. 격리 응답은 `reader-image:` artifact로 등록하지 않으며 ACQUIRED로 세거나 이미지 endpoint에 연결하지 않는다. 같은 URL의 후속 취득에 성공하더라도 이전 실패 응답과 attempt를 보존한다. 격리 파일의 저장·hash 검증에 실패하면 job 실패로 전달하여 응답이 보존된 것처럼 계속 진행하지 않는다.

격리 응답 바이트는 내부 `consumed_bytes`를 통해 배치 용량 한도에 포함한다. 기존 `AcquisitionResult.bytes_stored`와 worker의 `image_bytes_stored`는 검증된 이미지 바이트만 계산한다.

검증은 `korcounsel_test`의 UUID 격리 PostgreSQL 스키마와 synthetic HTTP/fetch fixture에서 수행했다. HTML 오류 응답·손상 GIF의 exact bytes/hash, Content-Type/시각/attempt 연결, 반환형 및 예외형 fetcher, 정상 재시도 뒤 실패 원본 유지, 배치 한도, 손상된 격리 파일 거절, reader 이미지 제공 불가를 포함한 관련 회귀 41개가 통과했다. ruff와 mypy(55 source files)도 통과했다. 실제 provider 재요청과 기존 실패 8건의 재취득은 도구 구현·테스트 과정에서 실행하지 않았다.
