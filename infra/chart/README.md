# infra/chart — Helm chart

`backend`, `frontend`, `gateway`를 Kubernetes 클러스터에 배포하는 Helm chart를 담습니다.
DB와 캐시는 chart 안에서 운영하지 않고 외부 엔드포인트로 주입받습니다.
