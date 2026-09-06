-- 스키마별 최소 권한. 08 문서 C4 의 접근 경계를 그대로 옮긴 것입니다.
--
--   스키마    backend_app                                  gateway_app
--   auth      CRUD                                         SELECT + virtual_keys.last_used_at UPDATE
--   model     CRUD                                         SELECT
--   budget    budget_configs CRUD, budget_usages 조회/재시드  SELECT + budget_usages UPSERT
--   usage     SELECT + 집계 테이블 쓰기                       usage_events INSERT
--   audit     CRUD                                         접근 없음
--
-- 여기서는 스키마 사용 권한과 ALTER DEFAULT PRIVILEGES 만 겁니다. 아직 테이블이 없기 때문입니다.
-- 테이블 단위 권한(gateway 의 컬럼 UPDATE, backend 의 usage 쓰기 제한)은 alembic 이후
-- grants/*.sql 이 겁니다.

-- ── backend_app ──
GRANT USAGE ON SCHEMA auth, model, budget, usage, audit TO backend_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA auth, model, budget, audit
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO backend_app;
ALTER DEFAULT PRIVILEGES IN SCHEMA usage GRANT SELECT ON TABLES TO backend_app;

-- ── gateway_app ──
-- 정책을 읽어 집행만 합니다. 정책을 정의하지 않습니다.
GRANT USAGE ON SCHEMA auth, model, budget, usage TO gateway_app;

ALTER DEFAULT PRIVILEGES IN SCHEMA auth, model, budget GRANT SELECT ON TABLES TO gateway_app;

-- audit 스키마는 gateway 에 노출하지 않습니다(감사 로그는 control plane 의 것입니다).
REVOKE ALL ON SCHEMA audit FROM gateway_app;
