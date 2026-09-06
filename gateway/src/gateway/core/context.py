"""요청 단위 컨텍스트.

미들웨어와 라우터는 `scope["state"]` 딕셔너리로 값을 주고받습니다. 키 이름을 문자열로 흩뿌리면
한 곳만 바뀌었을 때 조용히 어긋나므로 여기 상수로 모읍니다.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from datetime import datetime

from gateway.config import CLIENT_OTHER

#: scope["state"] 키.
STATE_REQUEST = "request_ctx"
STATE_AUTH = "auth_context"
STATE_CLIENT = "client"


@dataclass
class RequestContext:
    request_id: str
    #: time.monotonic() 기준. 벽시계는 NTP 보정으로 뒤로 갈 수 있어 지연 측정에 쓰지 않습니다.
    started_at: float = field(default_factory=time.monotonic)
    client: str = CLIENT_OTHER

    @property
    def elapsed_ms(self) -> int:
        return int((time.monotonic() - self.started_at) * 1000)


@dataclass(frozen=True)
class AuthContext:
    """VK 인증의 산출물이자 `vk:auth:{key_hash}` 에 그대로 직렬화되는 스냅샷.

    형태는 공유 계약 C2 의 payload 를 따릅니다. `idp_subject` 는 넣지 않습니다 — provider 로
    보낼 식별자를 `user_id` 로 바꾼 결과이며, 그 덕에 이 캐시에는 개인식별정보가 없습니다
    (docs/06 Q4).
    """

    virtual_key_id: str
    owner_type: str
    owner_id: str
    #: VK 의 비정규화 컬럼이라 USER 소유 키에도 항상 존재합니다.
    team_id: str
    #: owner_type=USER 일 때만. TEAM 소유 VK 호출은 사람에 귀속되지 않습니다.
    user_id: str | None
    status: str
    expires_at: datetime | None
    #: 3층 해석이 끝난 **최종 목록**. "전체 허용"(None)을 쓰지 않습니다 — 캐시에 넣으면
    #: 카탈로그가 바뀔 때마다 의미가 달라지는데 그 순간을 캐시가 알 수 없습니다.
    #: 빈 목록은 "이 키로 쓸 수 있는 모델 없음"이라는 유효한 상태입니다.
    allowed_model_aliases: tuple[str, ...]

    @property
    def end_user_id(self) -> str:
        """provider 의 `metadata.user_id` 로 나가는 불투명 식별자.

        VK id 가 아니라 사용자 id 를 우선하는 이유는 로테이션 내성입니다. VK 는 주기적으로
        교체되지만 사람은 그대로라, VK id 를 쓰면 로테이션마다 provider 측 추적이 끊깁니다.
        """
        return self.user_id or self.virtual_key_id

    def to_json(self) -> str:
        return json.dumps(
            {
                "virtual_key_id": self.virtual_key_id,
                "owner_type": self.owner_type,
                "owner_id": self.owner_id,
                "team_id": self.team_id,
                "user_id": self.user_id,
                "status": self.status,
                "expires_at": self.expires_at.isoformat() if self.expires_at else None,
                "allowed_model_aliases": list(self.allowed_model_aliases),
            },
            separators=(",", ":"),
        )

    @classmethod
    def from_json(cls, raw: str) -> AuthContext:
        """파싱 실패는 호출부가 **캐시 miss 로 취급**합니다.

        필드를 추가했을 때 구버전 항목 하나가 영구 500 이 되는 것을 막는 방어입니다.
        """
        data = json.loads(raw)
        expires_at = data.get("expires_at")
        return cls(
            virtual_key_id=data["virtual_key_id"],
            owner_type=data["owner_type"],
            owner_id=data["owner_id"],
            team_id=data["team_id"],
            user_id=data.get("user_id"),
            status=data["status"],
            expires_at=datetime.fromisoformat(expires_at) if expires_at else None,
            allowed_model_aliases=tuple(data["allowed_model_aliases"]),
        )
