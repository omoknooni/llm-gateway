# infra/terraform — AWS 리소스

llm-gateway 운영에 필요한 AWS 클라우드 리소스를 정의합니다.

- 네트워크(VPC, 서브넷, 보안 그룹)
- Amazon EKS 클러스터와 OIDC provider, 워크로드별 IRSA IAM role
- Amazon RDS (PostgreSQL), Amazon ElastiCache (Redis)
- Amazon Bedrock 접근 IAM 정책
- Amazon ECR, 시크릿 저장소
