-- 테이블 단위 권한. alembic upgrade head **이후**에 적용합니다(대상 테이블이 존재해야 하므로).
-- 08 문서 C4 의 접근 경계 중, 스키마 기본 권한만으로는 표현할 수 없는 부분입니다.

-- ── backend_app ──
-- usage 스키마의 원천 이벤트는 gateway 의 것입니다. backend 는 읽기만 합니다.
-- 집계 테이블은 backend 의 job 이 씁니다.
REVOKE ALL ON usage.usage_events FROM backend_app;
GRANT SELECT ON usage.usage_events TO backend_app;
GRANT SELECT, INSERT, UPDATE, DELETE
    ON usage.daily_usage_aggregates, usage.monthly_usage_aggregates TO backend_app;

-- ── gateway_app ──
-- 정책을 읽어 집행만 합니다. 정책을 정의하지 않습니다.
GRANT UPDATE (last_used_at) ON auth.virtual_keys TO gateway_app;
GRANT INSERT, UPDATE ON budget.budget_usages TO gateway_app;
GRANT INSERT, SELECT ON usage.usage_events TO gateway_app;
GRANT SELECT ON usage.daily_usage_aggregates, usage.monthly_usage_aggregates TO gateway_app;
