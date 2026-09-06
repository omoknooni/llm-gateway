"""헬스 체크. API prefix 밖에 둡니다(k8s probe 가 버전 경로를 알 필요가 없습니다)."""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request, Response, status
from sqlalchemy import text

from app.core.db import session_scope

logger = structlog.get_logger()

router = APIRouter(tags=["Health"])


@router.get("/healthz", summary="프로세스 생존 확인")
async def healthz() -> dict[str, str]:
    """의존성을 건드리지 않습니다. DB 가 죽었다고 pod 를 재시작하면 안 됩니다."""
    return {"status": "ok"}


@router.get("/readyz", summary="의존성 연결 확인")
async def readyz(request: Request, response: Response) -> dict[str, object]:
    checks: dict[str, str] = {}

    try:
        async with session_scope() as session:
            await session.execute(text("SELECT 1"))
        checks["postgres"] = "ok"
    except Exception as exc:
        logger.warning("readyz.postgres_failed", error=str(exc))
        checks["postgres"] = "error"

    try:
        await request.app.state.redis.ping()
        checks["redis"] = "ok"
    except Exception as exc:
        logger.warning("readyz.redis_failed", error=str(exc))
        checks["redis"] = "error"

    ready = all(v == "ok" for v in checks.values())
    if not ready:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ready else "degraded", "checks": checks}
