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
