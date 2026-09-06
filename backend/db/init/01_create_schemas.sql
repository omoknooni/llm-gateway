-- 스키마와 확장. 멱등해야 합니다.
-- 스키마를 도메인별로 나누는 이유는 plane 별 최소 권한 GRANT 의 단위가 되기 때문입니다(01 문서).

CREATE SCHEMA IF NOT EXISTS auth;
CREATE SCHEMA IF NOT EXISTS model;
CREATE SCHEMA IF NOT EXISTS budget;
CREATE SCHEMA IF NOT EXISTS usage;
CREATE SCHEMA IF NOT EXISTS audit;

-- citext: 이메일을 대소문자 구분 없이 유일하게 다루기 위해
CREATE EXTENSION IF NOT EXISTS citext;
-- btree_gist: model_pricings 의 유효 구간 겹침 차단(EXCLUDE 제약)에 필요
CREATE EXTENSION IF NOT EXISTS btree_gist;
