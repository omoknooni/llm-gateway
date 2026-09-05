# frontend — Admin Console (control plane)

Admin 서비스의 웹 콘솔. Next.js SSR 앱으로 동작하며 `backend/`의 admin API만 소비합니다.
브라우저가 admin API를 직접 호출하지 않고, SSR 서버 또는 route handler를 경유합니다.

- 스택: Next.js (App Router) + TypeScript, SSR 런타임 유지
- 작업 브랜치: `feat/admin-frontend`
- 기준 문서: [docs/implementation-plan.md](../docs/implementation-plan.md)
