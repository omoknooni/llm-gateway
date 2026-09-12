#!/usr/bin/env bash
# 통합 테스트 스택 제어.
#
# 로컬에 psql 이 없어도 되도록 init/grants SQL 은 postgres 컨테이너 안에서 실행합니다.
# alembic 은 로컬 venv 로 돌립니다(마이그레이션 코드가 곧 테스트 대상입니다).
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE="docker compose -f docker-compose.test.yml"
PGPORT_HOST=55432
REDIS_PORT_HOST=56379

export TEST_DATABASE_URL="postgresql+asyncpg://postgres:postgres@localhost:${PGPORT_HOST}/llm_gateway_test"
export TEST_REDIS_URL="redis://localhost:${REDIS_PORT_HOST}/0"
export TEST_BACKEND_APP_URL="postgresql+asyncpg://backend_app:backend_app_test@localhost:${PGPORT_HOST}/llm_gateway_test"
export TEST_GATEWAY_APP_URL="postgresql+asyncpg://gateway_app:gateway_app_test@localhost:${PGPORT_HOST}/llm_gateway_test"

psql_in_container() {
    $COMPOSE exec -T postgres psql \
        "postgresql://postgres:postgres@localhost:5432/llm_gateway_test" \
        -v ON_ERROR_STOP=1 \
        -v backend_app_password=backend_app_test \
        -v gateway_app_password=gateway_app_test \
        "$@"
}

apply_sql_dir() {
    for f in "$1"/*.sql; do
        [ -e "$f" ] || continue
        echo "    - $f"
        psql_in_container -f "/db/${f#db/}"
    done
}

cmd_up() {
    echo "==> 스택 기동"
    $COMPOSE up -d --wait
    cmd_migrate
}

cmd_migrate() {
    echo "==> init SQL (스키마, 역할, 스키마 권한)"
    apply_sql_dir db/init

    echo "==> alembic upgrade head"
    (cd db && MIGRATION_DATABASE_URL="$TEST_DATABASE_URL" ../.venv/bin/alembic upgrade head)

    echo "==> 테이블 단위 권한"
    apply_sql_dir db/grants

    echo "==> 완료"
}

cmd_test() {
    # 통합 테스트는 이 두 변수가 있을 때만 돕니다. 없으면 conftest 가 skip 합니다.
    .venv/bin/python -m pytest "${@:-tests}" -q
}

cmd_psql() {
    psql_in_container "$@"
}

cmd_down() {
    echo "==> 스택 제거 (tmpfs 라 데이터도 함께 사라집니다)"
    $COMPOSE down -v --remove-orphans
}

cmd_reset() {
    cmd_down
    cmd_up
}

case "${1:-}" in
    up)      cmd_up ;;
    migrate) cmd_migrate ;;
    test)    shift; cmd_test "$@" ;;
    psql)    shift; cmd_psql "$@" ;;
    down)    cmd_down ;;
    reset)   cmd_reset ;;
    *)
        echo "사용법: $0 {up|migrate|test|psql|down|reset}" >&2
        exit 2
        ;;
esac
