# Deployment and Operations

## Objective

플랫폼을 AWS 내부 환경에 안전하게 배포하고, 보안 경계, 관제, 운영 절차를 일관되게 정의합니다.

## Baseline Assumptions

- 배포 환경은 AWS 내부망 또는 사내 전용 AWS 계정입니다.
- Bedrock 연동은 내부 서비스 계정 또는 역할 기반 접근으로 수행합니다.
- 사용자와 애플리케이션은 Bedrock 자격 증명이 아니라 Virtual Key로 Gateway를 사용합니다.

## Deployment Building Blocks

- LiteLLM Gateway service
- FastAPI control plane service
- Next.js operations dashboard
- PostgreSQL
- Redis
- log and metrics pipeline

## AWS Baseline

1차 AWS 배포 기준은 다음을 권장합니다.

- Gateway와 backend는 ECS Fargate service로 배포
- Frontend도 Next.js SSR runtime을 유지하기 위해 ECS Fargate service로 배포
- PostgreSQL은 Amazon RDS for PostgreSQL 사용
- Redis는 Amazon ElastiCache for Redis OSS 사용
- 공개 진입점은 public ALB로 두고 gateway를 노출
- 관리자 UI와 backend admin API는 internal ALB 뒤에 두고 frontend를 기본 경로로 라우팅
- ECS task role을 통해 Bedrock 호출 권한을 부여하고 장기 자격 증명은 두지 않음
- Secrets Manager를 사용해 애플리케이션 런타임 secret을 주입

Terraform 기준선은 `infra/aws/`를 참조합니다.

## Security Boundaries

- Bedrock 자격 증명은 Gateway 또는 control plane의 보호된 런타임 경계 내에만 존재해야 합니다.
- 외부 호출자는 Virtual Key 외의 provider credential을 알 필요가 없어야 합니다.
- 관리자 작업은 일반 사용자 호출과 분리된 인증/권한 체계를 사용해야 합니다.
- 감사 로그는 변경 추적이 가능하도록 보존해야 합니다.

## Operational Concerns

- 서비스별 헬스체크와 기본 메트릭 수집
- 키 발급/폐기/로테이션 절차 운영화
- 모델 단가 참조 데이터 갱신 절차
- 장애 시 호출 실패율과 비용 집계 누락 여부 확인
- 실험 환경과 운영 환경의 데이터 분리

## Recommended Monitoring Signals

- request throughput
- error rate
- latency percentiles
- token volume
- estimated cost trend
- revoked key access attempts
- model-specific failure spikes

## Runbook Starters

- Bedrock provider 장애 시 fallback 또는 제한 정책 검토
- 비정상 사용량 급증 시 해당 키 또는 팀 범위 차단
- 비용 급증 시 상위 팀/모델 원인 분석
- SSO/IdP 동기화 실패 시 권한 데이터 최신성 점검

## Implementation Notes

- 운영 절차는 코드 구현과 함께 점진적으로 구체화합니다.
- 초기에는 단순한 운영 메트릭부터 시작하되, 감사 가능성과 비용 추적 가능성은 첫 단계부터 확보합니다.
