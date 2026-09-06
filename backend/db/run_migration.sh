#!/usr/bin/env bash
# 마이그레이션 실행 진입점. 배포 시 Job 으로 한 번 실행합니다.
#   1) init/*.sql    — 스키마, 확장, DB 역할, 스키마 권한 (멱등)
#   2) alembic upgrade head — 테이블과 제약
#   3) grants/*.sql  — 테이블 단위 권한 (대상 테이블이 존재해야 하므로 마지막)
set -euo pipefail

cd "$(dirname "$0")"

: "${MIGRATION_DATABASE_URL:?MIGRATION_DATABASE_URL 이 필요합니다}"

# psql 은 asyncpg 드라이버 접두사를 모릅니다.
PSQL_URL="${MIGRATION_DATABASE_URL/postgresql+asyncpg:/postgresql:}"

apply_sql() {
    for f in "$1"/*.sql; do
        [ -e "$f" ] || continue
        echo "    - $f"
        psql "$PSQL_URL" -v ON_ERROR_STOP=1 \
            -v backend_app_password="${BACKEND_APP_PASSWORD:-backend_app_change_me}" \
            -v gateway_app_password="${GATEWAY_APP_PASSWORD:-gateway_app_change_me}" \
            -f "$f"
    done
}

echo "==> init SQL 적용 (스키마, 역할, 스키마 권한)"
apply_sql init

echo "==> alembic upgrade head"
alembic upgrade head

echo "==> 테이블 단위 권한 적용"
apply_sql grants

echo "==> 완료"
