#!/usr/bin/env bash
# 마이그레이션 실행 진입점. 배포 시 Job 으로 한 번 실행합니다.
#   1) init/*.sql  — 스키마, 확장, DB 역할, GRANT (멱등)
#   2) alembic upgrade head — 테이블과 제약
set -euo pipefail

cd "$(dirname "$0")"

: "${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL 이 필요합니다}"

# psql 은 asyncpg 드라이버 접두사를 모릅니다.
PSQL_URL="${MIGRATION_DATABASE_URL/postgresql+asyncpg:/postgresql:}"

echo "==> init SQL 적용"
for f in init/*.sql; do
    [ -e "$f" ] || continue
    echo "    - $f"
    psql "$PSQL_URL" -v ON_ERROR_STOP=1 \
        -v backend_app_password="${BACKEND_APP_PASSWORD:-backend_app_change_me}" \
        -v gateway_app_password="${GATEWAY_APP_PASSWORD:-gateway_app_change_me}" \
        -f "$f"
done

echo "==> alembic upgrade head"
alembic upgrade head

echo "==> 완료"
