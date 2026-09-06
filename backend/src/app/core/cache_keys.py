"""Redis 키 이름을 만드는 단일 지점.

> **공유 계약** — 키 이름의 소유자는 gateway 입니다(08 문서 C2). backend 는 정책 캐시 키를
> **삭제만** 하고, 집행 카운터는 쓰지도 지우지도 않습니다.

문자열을 여기저기서 조립하면 한 곳만 바뀌었을 때 무효화가 조용히 빗나갑니다.
키를 만드는 코드는 전부 이 모듈을 지납니다.
"""

from __future__ import annotations

import uuid

# ── 정책 캐시: gateway 가 채우고 backend 가 삭제만 ──


def vk_auth(key_hash: str) -> str:
    """VK 인증 컨텍스트."""
    return f"vk:auth:{key_hash}"


def model_policy(alias: str) -> str:
    """모델 해석 + 현재 단가."""
    return f"policy:model:{alias}"


def model_list() -> str:
    """활성 alias 목록.

    원래 gateway 전용 키였지만 **이 키를 낡게 만드는 주체가 backend**(카탈로그 변경)라서
    공유 키로 옮겼습니다(09 문서 Q1). `/v1/models` 응답의 재료이면서 동시에 허용 모델 3층
    해석에서 "team 층 0개 → 카탈로그 ACTIVE 전체"의 재료이기도 합니다.

    상태 전환만이 아니라 `model_aliases` 의 **모든 변경**에서 지웁니다. 목록 항목이
    `supported_dialects`·`max_output_tokens` 를 싣고 있어, 상태만 트리거로 잡으면 방언이 바뀐
    모델이 옛 값으로 남습니다.
    """
    return "policy:model:list"


def allowed_models(scope: str, scope_id: uuid.UUID | str) -> str:
    """허용 모델. scope 는 'team' 또는 'user'."""
    return f"policy:allowed_models:{scope}:{scope_id}"


def budget_policy(scope: str, scope_id: uuid.UUID | str) -> str:
    """예산 설정."""
    return f"policy:budget:{scope.lower()}:{scope_id}"


def rate_limit_policy(scope: str, scope_id: uuid.UUID | str | None, model_alias: str | None) -> str:
    """rate limit 설정. scope_id 가 없으면(GLOBAL) 'global', 모델 전체면 '*'."""
    return f"policy:ratelimit:{scope.lower()}:{scope_id or 'global'}:{model_alias or '*'}"


# ── 집행 카운터: gateway 전용. backend 는 읽기만 ──
#
# 이 키들을 삭제하면 소진액이 0 으로 리셋되고 rate limit 윈도가 풀립니다.
# 무효화 대상에 절대 넣지 않습니다(05·06 문서).


def budget_usage_counter(scope: str, scope_id: uuid.UUID | str, period: str) -> str:
    return f"budget:usage:{scope.lower()}:{scope_id}:{period}"


def rate_limit_counter(scope: str, scope_id: uuid.UUID | str, model_alias: str, window: str) -> str:
    return f"rl:{scope.lower()}:{scope_id}:{model_alias}:{window}"
