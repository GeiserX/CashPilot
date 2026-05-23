# -- Build stage --
FROM python:3.14-alpine AS builder

WORKDIR /build

RUN apk add --no-cache gcc musl-dev libffi-dev

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /bin/uv

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project \
    && find .venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
       find .venv -type f -name "*.pyc" -delete 2>/dev/null; \
       find .venv -type f -name "*.pyo" -delete 2>/dev/null; \
       find .venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
       find .venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; true

# -- Runtime stage --
FROM python:3.14-alpine

LABEL maintainer="Sergio Fernandez <9169332+GeiserX@users.noreply.github.com>"
LABEL org.opencontainers.image.description="CashPilot - Self-hosted passive income orchestrator"
LABEL org.opencontainers.image.url="https://github.com/GeiserX/CashPilot"
LABEL org.opencontainers.image.source="https://github.com/GeiserX/CashPilot"
LABEL org.opencontainers.image.licenses="GPL-3.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH"

RUN apk add --no-cache su-exec

RUN adduser -D -u 1000 cashpilot \
    && mkdir -p /data && chown cashpilot:root /data

WORKDIR /app

COPY --from=builder /build/.venv ./.venv

COPY --chown=cashpilot:root app/ ./app/
COPY --chown=cashpilot:root services/ ./services/
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

VOLUME /data
EXPOSE 8080

ENTRYPOINT ["/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
