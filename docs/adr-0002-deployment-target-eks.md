# ADR-0002: 애플리케이션 배포 대상을 Amazon EKS로 확정

- Status: Accepted
- Date: 2026-09-06
- Decision Makers: llm-gateway owner

## Context

`backend`, `frontend`, `gateway` 세 앱은 Kubernetes에 배포하기로 되어 있었지만, 어떤 Kubernetes인지는
미확정이었습니다. 선택지는 두 갈래였습니다.

- **CSP 중립 chart** — 표준 리소스만 써서 어느 클러스터에나 올라가게 하고, AWS 자격 증명 주입과
  Ingress는 별도로 설계합니다.
- **EKS 전제** — IRSA, AWS Load Balancer Controller 같은 AWS 네이티브 메커니즘을 기본 경로로 씁니다.

이 결정을 미루면 chart의 ServiceAccount·Ingress·Secret 주입 방식이 전부 미정으로 남아
`infra/chart`와 `infra/terraform` 착수가 막힙니다.

한편 이 플랫폼의 다른 축은 이미 AWS로 고정되어 있습니다. 모델 호출은 Bedrock, DB는 RDS,
캐시는 ElastiCache입니다. 참조 구현 `awsome-ai-gateway`도 EKS Fargate 전제로 만들어져 있어
IRSA·ALB Ingress 구성을 그대로 참고할 수 있습니다.

즉 이식성을 위해 지불하는 비용(자격 증명 주입 자체 설계, Ingress 추상화)에 비해,
실제로 다른 CSP로 옮길 가능성은 낮은 상태입니다.

## Decision

애플리케이션 컴퓨팅 배포 대상을 **Amazon EKS로 확정**합니다.

- `infra/chart/`의 Helm chart는 EKS를 전제로 작성합니다. 워크로드별 ServiceAccount에 **IRSA**를
  연결해 AWS 권한을 부여하고, Ingress는 **AWS Load Balancer Controller**를 기본 구현체로 씁니다.
- Bedrock 접근 자격 증명은 IRSA로 해결합니다. 장기 AWS 액세스 키를 Secret이나 이미지에 두지 않습니다.
- `infra/terraform/`는 EKS 클러스터, 노드 구성, IRSA용 IAM role과 OIDC provider,
  RDS, ElastiCache, ECR, 시크릿 저장소를 정의합니다.
- 상태 저장 계층은 클러스터 안에서 운영하지 않습니다. PostgreSQL은 Amazon RDS,
  Redis는 Amazon ElastiCache를 외부 엔드포인트로 주입받습니다.
- 애플리케이션 코드에는 여전히 CSP별 분기를 두지 않습니다. AWS 종속은 chart와 terraform,
  그리고 자격 증명 획득 방식(기본 credential chain)에만 존재합니다.

## Consequences

### Positive

- chart의 ServiceAccount·Ingress·자격 증명 주입 방식이 즉시 확정되어 infra 작업을 착수할 수 있습니다.
- IRSA로 장기 자격 증명 없이 Bedrock 권한을 워크로드별 최소 권한으로 부여할 수 있습니다.
- 참조 구현의 EKS 구성(IRSA, ALB Ingress, ESO 패턴)을 그대로 참고할 수 있어 설계 비용이 줄어듭니다.
- 클러스터 ↔ RDS/ElastiCache가 같은 VPC 안에 놓여 네트워크 경로와 지연이 단순해집니다.

### Negative

- 다른 CSP나 온프레미스 클러스터로 옮기려면 chart의 ServiceAccount·Ingress 부분을 다시 써야 합니다.
- 로컬 kind/minikube에서는 IRSA와 ALB Ingress가 동작하지 않으므로, 로컬 검증 경로가 운영 경로와
  달라집니다.
- EKS 클러스터 자체의 운영 부담(버전 업그레이드, 애드온 관리)을 집니다.

### Follow-up Implications

- 워크로드별 IAM role과 신뢰 정책을 terraform에서 정의하고, chart의 ServiceAccount annotation과
  이름 규약을 맞춰야 합니다.
- 로컬 개발은 IRSA 대신 개발자 AWS 프로필을 쓰는 경로를 별도로 마련해야 합니다.
  코드는 자격 증명 획득을 기본 credential chain에 위임해 두 경로를 모두 수용합니다.
- 관리자 콘솔(`frontend`)과 admin API(`backend`)는 내부 경계 뒤에 두고 `gateway`만 공개 진입점으로
  노출하는 Ingress 구성이 필요합니다.
- 노드 형태(Fargate vs 관리형 노드그룹)는 이 ADR에서 확정하지 않습니다. 워크로드 특성이 드러난 뒤
  별도로 정합니다.

## Options

### 1. CSP 중립 순수 Kubernetes

표준 리소스만 사용하고 AWS 전용 controller나 IRSA를 전제하지 않습니다.

- 장점
  - 클러스터 교체나 온프레미스 이전 시 chart를 그대로 사용할 수 있습니다.
  - 로컬 kind/minikube에서 동일한 chart로 검증할 수 있습니다.
- 단점
  - Bedrock 자격 증명 주입 방식을 직접 설계해야 하고, 장기 키를 쓰지 않으려면 결국 별도 메커니즘이 필요합니다.
  - Ingress·TLS·시크릿 동기화를 chart에서 명시적으로 다뤄야 합니다.
- 선택하지 않은 이유
  - 모델·DB·캐시가 모두 AWS로 고정된 상태에서 컴퓨팅만 이식 가능하게 두는 실익이 작고,
    그 대가로 자격 증명 설계 부담을 집니다.

### 2. Amazon EKS 전제

IRSA와 AWS Load Balancer Controller를 기본 경로로 사용합니다.

- 장점
  - 자격 증명·Ingress 문제가 매니지드 메커니즘으로 해결됩니다.
  - 참조 구현 구성을 재사용할 수 있습니다.
- 단점
  - 배포 자산이 AWS에 묶이고, 로컬 검증 경로가 운영과 달라집니다.
- 선택하지 않은 이유
  - 해당 없음
- 최종 선택 여부: Accepted

### 3. ECS Fargate

Kubernetes를 쓰지 않고 ECS 서비스로 배포합니다.

- 장점
  - 클러스터 운영 부담이 가장 낮습니다.
- 단점
  - Helm chart 자산을 포기해야 하고, 사내 Kubernetes 운영 관행과 어긋납니다.
  - 워크로드가 늘어날 때 스케줄링·배포 표현력이 부족합니다.
- 선택하지 않은 이유
  - 이전 기준선이 ECS였으나 Kubernetes 배포로 방향이 잡혔고, 되돌릴 이유가 없습니다.

## References

- [docs/implementation-plan.md](implementation-plan.md)
- [ADR-0001: gateway 자체 구현](adr-0001-self-hosted-data-plane.md)
- 참조 구현: `awsome-ai-gateway` (EKS Fargate, IRSA, ALB Ingress, External Secrets Operator)
