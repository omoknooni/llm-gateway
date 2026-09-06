# 마이그레이션 전용 이미지. 앱 이미지와 분리합니다(권한이 다릅니다).
FROM python:3.11-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /migrate

COPY pyproject.toml uv.lock* ./
RUN uv pip install --system --no-cache -r pyproject.toml

COPY src/ src/
COPY db/ db/

ENV PYTHONPATH=/migrate/src
ENTRYPOINT ["/migrate/db/run_migration.sh"]
