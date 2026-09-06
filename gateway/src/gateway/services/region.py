"""cross-region inference profile 접두사 재작성.

Bedrock 의 inference profile ID 는 리전군 접두사를 갖습니다. 호출 리전과 접두사가 다르면
`ValidationException` 이 납니다.

    us.anthropic.claude-...      미국
    eu.anthropic....             유럽
    apac.anthropic....           아시아·태평양
    global.anthropic....         어디서든 해석됨 — 그대로 통과

**이건 안전망이지 정상 경로가 아닙니다.** 재작성이 상시 발생한다면 카탈로그의 리전이 잘못
등록됐다는 신호이므로 로그로 드러냅니다(docs/04).
"""

from __future__ import annotations

import structlog

logger = structlog.get_logger(__name__)

KNOWN_PREFIXES = frozenset({"us", "eu", "apac", "global"})


def _prefix_for_region(region: str) -> str | None:
    """리전 이름의 앞부분으로 리전군을 정합니다.

    표를 하드코딩하면 리전이 추가될 때마다 여기를 고쳐야 하고, 빠뜨리면 조용히 재작성이
    멈춥니다. 모르는 리전군은 None 을 돌려 **손대지 않는** 쪽으로 실패합니다.
    """
    if region.startswith("us-"):
        return "us"
    if region.startswith("eu-"):
        return "eu"
    if region.startswith("ap-"):
        return "apac"
    return None


def rewrite_model_id(model_id: str, region: str | None) -> str:
    if not region:
        return model_id

    head, sep, rest = model_id.partition(".")
    if not sep or head not in KNOWN_PREFIXES:
        return model_id  # cross-region inference profile 이 아닙니다
    if head == "global":
        return model_id

    target = _prefix_for_region(region)
    if target is None or target == head:
        return model_id

    rewritten = f"{target}.{rest}"
    logger.info("model.id_rewritten", original=model_id, rewritten=rewritten, region=region)
    return rewritten
