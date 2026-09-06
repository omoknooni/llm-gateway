"""요청 단위 컨텍스트.

미들웨어와 라우터는 `scope["state"]` 딕셔너리로 값을 주고받습니다. 키 이름을 문자열로 흩뿌리면
한 곳만 바뀌었을 때 조용히 어긋나므로 여기 상수로 모읍니다.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field

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
