"""요청을 보낸 도구(client)를 분류합니다.

**client 는 인가 신호가 아닙니다.** User-Agent 와 헤더는 client 가 마음대로 쓸 수 있는 값이라
위조 가능합니다. 그래서 이 값은 세 곳에만 쓰입니다 — 사용량 귀속(`usage_events.client`),
운영 관측, 거절 분석(`auth_events.client`). 잘못 분류돼도 집계 라벨 하나가 'other' 가 될 뿐
어떤 권한도 열리지 않습니다(docs/03).

I/O 가 없는 순수 함수입니다. 실패할 것이 없어야 하는 경로이기 때문입니다.
"""

from __future__ import annotations

from collections.abc import Mapping

from gateway.config import CLIENT_OTHER

CLIENT_CLAUDE_CODE = "claude-code"
CLIENT_CLAUDE_DESKTOP = "claude-desktop"
CLIENT_CODEX = "codex"
CLIENT_OPENAI_SDK = "openai-sdk"

#: 선언 헤더. 사내 서비스는 UA 를 추측당하기보다 자기 이름을 선언하는 편이 정확합니다.
DECLARED_HEADER = "x-llmgw-client"


def identify_client(headers: Mapping[str, str], registered: frozenset[str]) -> str:
    """'claude-code' | 'claude-desktop' | 'codex' | 'openai-sdk' | 'other'.

    우선순위 순으로 판정하고 첫 일치에서 멈춥니다. 결과는 항상 `registered` 안의 값이며,
    그 밖이면 'other' 로 떨어집니다 — 이 필터가 집계 축과 메트릭 라벨의 카디널리티 상한입니다.
    """
    h = {k.lower(): v for k, v in headers.items()}

    # 1) 선언 헤더. 등록된 값일 때만 인정하고, 아니면 아래 추론으로 내려갑니다.
    declared = h.get(DECLARED_HEADER, "").strip()
    if declared and declared in registered:
        return declared

    ua = h.get("user-agent", "")
    platform = h.get("anthropic-client-platform", "")
    originator = h.get("originator", "")

    # 2) 데스크톱 계열을 CLI 보다 **먼저** 봅니다. 두 도구가 같은 'claude-cli/' UA 접두사를
    #    쓰기 때문에, 순서를 뒤집으면 데스크톱이 CLI 로 잘못 분류됩니다.
    if platform == "desktop_app" or "claude-desktop" in ua or ("Electron/" in ua and "Claude/" in ua):
        return _registered_or_other(CLIENT_CLAUDE_DESKTOP, registered)

    if originator.startswith("codex") or "codex_cli_rs" in ua or ua.startswith("codex/"):
        return _registered_or_other(CLIENT_CODEX, registered)

    if ua.startswith("claude-cli/"):
        return _registered_or_other(CLIENT_CLAUDE_CODE, registered)

    if ua.startswith("OpenAI/") or "openai-python" in ua or "openai-node" in ua:
        return _registered_or_other(CLIENT_OPENAI_SDK, registered)

    return CLIENT_OTHER


def _registered_or_other(value: str, registered: frozenset[str]) -> str:
    """추론 결과도 등록 집합을 통과해야 합니다.

    운영자가 설정에서 값을 빼면 그 분류가 즉시 꺼집니다. 추론 규칙을 코드에서 지우지 않고도
    집계에서 제외할 수 있는 손잡이입니다.
    """
    return value if value in registered else CLIENT_OTHER
