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

# The release tag this image was built from, so the app can report what it is.
# Both apps used to hardcode "0.1.0" while releases were tag-driven and past
# 1.11, which made UI/worker skew undetectable (CashPilot-l6c). Defaults to dev
# so a local `docker build` says so rather than claiming a release.
ARG CASHPILOT_VERSION=dev
ENV CASHPILOT_VERSION=$CASHPILOT_VERSION

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
# Ask the app whether it can still DO ITS JOB, not merely whether the port
# answers: a TCP connect is completed by the kernel's listen backlog while
# uvicorn is wedged, the scheduler is dead or the database is unreadable —
# every internal failure rendered as "healthy". /api/health answers 503 for
# those. http.client, NOT urllib.request: urlopen honors http_proxy (which
# Docker injects fleet-wide when the host has a proxies config) with no
# localhost exemption, so the "loopback" probe would be answered by the proxy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD ["python", "-c", "import sys,http.client\ntry:\n    c = http.client.HTTPConnection('127.0.0.1', 8080, timeout=3)\n    c.request('GET', '/api/health')\n    sys.exit(0 if c.getresponse().status == 200 else 1)\nexcept Exception:\n    sys.exit(1)"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
