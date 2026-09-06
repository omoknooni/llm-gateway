-- 런타임 DB 역할. 비밀번호는 run_migration.sh 가 환경변수로 주입합니다.
--
-- [보안] 기본값(*_change_me)은 로컬 개발 전용 플레이스홀더입니다. 로컬이 아닌 모든 환경에서는
-- BACKEND_APP_PASSWORD / GATEWAY_APP_PASSWORD 를 시크릿에서 주입해야 합니다.
--
-- 두 역할 모두 DDL 권한이 없습니다. 스키마 변경은 이 스크립트를 실행하는 별도 역할만 합니다.

DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'backend_app') THEN
        EXECUTE format('CREATE ROLE backend_app WITH LOGIN PASSWORD %L', :'backend_app_password');
    END IF;
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'gateway_app') THEN
        EXECUTE format('CREATE ROLE gateway_app WITH LOGIN PASSWORD %L', :'gateway_app_password');
    END IF;
END
$$;
