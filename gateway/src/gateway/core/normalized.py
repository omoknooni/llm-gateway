"""방언과 provider 사이의 내부 표현.

    DialectParser → NormalizedRequest → ProviderAdapter
    ProviderAdapter → StreamEvent / ProviderResponse → DialectSerializer

방언 수 × provider 수가 곱해지지 않게 하는 경계입니다. 방언을 하나 더 붙일 때 건드리는 곳은
`dialects/` 뿐이고, provider 를 하나 더 붙일 때 건드리는 곳은 `providers/` 뿐이어야 합니다.

**표현의 모양은 Anthropic 계열(블록 + 블록 인덱스 이벤트)을 따릅니다.** 임의의 선택이 아니라
표현력 때문입니다 — 블록 단위 이벤트에서 OpenAI 의 delta chunk 를 만들 수 있지만 그 반대는
손실 없이 되지 않습니다. Bedrock 의 Anthropic native wire 와도 거의 1:1 이라 변환 손실이
가장 적습니다.

**방언 고유 필드를 실어 나르는 통로(extras/raw)를 두지 않습니다.** 흡수하지 못하는 필드는
통과시키는 대신 거절합니다. 통로를 하나 열면 방언이 adapter 까지 새어 들어가고, 그때부터
둘 중 하나는 사실 일급이 아닌 구조가 됩니다(ADR-0003).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# ── 콘텐츠 블록 ──


@dataclass(frozen=True)
class TextBlock:
    text: str
    #: Anthropic 의 cache_control. OpenAI 방언은 대응 개념이 없어 항상 False 입니다.
    cache_hint: bool = False

    def to_wire(self) -> dict[str, Any]:
        block: dict[str, Any] = {"type": "text", "text": self.text}
        if self.cache_hint:
            block["cache_control"] = {"type": "ephemeral"}
        return block


@dataclass(frozen=True)
class ImageBlock:
    media_type: str
    data: str  # base64

    def to_wire(self) -> dict[str, Any]:
        return {
            "type": "image",
            "source": {"type": "base64", "media_type": self.media_type, "data": self.data},
        }


@dataclass(frozen=True)
class ToolUseBlock:
    id: str
    name: str
    input: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        return {"type": "tool_use", "id": self.id, "name": self.name, "input": self.input}


@dataclass(frozen=True)
class ToolResultBlock:
    tool_use_id: str
    content: Any
    is_error: bool = False

    def to_wire(self) -> dict[str, Any]:
        block: dict[str, Any] = {
            "type": "tool_result",
            "tool_use_id": self.tool_use_id,
            "content": self.content,
        }
        if self.is_error:
            block["is_error"] = True
        return block


@dataclass(frozen=True)
class ThinkingBlock:
    thinking: str
    #: 모델이 준 서명. 다음 턴에 그대로 돌려보내지 않으면 provider 가 거절합니다.
    signature: str | None = None

    def to_wire(self) -> dict[str, Any]:
        block: dict[str, Any] = {"type": "thinking", "thinking": self.thinking}
        if self.signature:
            block["signature"] = self.signature
        return block


ContentBlock = TextBlock | ImageBlock | ToolUseBlock | ToolResultBlock | ThinkingBlock


@dataclass(frozen=True)
class Message:
    role: Literal["user", "assistant"]
    content: list[ContentBlock]

    def to_wire(self) -> dict[str, Any]:
        return {"role": self.role, "content": [b.to_wire() for b in self.content]}


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str | None
    input_schema: dict[str, Any]

    def to_wire(self) -> dict[str, Any]:
        tool: dict[str, Any] = {"name": self.name, "input_schema": self.input_schema}
        if self.description:
            tool["description"] = self.description
        return tool


@dataclass(frozen=True)
class ReasoningSpec:
    """확장 사고. 방언마다 표현이 달라 둘을 모두 담습니다.

    Anthropic 은 토큰 예산(`thinking.budget_tokens`)으로, OpenAI 는 단계(`reasoning_effort`)로
    말합니다. adapter 가 자기 provider 가 이해하는 쪽을 씁니다.
    """

    budget_tokens: int | None = None
    effort: str | None = None


@dataclass(frozen=True)
class NormalizedRequest:
    model_alias: str
    messages: list[Message]
    max_tokens: int
    stream: bool
    system: list[ContentBlock] | None = None
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    stop_sequences: list[str] = field(default_factory=list)
    tools: list[ToolSpec] = field(default_factory=list)
    tool_choice: dict[str, Any] | None = None
    reasoning: ReasoningSpec | None = None
    #: client 가 보낸 end-user 식별자. **관측용이며 provider 로 전달하지 않습니다** —
    #: client 가 채우는 값이라 신뢰할 수 없고, 같은 사람이 도구마다 다른 값을 보내면
    #: provider 측 귀속이 흩어집니다. provider 에 실리는 값은 gateway 가 정합니다(docs/05).
    end_user_id: str | None = None


# ── 응답 ──


@dataclass
class TokenUsage:
    """필드 이름을 `usage.usage_events` 컬럼과 맞췄습니다.

    중간에 이름이 한 번 바뀌면 그 지점에서 매핑 실수가 생깁니다.
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_write_tokens: int = 0
    cache_read_tokens: int = 0
    #: provider 가 usage 를 주지 않아 역산한 경우 True. 청구 정확도 분석의 근거입니다.
    estimated: bool = False

    def merge(self, other: TokenUsage) -> None:
        """스트림은 usage 가 여러 이벤트에 나뉘어 옵니다(입력은 시작, 출력은 끝).

        0 인 값으로 기존 값을 덮지 않습니다.
        """
        self.input_tokens = other.input_tokens or self.input_tokens
        self.output_tokens = other.output_tokens or self.output_tokens
        self.cache_write_tokens = other.cache_write_tokens or self.cache_write_tokens
        self.cache_read_tokens = other.cache_read_tokens or self.cache_read_tokens
        self.estimated = self.estimated or other.estimated


@dataclass
class ProviderResponse:
    response_id: str
    model_id: str
    content: list[ContentBlock]
    stop_reason: str | None
    usage: TokenUsage
    #: 장애 시 AWS 에 문의할 때 쓰는 값. client 응답에는 넣지 않습니다.
    upstream_request_id: str | None = None


# ── 스트림 이벤트 ──


@dataclass(frozen=True)
class StreamStart:
    response_id: str
    model_id: str
    usage: TokenUsage


@dataclass(frozen=True)
class ContentBlockStart:
    index: int
    block_type: str
    tool_id: str | None = None
    tool_name: str | None = None


@dataclass(frozen=True)
class ContentDelta:
    index: int
    text: str | None = None
    partial_json: str | None = None
    thinking: str | None = None
    signature: str | None = None


@dataclass(frozen=True)
class ContentBlockStop:
    index: int


@dataclass(frozen=True)
class MessageDelta:
    stop_reason: str | None
    usage: TokenUsage


@dataclass(frozen=True)
class StreamEnd:
    usage: TokenUsage


@dataclass(frozen=True)
class StreamError:
    """스트림 도중 실패.

    이미 200 헤더가 나간 뒤라 HTTP 상태로 표현할 수 없습니다. 반드시 스트림 안의 프레임으로
    전달해야 client 가 잘린 응답과 구분할 수 있습니다(docs/01).
    """

    code: str
    message: str


StreamEvent = (
    StreamStart
    | ContentBlockStart
    | ContentDelta
    | ContentBlockStop
    | MessageDelta
    | StreamEnd
    | StreamError
)
