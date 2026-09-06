import type { NextConfig } from 'next';

/**
 * 콘솔은 SSR 로 동작합니다(AGENTS.md). standalone 출력은 EKS 배포용 이미지를 얇게 만듭니다.
 *
 * CSP 의 connect-src 에 Admin API 를 넣지 않는 것은 의도입니다. 브라우저는 backend 를 직접
 * 호출하지 않고 항상 SSR 서버를 경유합니다(00 문서 경계 규칙).
 */
const SECURITY_HEADERS = [
  { key: 'X-Content-Type-Options', value: 'nosniff' },
  { key: 'X-Frame-Options', value: 'DENY' },
  { key: 'Referrer-Policy', value: 'strict-origin-when-cross-origin' },
  { key: 'Permissions-Policy', value: 'camera=(), microphone=(), geolocation=()' },
  { key: 'Strict-Transport-Security', value: 'max-age=31536000; includeSubDomains' },
  {
    key: 'Content-Security-Policy',
    value: [
      "default-src 'self'",
      // Next 의 인라인 부트스트랩 스크립트 때문에 unsafe-inline 이 필요합니다.
      "script-src 'self' 'unsafe-inline'",
      "style-src 'self' 'unsafe-inline'",
      "img-src 'self' data:",
      "font-src 'self' data:",
      "connect-src 'self'",
      "frame-ancestors 'none'",
      "base-uri 'self'",
      "form-action 'self'",
    ].join('; '),
  },
];

const nextConfig: NextConfig = {
  output: 'standalone',
  reactStrictMode: true,
  poweredByHeader: false,
  async headers() {
    return [{ source: '/(.*)', headers: SECURITY_HEADERS }];
  },
};

export default nextConfig;
