# -- Build stage --
FROM python:3.12-alpine AS builder

WORKDIR /build

COPY requirements.txt .
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --no-compile -r requirements.txt \
    && find /opt/venv -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -type f -name "*.pyc" -delete 2>/dev/null; \
       find /opt/venv -type f -name "*.pyo" -delete 2>/dev/null; \
       find /opt/venv -type d -name "tests" -exec rm -rf {} + 2>/dev/null; \
       find /opt/venv -type d -name "test" -exec rm -rf {} + 2>/dev/null; true

# -- Runtime stage --
FROM python:3.12-alpine

LABEL maintainer="Sergio Fernandez <9169332+GeiserX@users.noreply.github.com>"
LABEL org.opencontainers.image.description="CashPilot - Self-hosted passive income orchestrator"
LABEL org.opencontainers.image.url="https://github.com/GeiserX/CashPilot"
LABEL org.opencontainers.image.source="https://github.com/GeiserX/CashPilot"
LABEL org.opencontainers.image.licenses="GPL-3.0"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/opt/venv/bin:$PATH"

COPY --from=builder /opt/venv /opt/venv

RUN adduser -D -u 1000 cashpilot \
    && mkdir -p /data && chown cashpilot:root /data

WORKDIR /app

COPY --chown=cashpilot:root app/ ./app/
COPY --chown=cashpilot:root services/ ./services/

VOLUME /data
EXPOSE 8080

USER cashpilot

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
