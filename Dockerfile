# -- Build stage --
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --no-compile --prefix=/install -r requirements.txt \
    && find /install -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true \
    && find /install -type f -name '*.pyc' -delete 2>/dev/null || true \
    && find /install -type d -name tests -exec rm -rf {} + 2>/dev/null || true

# -- Runtime stage --
FROM python:3.12-slim

LABEL maintainer="Sergio Fernandez <9169332+GeiserX@users.noreply.github.com>"
LABEL org.opencontainers.image.description="CashPilot - Self-hosted passive income orchestrator"
LABEL org.opencontainers.image.url="https://github.com/GeiserX/CashPilot"
LABEL org.opencontainers.image.source="https://github.com/GeiserX/CashPilot"
LABEL org.opencontainers.image.licenses="GPL-3.0"

# Prevent Python from writing .pyc files and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Install tini (PID 1 init) and clean up in same layer
RUN apt-get update \
    && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user with docker group access
RUN groupadd -g 999 docker \
    && useradd -r -u 1000 -g docker -m cashpilot

WORKDIR /app

COPY app/ ./app/
COPY services/ ./services/

RUN mkdir -p /data && chown cashpilot:docker /data

VOLUME /data
EXPOSE 8080

USER cashpilot

ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--no-access-log"]
