"""헬스 프로브.

경로 이름은 backend 와 맞춥니다(`/healthz`, `/readyz`). 두 서비스의 프로브 설정이 같은 모양이면
Helm 차트에서 실수할 여지가 줄어듭니다.

- `/healthz` — liveness. **의존성을 확인하지 않습니다.** Redis 가 죽었다고 pod 를 재시작해도
  나아지지 않습니다. 재시작으로 고쳐지는 상태만 여기서 실패해야 합니다.
- `/readyz`  — readiness. Redis·DB 를 확인합니다. 둘 다 죽으면 인증조차 할 수 없으므로
  트래픽을 받지 않는 편이 낫습니다(docs/README 실패 정책).
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from sqlalchemy import text

logger = structlog.get_logger(__name__)
router = APIRouter()


@router.get("/healthz")
async def liveness(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok", "version": request.app.state.settings.app_version})


@router.get("/readyz")
async def readiness(request: Request) -> JSONResponse:
    redis_ok = await _check_redis(request.app.state.redis)
    db_ok = await _check_db(request.app.state.engine)

    # 하나만 죽은 상태는 degraded 지만 서비스는 됩니다(캐시 없이 DB, 또는 캐시 hit 만).
    # 트래픽을 끊는 것은 둘 다 죽었을 때뿐입니다.
    ready = redis_ok or db_ok
    body = {
        "status": "ok" if (redis_ok and db_ok) else ("degraded" if ready else "unavailable"),
        "redis": "ok" if redis_ok else "down",
        "database": "ok" if db_ok else "down",
    }
    return JSONResponse(body, status_code=200 if ready else 503)


async def _check_redis(redis) -> bool:
    try:
        await redis.ping()
        return True
    except Exception as exc:
        # 의존성이 죽어 있는 동안 프로브가 주기적으로 도는 자리입니다. 스택 트레이스를 남기면
        # 같은 트레이스로 로그가 가득 차 정작 필요한 줄이 묻힙니다. 원인 한 줄이면 충분합니다.
        logger.warning("readiness.redis_down", error=str(exc))
        return False


async def _check_db(engine) -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:
        logger.warning("readiness.database_down", error=str(exc))
        return False
