-- 런타임 DB 역할. 비밀번호는 run_migration.sh 가 환경변수로 주입합니다.
--
-- [보안] 기본값(*_change_me)은 로컬 개발 전용 플레이스홀더입니다. 로컬이 아닌 모든 환경에서는
-- BACKEND_APP_PASSWORD / GATEWAY_APP_PASSWORD 를 시크릿에서 주입해야 합니다.
--
-- 두 역할 모두 DDL 권한이 없습니다. 스키마 변경은 이 스크립트를 실행하는 별도 역할만 합니다.
--
-- [주의] psql 변수(:'name')는 **dollar-quoted 블록 안에서 치환되지 않습니다.**
-- 그래서 `DO $$ ... :'backend_app_password' ... $$` 형태는 문법 오류로 끝납니다.
-- 변수를 블록 밖에 두고 `\gexec` 로 실행합니다. WHERE NOT EXISTS 가 멱등성을 유지합니다
-- (조건이 거짓이면 행이 없어 아무것도 실행되지 않습니다).

SELECT format('CREATE ROLE backend_app WITH LOGIN PASSWORD %L', :'backend_app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'backend_app')
\gexec

SELECT format('CREATE ROLE gateway_app WITH LOGIN PASSWORD %L', :'gateway_app_password')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'gateway_app')
\gexec
