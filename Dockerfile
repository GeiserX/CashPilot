# -- Build stage --
FROM python:3.12-slim AS builder

WORKDIR /build

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# -- Runtime stage --
FROM python:3.12-slim

LABEL maintainer="Sergio Fernandez <9169332+GeiserX@users.noreply.github.com>"
LABEL org.opencontainers.image.description="CashPilot - Self-hosted passive income orchestrator"
LABEL org.opencontainers.image.url="https://github.com/GeiserX/cashpilot"

# Install minimal runtime deps (tini for PID 1)
RUN apt-get update && apt-get install -y --no-install-recommends tini \
    && rm -rf /var/lib/apt/lists/*

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Create non-root user with docker group access (GID 998/999 varies; socket
# ownership is handled at runtime via the mounted socket's group).
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
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
