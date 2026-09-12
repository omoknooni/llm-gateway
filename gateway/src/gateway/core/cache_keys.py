"""Redis 키 이름을 만드는 단일 지점.

키 이름의 소유자는 gateway 이지만, backend 가 이미 구현해 둔 이름을 그대로 채택했습니다
(공유 계약 C2). 문자열을 여기저기서 조립하면 한 곳만 바뀌었을 때 무효화가 조용히 빗나갑니다.

    정책 캐시   gateway 가 채우고 backend 는 **삭제만** 합니다.
    gateway 전용 backend 는 존재를 알되 건드리지 않습니다.

모든 정책 캐시에 TTL 상한이 있습니다. 무효화 실패의 영향이 "영구 불일치"가 아니라
"TTL 만큼의 반영 지연"에 머물러야 하기 때문입니다.
"""

from __future__ import annotations

# ── 정책 캐시 (공유) ──


def vk_auth(key_hash: str) -> str:
    return f"vk:auth:{key_hash}"


def model_policy(alias: str) -> str:
    return f"policy:model:{alias}"


def model_list() -> str:
    """카탈로그의 ACTIVE alias 목록.

    `/v1/models` 응답의 재료이면서 허용 모델 3층 해석에서 "team 층 0개 → 카탈로그 전체"의
    재료이기도 합니다. 그래서 backend 는 `model_aliases` 의 **모든** 변경에서 이 키를 지웁니다
    (docs/06 Q1).
    """
    return "policy:model:list"


def allowed_models(scope: str, scope_id: str) -> str:
    """scope 는 'team' 또는 'user'."""
    return f"policy:allowed_models:{scope}:{scope_id}"


# ── gateway 전용 ──


def vk_miss(key_hash: str) -> str:
    """미등록 키의 음성 캐시.

    없으면 잘못된 키 하나로 만드는 트래픽이 그대로 DB 조회가 됩니다. 짧은 TTL 이라
    발급 직후의 키가 오래 막히지 않습니다.
    """
    return f"vk:miss:{key_hash}"


# ── 정책 캐시: 집행 (Phase 4, docs/08) ──


def budget_policy(scope: str, scope_id: str) -> str:
    """예산 설정. scope 는 'team' 또는 'user'."""
    return f"policy:budget:{scope.lower()}:{scope_id}"


def rate_limit_policy(scope: str, scope_id: str | None, model_alias: str | None) -> str:
    """rate limit 설정. GLOBAL 은 scope_id 자리에 'global', 전체 모델은 alias 자리에 '*'."""
    return f"policy:ratelimit:{scope.lower()}:{scope_id or 'global'}:{model_alias or '*'}"


# ── 집행 카운터: gateway 전용. backend 는 읽기만 (docs/08) ──
#
# 이 키들을 지우면 소진액이 0 으로 리셋되고 rate limit 윈도가 풀립니다.
# 무효화 대상에 절대 넣지 않습니다.
#
# **모든 카운터 연산은 정확히 한 키만 건드립니다.** 그래서 ElastiCache cluster mode 용
# 해시 태그(`{}`)가 필요 없습니다 — 같은 슬롯을 요구하는 것은 multi-key 연산뿐입니다.


def budget_usage_counter(scope: str, scope_id: str, period: str) -> str:
    """월 소진 누적액. `period` 는 UTC 기준 `YYYY-MM`."""
    return f"budget:usage:{scope.lower()}:{scope_id}:{period}"


def rate_limit_counter(scope: str, scope_id: str, model_alias: str, window: str) -> str:
    """집행 카운터.

    `window` 가 한도 종류를 함께 담습니다 — `rpm:{분}` / `tpm:{분}` / `conc`. rpm 과 tpm 이
    같은 분에 같은 키를 쓰면 안 되는데, 자리를 하나 더 늘리면 backend 의 4인자 헬퍼와
    형태가 갈립니다(docs/08).
    """
    return f"rl:{scope.lower()}:{scope_id}:{model_alias}:{window}"
