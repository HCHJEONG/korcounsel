# 개발 기반 — Step 1

2026-09-10. 실행 명령의 진입점은 [루트 README](../README.md) 하나로 통합했다. 하위 README는 만들지 않는다.

선택한 도구: Node 24.16.0/pnpm 11.23.0, React 19.3.0/Vite 8.2.2/TypeScript 5.9.3, Python 3.12/uv 0.12.5, Psycopg 3, Docker Compose/PostgreSQL 17/Nginx. 정확한 Python/Node dependency는 backend/uv.lock과 pnpm-lock.yaml에 고정한다. pnpm-workspace.yaml은 pnpm이 기록한 package 설치 정책이며 다중 프런트 workspace를 도입한 것은 아니다.

[Vite Node 요구사항](https://vite.dev/guide/), [uv Python 관리](https://docs.astral.sh/uv/guides/install-python/), [Psycopg 설치](https://www.psycopg.org/psycopg3/docs/basic/install.html)를 확인하고 현재 WSL 환경에서 검증했다. migration/ORM·프런트 router·조회 라이브러리는 해당 기능이 생길 때 선택한다.

현재 Compose의 api/web/postgres는 실제 기동된다. worker는 tools profile의 일회성 check-db이며 영속 job queue를 가장하지 않는다. 별도 worker.py와 migrations를 빈 구현으로 만들지 않았다. 인증이 없는 개발 상태이므로 공개 배포용으로 노출하지 않는다. 운영 TLS·restart/resource 정책·image release 고정·백업/복구는 Step 11B에서 완성한다.

개발에서 host Vite/uvicorn + Compose postgres를 쓰거나 전체 Compose를 쓸 수 있다. compose.dev.yaml은 PostgreSQL localhost:55432 공개만 추가한다. API/DB 내부 포트는 base Compose에서 host에 공개하지 않는다. compose.yaml만 사용할 때에도 예시 env를 지정해야 하며 운영은 별도 실제 env를 제공한다. 예시 env는 사용자 aws-backup/.env와 무관하다.

Python 테스트는 기본적으로 credentials/env를 지우고 실행한다. integration은 KLEGAL_TEST_DATABASE_URL이 지정된 localhost korcounsel_dev/test에 SELECT 1만 수행한다. domain DB schema·동시성·migration 검증은 Step 2A다. browser E2E는 5173/8000에 테스트용 서버를 직접 시작하므로 기존 서버가 그 포트를 쓰면 명시적으로 종료하거나 포트를 조정한다.

원본 53개 합성 fixture의 bytes를 유지하여 backend/tests/fixtures로 이동했다. 앞으로 resolver/parser 구현 시 실제 회귀 테스트에 연결한다. 현재 검증은 설정 alias/명시적 env/비밀값 출력 방지/health/DB 연결과 프런트 정상·실패·잘못된 payload·좁은 화면에 한정된다.
