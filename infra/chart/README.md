# infra/chart — Helm chart

`backend`, `frontend`, `gateway`를 Amazon EKS에 배포하는 Helm chart를 담습니다.

- 워크로드별 ServiceAccount에 IRSA를 연결해 AWS 권한을 부여합니다.
- Ingress는 AWS Load Balancer Controller를 기본 구현체로 씁니다.
- `gateway`만 공개 진입점으로 노출하고, `backend`와 `frontend`는 내부 경계 뒤에 둡니다.
- DB와 캐시는 chart 안에서 운영하지 않고 외부 엔드포인트로 주입받습니다.
