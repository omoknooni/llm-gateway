"""구조적 로깅.

요청 단위 컨텍스트(request_id, client, virtual_key_id)는 contextvars 로 묶어 모든 로그 줄에
자동으로 붙입니다. **키 원문은 어떤 경로로도 로그에 들어가지 않습니다**(docs/02).
"""

from __future__ import annotations

import logging

import structlog

from gateway.config import Settings


def configure_logging(settings: Settings) -> None:
    renderer = (
        structlog.processors.JSONRenderer()
        if settings.log_format == "json"
        else structlog.dev.ConsoleRenderer()
    )
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            renderer,
        ],
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelName(settings.log_level.upper())
        ),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )
