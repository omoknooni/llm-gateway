"""요청 방언.

값은 backend 의 `model.api_dialect` enum 과 같아야 합니다 — `usage_events.dialect` 에 그대로
실리므로 다른 이름을 쓰면 집계가 갈립니다. 방언은 파싱·직렬화 계층에만 존재하고, 인증·집행·
기록은 방언과 무관한 같은 경로를 지납니다(ADR-0003).
"""

from __future__ import annotations

from enum import StrEnum


class ApiDialect(StrEnum):
    OPENAI_CHAT = "OPENAI_CHAT"
    ANTHROPIC_MESSAGES = "ANTHROPIC_MESSAGES"


def dialect_for_path(path: str) -> ApiDialect:
    """경로 → 방언.

    미들웨어는 라우팅 전에 실행되므로 오류 응답의 형식을 경로로 정합니다. 어느 쪽도 아니면
    OpenAI 호환으로 답합니다 — 잘못된 경로에 대한 응답 형식은 어차피 client 가 파싱하지 못하고,
    둘 중 하나를 골라야 한다면 더 널리 쓰이는 쪽이 낫습니다.
    """
    if path.startswith("/v1/messages"):
        return ApiDialect.ANTHROPIC_MESSAGES
    return ApiDialect.OPENAI_CHAT
