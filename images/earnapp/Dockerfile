# CashPilot's EarnApp image. It holds no Bright Data code: only the entrypoint,
# the pinned EarnApp version and the sha256 of each architecture's build. The
# entrypoint downloads that build from Bright Data's CDN at first start and
# refuses to run it unless the hash matches. See README.md.
#
# debian:trixie-slim, pinned to its multi-arch index (amd64, arm64, arm/v7).
FROM debian:trixie-slim@sha256:89c1ea91e897f0fe0a3731595330bc45b8bdef4047464a07116f891a94054b31

RUN apt-get update \
	&& apt-get install -y --no-install-recommends ca-certificates curl \
	&& rm -rf /var/lib/apt/lists/*

COPY VERSION SHA256SUMS /opt/cashpilot-earnapp/
COPY --chmod=755 entrypoint.sh /usr/local/bin/cashpilot-earnapp
COPY --chmod=755 health.sh /usr/local/bin/cashpilot-earnapp-health

# The binary lives in the volume, next to the device state, so a recreated
# container reuses the copy it already checked.
RUN ln -s /etc/earnapp/bin/earnapp /usr/bin/earnapp

VOLUME ["/etc/earnapp"]

# Healthy = `earnapp start` ran and `earnapp run` is alive. It does not prove
# the device registered; see health.sh.
HEALTHCHECK --interval=1m --timeout=10s --start-period=2m --retries=3 \
	CMD ["/usr/local/bin/cashpilot-earnapp-health"]

ENTRYPOINT ["/usr/local/bin/cashpilot-earnapp"]

LABEL org.opencontainers.image.title="cashpilot-earnapp" \
	org.opencontainers.image.description="Unofficial EarnApp lite container for CashPilot. Downloads the pinned EarnApp build from Bright Data at first start and checks its sha256." \
	org.opencontainers.image.source="https://github.com/GeiserX/CashPilot" \
	org.opencontainers.image.licenses="GPL-3.0-or-later"
