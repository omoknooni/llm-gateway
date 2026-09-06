FROM python:3.11-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.6.12 /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* ./
RUN uv pip install --system --no-cache .

COPY src ./src
ENV PYTHONPATH=/app/src

# 비루트로 실행합니다. Bedrock 권한은 IRSA 로 주어지므로 이미지에 자격 증명이 없습니다.
RUN useradd --uid 10001 --no-create-home --shell /usr/sbin/nologin gateway
USER 10001

EXPOSE 8000
CMD ["uvicorn", "gateway.main:app", "--host", "0.0.0.0", "--port", "8000"]
