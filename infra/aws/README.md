# AWS Terraform Stack

이 디렉터리는 사내 LLM Gateway를 AWS에 배포하기 위한 Terraform 기준선을 제공합니다.

## What It Creates

- VPC with public, private, and database subnets across 2 AZs
- Public ALB for gateway request routing
- Internal ALB for admin UI and backend admin APIs
- ECS Fargate cluster with 3 services
  - `gateway`: LiteLLM proxy
  - `backend`: FastAPI control plane
  - `frontend`: Next.js SSR admin app
- Amazon RDS for PostgreSQL
- Amazon ElastiCache for Redis OSS
- Amazon ECR repositories for backend, gateway, and frontend images
- Secrets Manager secrets for app runtime configuration
- CloudWatch log groups for ECS services

## Routing Model

- Public ALB 기본 경로는 LiteLLM gateway로 전달됩니다.
- Internal admin ALB 기본 경로는 Next.js frontend로 전달됩니다.
- Internal admin ALB의 `/admin*`, `/internal*`, `/docs*`, `/openapi.json`, `/healthz`는 backend로 전달됩니다.

## Assumptions

- ECS task 이미지는 별도로 빌드해 ECR에 push합니다.
- Bedrock 호출은 ECS task role을 사용합니다.
- frontend는 SSR 모드를 유지하므로 ECS에서 containerized Next.js runtime으로 운영합니다.
- 관리자 UI는 internal ALB를 통해 VPC 내부 또는 연결된 사내 네트워크에서만 접근하는 것을 전제로 합니다.
- 현재 스택은 HTTP ALB 기준선입니다. 운영 전환 시 ACM, HTTPS listener, WAF, Route 53 연동을 추가하는 것을 권장합니다.

## Quick Start

```bash
cd infra/aws
terraform init
terraform plan -out tfplan
terraform apply tfplan
```

배포 전에는 `terraform.tfvars.example`을 복사해 환경별 값으로 조정하고, apply 전에 backend/gateway/frontend 이미지 태그가 ECR에 존재하는지 확인하세요.
