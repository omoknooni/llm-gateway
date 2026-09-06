# Admin Console (Next.js SSR) 이미지.
#
# standalone 출력을 쓰므로 런타임에는 node_modules 전체가 필요하지 않습니다.
# EKS 에 배포하며, 공개 진입점은 gateway 뿐이고 이 앱은 내부 경계 뒤에 둡니다(ADR-0002).

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --ignore-scripts

FROM node:22-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
RUN npm run build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV PORT=3000
ENV HOSTNAME=0.0.0.0

# 루트로 돌리지 않습니다.
RUN addgroup --system --gid 1001 nodejs && adduser --system --uid 1001 nextjs

COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

# backend 를 건드리지 않는 헬스체크. Admin API 가 흔들린다고 콘솔 파드가 죽으면 장애가 번집니다.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
  CMD wget -q --spider http://127.0.0.1:3000/api/health || exit 1

CMD ["node", "server.js"]
