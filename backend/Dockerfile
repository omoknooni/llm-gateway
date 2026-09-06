# ---- builder ----
FROM python:3.11-slim AS builder

WORKDIR /build
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

COPY pyproject.toml uv.lock* ./
RUN uv pip install --system --no-cache -r pyproject.toml \
    && find /usr/local/lib/python3.11/site-packages -type d -name '__pycache__' -exec rm -rf {} + \
    && find /usr/local/lib/python3.11/site-packages -type f -name '*.pyc' -delete

COPY src/ src/

# ---- runtime ----
FROM python:3.11-slim AS runtime

RUN groupadd -r appuser && useradd -r -g appuser -d /app -s /sbin/nologin appuser
WORKDIR /app

COPY --from=builder /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=builder /usr/local/bin /usr/local/bin
COPY --from=builder /build/src /app/src

RUN chown -R appuser:appuser /app
USER appuser

ENV PYTHONPATH=/app/src \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
