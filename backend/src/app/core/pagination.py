"""cursor 기반 페이지네이션.

offset 은 쓰지 않습니다. 목록이 길어질수록 느려지고, 페이지를 넘기는 동안 앞쪽 행이
추가·삭제되면 항목이 건너뛰어지거나 중복됩니다.

cursor 는 정렬 키 `(created_at, id)` 를 인코딩한 불투명 문자열입니다. 값의 형식은 계약이
아니므로 client 는 해석하지 않고 그대로 되돌려줍니다.
"""

from __future__ import annotations

import base64
import binascii
import json
import uuid
from datetime import datetime
from typing import Any

from app.core.exceptions import ValidationError


def encode_cursor(created_at: datetime, item_id: uuid.UUID) -> str:
    raw = json.dumps({"t": created_at.isoformat(), "id": str(item_id)}).encode()
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, uuid.UUID]:
    padded = cursor + "=" * (-len(cursor) % 4)
    try:
        payload: dict[str, Any] = json.loads(base64.urlsafe_b64decode(padded))
        return datetime.fromisoformat(payload["t"]), uuid.UUID(payload["id"])
    except (ValueError, KeyError, binascii.Error) as exc:
        raise ValidationError("cursor 값이 올바르지 않습니다") from exc
