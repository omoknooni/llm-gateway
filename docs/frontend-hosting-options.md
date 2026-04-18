# ADR-001: Frontend Hosting Strategy on AWS

- Status: Accepted
- Date: 2026-04-18
- Decision Makers: LLM Gateway platform team

## Context

현재 `frontend/`는 Next.js 기반 관리자 애플리케이션이며, 다음 조건이 중요합니다.

- 운영 표준성을 위해 frontend도 backend, gateway와 동일하게 container + ECS Service 패턴으로 관리하고 싶습니다.
- 이미 구성된 앱은 Next.js SSR 런타임을 사용하므로 정적 호스팅만으로는 맞지 않습니다.
- 이 UI는 일반 사용자용 공개 사이트가 아니라 관리자 전용 접근면입니다.
- 관리자 UI는 backend admin API, gateway 운영 링크, 내부 네트워크 제어와 함께 다뤄지는 것이 더 자연스럽습니다.

이 조건 때문에 단순한 정적 호스팅보다, VPC 내부에 배치되는 애플리케이션 런타임이 더 적합합니다.

## Decision

frontend는 AWS ECS Fargate Service로 배포합니다.

- frontend 컨테이너는 Next.js SSR 앱을 `build + start` 방식으로 실행합니다.
- frontend service는 private subnet에 배치합니다.
- 관리자 접근 전용 internal ALB를 추가하고, 이 ALB의 기본 경로는 frontend로 라우팅합니다.
- 같은 internal ALB에서 `/admin*`, `/internal*`, `/docs*`, `/openapi.json`, `/healthz`는 backend service로 라우팅합니다.
- gateway는 별도의 public ALB 경로로 유지해 OpenAI 호환 호출 진입점 역할을 맡깁니다.

즉, 외부 모델 호출 경로와 내부 관리자 UI 경로를 분리하고, 관리자면은 VPC 내부에서만 접근 가능한 운영면으로 둡니다.

## Consequences

### Positive

- frontend, backend, gateway가 모두 ECS 운영 모델을 공유하므로 배포, 로그, 알람, autoscaling 패턴이 일관됩니다.
- SSR 제약 없이 Next.js 런타임을 그대로 유지할 수 있습니다.
- 관리자 UI와 backend admin API를 internal ALB 뒤에 모아 내부 운영면으로 분리할 수 있습니다.
- 사내 VPN, Direct Connect, Transit Gateway 같은 네트워크 경로와 연결하기 쉬워집니다.

### Negative

- Amplify Hosting이나 S3 + CloudFront보다 운영 복잡도와 비용이 증가합니다.
- ALB, ECS, ECR, 배포 파이프라인, 로그 보존 등 직접 관리해야 할 요소가 많아집니다.
- frontend 이미지 빌드와 배포 속도가 정적 자산 배포보다 느릴 수 있습니다.

### Follow-up Implications

- production 환경에서는 internal ALB에도 HTTPS, ACM, 사내 DNS 연동이 필요합니다.
- frontend 이미지도 backend/gateway와 동일하게 ECR push 및 ECS rollout 절차에 포함해야 합니다.
- 관리자 접근 CIDR 또는 사내 네트워크 연결 정책을 Terraform 변수로 운영 환경마다 조정해야 합니다.

## Alternatives Considered

### 1. AWS Amplify Hosting

검토는 했지만 채택하지 않았습니다.

- 장점
  - Next.js SSR 앱을 관리형으로 빠르게 배포할 수 있습니다.
  - Git 기반 배포와 CloudFront 통합이 쉽습니다.
- 채택하지 않은 이유
  - 다른 서비스가 ECS 표준을 따르는 상황에서 운영 패턴이 분리됩니다.
  - 관리자 전용 UI를 VPC 내부 경계 안에 두려는 목표와 잘 맞지 않습니다.

### 2. S3 + CloudFront

정적 사이트라면 매우 좋은 선택이지만 이번 결정에는 맞지 않았습니다.

- 장점
  - 가장 단순하고 저렴한 구성입니다.
  - 정적 대시보드라면 운영 부담이 매우 낮습니다.
- 채택하지 않은 이유
  - 현재 frontend는 SSR 기반 런타임을 사용합니다.
  - 관리자 전용 내부 운영면이라는 요구와는 거리가 있습니다.

### 3. ECS Fargate

최종 채택안입니다.

- 장점
  - SSR과 container runtime을 그대로 유지할 수 있습니다.
  - backend/gateway와 동일한 운영 표준을 따를 수 있습니다.
  - internal ALB와 private subnet 조합으로 관리자 접근면을 분리할 수 있습니다.
- trade-off
  - 운영 부담과 비용은 가장 큽니다.

## References

- AWS Amplify Hosting supports Next.js SSR apps and Next.js versions up through 15: https://docs.aws.amazon.com/en_us/amplify/latest/userguide/ssr-amplify-support.html
- AWS documents that Amplify Hosting compute fully manages the resources required to deploy a Next.js SSR app: https://docs.aws.amazon.com/amplify/latest/userguide/deploy-nextjs-app.html
- AWS S3 documentation explicitly recommends Amplify Hosting for secure static website hosting on S3 content: https://docs.aws.amazon.com/AmazonS3/latest/dev/WebsiteHosting.html
- AWS App Runner overview for containerized web services: https://docs.aws.amazon.com/apprunner/latest/dg/what-is-apprunner.html
