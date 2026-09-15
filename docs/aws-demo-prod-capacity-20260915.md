# aws-demo / aws-prod 배포 후보 조사 — 2026-09-15

## 최종 배포 결정 — 2026-09-15 사용자 확정

**KorCounsel은 aws-demo에 우선 배포한다.** 과거 aws-bastion 배포 계획과
이 문서의 초기 prod 조건부 후보 판단을 대체한다. aws-bastion은 SSH 경유지로
유지한다. 로컬 수집·정리를 마치고 DB·참조 파일 snapshot을 demo에 복원한 뒤
서비스 검증과 실제 운영을 확인한다.

**Onju AI KR은 당분간 aws-prod에 유지한다.** KorCounsel이 운영되는 것을
확인한 다음 이전 여부·시기·공동 운영 자원과 가동 시간 정책을 별도 검토한다.
두 앱 동시 이전을 기본 계획이나 KorCounsel 배포의 선행 조건으로 삼지 않는다.
현재 PhysicalAI 중지만 실행됐으며 EBS 증설·KorCounsel 배포·Onju 이전은
미실행이다. 아래 ‘후보·제안·기존 대상 유지’ 문구는 결정 전 조사 이력이다.

## PhysicalAI 중지 완료 — 2026-09-15

사용자의 명시적 중지 요청으로 aws-demo의 Compose project label이
`physicalai`인 실행 컨테이너 10개를 재확인한 뒤 `docker stop --time 120`으로
중지했다. 전부 exited이며 호스트 전체의 실행 Docker 컨테이너도 0개다.
컨테이너·이미지·볼륨·배포 파일과 재시작 정책은 삭제하거나 변경하지 않았다.
PostgreSQL·Kafka·Neo4j·Mosquitto의 이름 있는 데이터 볼륨이 남아 있음을 확인했다.

중지 직후 available 메모리는 **3,285MiB(약 3.21GiB)**, 사용 메모리는 276MiB,
swap 사용량은 43MiB다. 이전 available 1,675MiB보다 약 1.57GiB 증가했다.
종료 코드는 API·graph worker·simulator·worker-2·Neo4j·Mosquitto·PostgreSQL 0,
frontend·Kafka 143, worker-1 1이다. OOMKilled는 전부 false이며 worker-1의
종료 코드 1 원인이나 앱 데이터 무결성을 이번 중지 확인만으로 확정하지 않는다.
다른 서버나 기존 종료 컨테이너에는 조작을 가하지 않았다.

아래 ‘중지 미실행’ 표기는 이전 조사 당시의 이력이다.

## aws-demo 컨테이너 재조사 — 18:09 KST

사용자의 재조사 요청으로 상태·Compose labels·재시작 정책·mount 경로를
읽기 전용 확인했다. 총 18개 중 실행 10개는 모두 `physicalai` 프로젝트이며,
나머지 8개는 이미 종료 상태였다. 중지·삭제·설정 변경은 실행하지 않았다.

| 실행 서비스 | 메모리 표본 MiB |
|---|---:|
| Kafka | 945.0 |
| Neo4j | 431.2 |
| frontend | 92.34 |
| worker 2개 | 96.08 |
| PostgreSQL | 46.15 |
| API | 10.75 |
| telemetry simulator | 5.69 |
| graph worker | 2.93 |
| Mosquitto | 1.48 |

합계 약 1,632MiB, 약 1.59GiB다. 호스트 available은 1,675MiB,
디스크 여유는 약 23GiB다. 실행 컨테이너 모두 메모리·CPU의 Docker 제한이
설정되지 않았으며 RestartCount=0, OOMKilled=false였다. Kafka와 PostgreSQL은
Docker health가 healthy이며 나머지는 실행 상태만 확인했다.

종료 컨테이너: vueshines(143), vueshines-mysql(137), vueshines-redis(0),
phpsucks-wordpress-1(0), phpsucks-db-1(137), spring-is-cool(143), cobolai(1),
pricingai(1). 괄호는 마지막 종료 코드다. 모두 OOMKilled=false이며 종료
코드만으로 원인이나 중지 주체를 단정하지 않았다. 마지막 세 개는 조사일
11:12 KST경 종료됐고 나머지 다섯 개는 9월 7일 종료됐다.

graph worker와 worker 2개는 on-failure, 나머지 컨테이너는 unless-stopped
재시작 정책이다. 실행 PhysicalAI 컨테이너는 모두 physicalai_default 네트워크에
속하지만 Kafka·PostgreSQL에는 더 오래된 배포 디렉터리의 Compose label이
남아 있다. 추후 중지할 때 최신 Compose 파일만 보고 대상이 빠지지 않도록
실제 프로젝트 labels와 컨테이너 목록을 기준으로 확인해야 한다.

PostgreSQL·Kafka·Neo4j·Mosquitto 데이터는 Docker volume에 보존돼 있다.
중지된 MySQL/Redis/WordPress의 volume도 남아 있다. Docker 전체 volume
17개, 약 2.955GB이며 컨테이너 중지만으로 이 디스크 공간이 없어지지는 않는다.
이미지 24개 약 7.047GB, 컨테이너 쓰기 계층 합계 약 274.4MB다.

## 사용자 조건 변경 후 배치 제안

사용자는 디스크 증설을 허용 가능한 비용으로 보며, 유지 대상은 lawvot,
onju-ai-kr, anguklaw, sampoongaptcom이고 PhysicalAI 관련 서비스는 내려도
된다는 의견을 밝혔다. EC2 간 배치 변경도 가능하다. 이 조건에서는 아래
최초 조사 결론과 달리 **aws-demo를 KorCounsel 전용으로 사용하는 안**을
우선 제안한다. 실제 중지·이관·증설은 실행하지 않았다.

- aws-prod: 이미 배치된 네 앱과 필요한 종속 서비스를 유지한다. 네 앱을
  옮길 필요가 없어 주소·데이터·인증·운영 경로 변경을 줄일 수 있다.
- aws-demo: PhysicalAI 관련 컨테이너를 중지한 뒤 KorCounsel 전용으로
  사용하고 디스크 100–150GiB를 검토한다. 중지는 volume·원본 삭제와 구분한다.
- 전용 4GiB 메모리에서 시작할 가능성은 충분하다. 기존 KorCounsel 표본
  사용량은 약 721MiB이나 최대 수집·검색·백업 부하는 별도로 검증해야 한다.
  PhysicalAI 종료 후 실제 여유는 아직 측정하지 않았다.
- Elasticsearch·penvot-yws는 네 앱에 필요한 종속 서비스일 수 있다.
  앱 네 개만 필요하다는 말을 해당 프로세스의 중지 승인으로 해석하지 않는다.

2026-09-15 AWS 공식 서울 EBS 가격 JSON 확인: gp3 기본 저장 용량은
GB-month당 USD 0.0912, gp2는 USD 0.114다. gp3라면 40→100GB는
월 USD 5.472, 40→150GB는 월 USD 10.032의 용량 비용 증가다. 세금,
snapshot, 추가 성능 요금은 별도다. 현재 볼륨 유형은 이번 SSH 조사만으로
확정하지 않았으므로 gp3 기준 견적을 현재 실제 청구액으로 표시하지 않는다.
[AWS 공식 가격 데이터](https://b0.p.awsstatic.com/pricing/2.0/meteredUnitMaps/ec2/USD/current/ebs.json),
[과금 기준](https://aws.amazon.com/ebs/pricing/).

아래는 기존 서비스를 모두 유지하는 조건에서 수행한 최초 실측이다.

## 결론

사용자 요청으로 2026-09-15 17:48 KST 전후 SSH 읽기 전용 조사를 수행했다.
**현재 디스크 기준으로 aws-prod는 조건부 후보, aws-demo는 용량 확장 전에는
기존 corpus 전체를 포함한 KorCounsel 배포가 어렵다.** 기존 확정 배포 대상인
aws-bastion을 변경한 결정은 아니며 배포·전송·삭제·재시작·AWS 설정 변경은 없다.

## 서버 실측

| 항목 | aws-demo | aws-prod |
|---|---|---|
| EC2 ID | i-0fa95bb4eff77caf2 | i-0c66613ecf80dc3cb |
| 리전 / 타입 | ap-northeast-2 / t3a.medium | ap-northeast-2 / t3a.medium |
| SSH | aws-bastion 경유, ubuntu | aws-bastion 경유, ubuntu |
| 사설 주소 | 172.31.76.194 | 172.31.68.164 |
| OS / CPU | Ubuntu 22.04.3 / x86_64 / 2 vCPU | 동일 |
| 메모리 총량 / available | 3,868MiB / 1,637MiB | 3,868MiB / 1,500MiB |
| swap 총량 / 사용량 | 2,047MiB / 170MiB | 8,191MiB / 888MiB |
| 디스크 장치 | 40GiB | 100GiB |
| 루트 파일시스템 / 사용 / 여유 | 약 39 / 17 / 23GiB | 약 97 / 33 / 65GiB |
| inode 사용률 | 7% | 4% |
| 실행 Docker 컨테이너 | 10개 | 7개 |
| 1분 load average | 0.28 | 0.28 |

IMDSv2에서 instance type·ID·리전·사설 IP를 확인했다. public-ipv4는 값을
취득하지 못했으며 직접 공인 접속 가능하다고 가정하지 않는다. 보안 그룹,
외부 ingress, DNS/HTTPS 경로와 예약 가동 정책은 이번 조사에서 확정하지 않았다.
짧은 vmstat 표본의 후속 구간에서는 두 서버 모두 swap in/out이 0이었다.
swap 사용량만으로 현재 메모리 압박을 확정하지 않으며 장기·최대 부하는 미측정이다.

### aws-demo의 기존 사용

PhysicalAI의 frontend/API/worker 2개/graph worker/telemetry simulator,
Kafka, Neo4j, Mosquitto, PostgreSQL 16이 실행 중이다. Docker 표본에서
Kafka 약 945MiB, Neo4j 약 431MiB를 사용했다. `/var/lib/docker` 약 8.7GiB,
Docker volume 약 2.96GB다. host nginx가 80을 사용하고 frontend 3010,
API는 localhost 18080, Neo4j는 localhost 7474/7687에 바인딩돼 있다.
데모 서버라는 이름만으로 비어 있거나 기존 앱을 중지해도 된다고 판단하지 않는다.

### aws-prod의 기존 사용

lawvotnextjs, onju backend/frontend/PostgreSQL 17, sampoongapt, anguklaw,
penvot-yws가 실행 중이며 호스트 Elasticsearch 8.7.1도 가동 중이다.
`/home/ubuntu/elasticsearch-8.7.1`은 약 12GiB, Docker 디렉터리는 약 7.5GiB다.
Elasticsearch JVM RSS는 약 613MiB, 주요 Next.js 컨테이너들은 약
388/424/204MiB를 사용했다. 컨테이너 80/3000/3500/3800/4321/8800,
호스트 9200/9300 listener가 있다. 기존 80 포트를 새 앱이 차지하면 안 된다.
관찰 시 8080 listener는 없었지만 실제 배포 시 충돌을 다시 확인해야 한다.

Docker는 demo 약 1.50GB, prod 약 5.65GB의 image reclaimable을 표시했다.
이는 삭제 승인이나 실제 확보 가능 용량이 아니다. 롤백용 이미지를 포함할 수
있으므로 현재 여유 공간에 더하지 않았고 정리도 하지 않았다.

## KorCounsel 이관 소요량

로컬 DB·파일과 컨테이너를 같은 조사 구간에 읽기 전용으로 측정했다.

| 항목 | 실측 |
|---|---:|
| 로컬 data 전체 디스크 점유 | 약 83GiB |
| 그중 복원 시험본 | 약 30GiB |
| corrected legacy bundle v1 / v2 | 약 7.1 / 15GiB |
| data/blobs 디스크 점유 | 약 29GiB |
| DB 등록 blob 논리 크기 | 29,395,892,209 bytes ≈ 27.38GiB |
| artifact가 참조하는 blob 논리 크기 | 29,386,344,671 bytes ≈ 27.37GiB |
| corrected Parquet 디렉터리 | 약 1.2GiB |
| PostgreSQL DB 논리 크기 | 5,125,379,763 bytes ≈ 4.77GiB |
| API / worker / DB / web 메모리 표본 | 약 90 / 171 / 446 / 14MiB |

blob 파일·Parquet·DB만으로 약 **35GiB**이며, 이미지·로그·WAL·덤프·복원
임시 공간까지 고려한 초기 계획치는 **35–40GiB 이상**이다. 이 숫자는 이미
완성된 이관 bundle의 확정 크기가 아니다. 현재 시점의 데이터만 반영하며
향후 기간 증보로 늘어난다. 전체 data 83GiB와 DB를 그대로 복사하는 방식은
두 서버 모두 현재 여유 공간을 초과한다.

data의 복원 시험본과 중간 bundle을 운영 디렉터리에 중복 배치하지 않는
일관된 DB+참조 파일 snapshot 구성이 필요하다. 이 파일을 로컬에서 삭제하라는
뜻이 아니다. 보존 archive·manifest·Parquet과 파일 참조를 실제 bundle 작성
시 검증해야 한다. 기존 backup 구현은 DB snapshot과 등록 blob을 다루므로
운영 Parquet 및 추가 참조 파일도 이관 manifest에 포함해야 한다.

KorCounsel 컨테이너 메모리 합계 약 721MiB는 조회·수집 최대 부하가 아닌
작업 종료 후 표본이다. 서버의 1.5–1.6GiB available과 비교하면 가벼운 조회
실험은 가능할 여지가 있지만, 전체 수집·재색인·백업과 기존 앱 동시 부하를
보장하지 않는다. 로컬 빌드 후 이미지를 옮기는 기존 원칙을 유지한다.

## 배포 판단에 필요한 다음 확인

1. **aws-prod:** 디스크상 약 35–40GiB를 추가할 여지는 있다. 전체 자료 이관
   후보로 검토할 수 있지만 기존 운영 앱 영향이 중요하다. 메모리 제한·실부하
   측정과 필요 시 증설을 검토하고, 서버 내 백업 복제본까지 둘 수 있는지는
   별도로 산정한다. 기존 PostgreSQL 17에 합치는 것으로 가정하지 않는다.
2. **aws-demo:** 현재 여유 23GiB가 현재 운영 데이터 소요량보다 작다.
   전체 corpus를 올리려면 먼저 저장 공간을 늘려야 한다. 작은 기능 표본은
   별도 범위로 가능하지만 전체 앱 데이터 이관 완료와 구분해야 한다.
3. 두 서버 모두 별도 Compose 이름·영속 경로·내부 포트, 기존 ingress와의
   연결, korcounsel.com DNS·TLS·인증·가동 시간·백업·복원 경로를 확정해야 한다.
4. 지금은 후보 조사만 완료했다. 실제 대상 변경과 배포는 별도 결정이며,
   로컬 수집·정리 후 일관된 snapshot으로 이관하는 사용자 지시는 유지한다.

조사 명령: SSH 해석 설정, hostname/uname/os-release, uptime/nproc/free,
df/lsblk/ss, docker ps/stats/system df 및 mount 경로, vmstat, 프로세스 RSS,
읽기 전용 du, IMDSv2 metadata, 로컬 PostgreSQL 크기·blob 합계 조회.
환경파일·credential·private key 본문은 출력하거나 변경하지 않았다.
