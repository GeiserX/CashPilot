# CashPilot's Anyone Protocol relay image: the vendor's own `anon` package,
# installed from their signed apt repository, run as the unprivileged `anond`
# user so it starts under CashPilot's hardening with no capabilities at all.
# See README.md.
#
# debian:bookworm-slim, pinned to its multi-arch index (amd64, arm64). The
# vendor publishes bookworm packages for amd64 and arm64 only.
FROM debian:bookworm-slim@sha256:99c0b25c46d0214d5a2091092e7908907dcaecd6a962cde0ac700acee222b6f3

# anond is uid 100, gid 101: the ids the vendor image's `adduser --system`
# gives it, so a volume that image wrote (identity keys included) stays
# readable here without a chown. Created before the package, which adds its
# own unused debian-anon account on the next free ids.
RUN groupadd --system --gid 101 anond \
	&& useradd --system --uid 100 --gid 101 --home-dir /var/lib/anon --no-create-home --shell /usr/sbin/nologin anond

# The vendor's signing key, committed beside this file. test.sh refuses to
# build unless its fingerprint is DC73B31AA1F797B180A87CBC7571AA42A0CBEFE9, the
# one the vendor's README publishes. apt checks the Release signature, the
# Packages hash and the .deb hash against it.
COPY anon.asc /etc/apt/keyrings/anon.asc
COPY VERSION /opt/cashpilot-anyone/VERSION

# The package refuses to install unless debconf says the terms were accepted.
# This answers the installer's question the way the vendor's own Dockerfiles
# do (anyone-protocol/onionperf). It does not accept the terms for whoever
# runs the relay: anon itself still refuses to start without AgreeToTerms 1 in
# their anonrc.
RUN export DEBIAN_FRONTEND=noninteractive \
	&& apt-get update \
	&& apt-get install -y --no-install-recommends ca-certificates \
	&& echo "anon anon/terms boolean true" | debconf-set-selections \
	&& echo "deb [signed-by=/etc/apt/keyrings/anon.asc] https://deb.en.anyone.tech anon-live-bookworm main" >/etc/apt/sources.list.d/anon.list \
	&& apt-get update \
	&& apt-get install -y --no-install-recommends "anon=$(cat /opt/cashpilot-anyone/VERSION)" \
	&& rm -rf /var/lib/apt/lists/* \
	# The package's default anonrc is a client config. Leave /etc/anon empty,
	# so a missing anonrc fails with a clear message instead of starting it.
	&& rm -rf /etc/anon/* \
	# Owned by anond, so a fresh named volume mounted here starts writable by
	# it: Docker copies the directory's owner and mode into an empty volume.
	&& mkdir -p /var/lib/anon /etc/anon /run/anon \
	&& chown anond:anond /var/lib/anon /etc/anon /run/anon \
	&& chmod 2700 /var/lib/anon

COPY --chmod=755 entrypoint.sh /usr/local/bin/cashpilot-anyone
COPY --chmod=755 health.sh /usr/local/bin/cashpilot-anyone-health

USER anond:anond

VOLUME ["/var/lib/anon", "/etc/anon", "/run/anon"]

# ORPort. Above 1024, so binding it needs no capability.
EXPOSE 9001

# Healthy = the anon process is alive and listening on the anonrc's ORPort.
# It does not prove the port is reachable from outside; see health.sh.
HEALTHCHECK --interval=1m --timeout=10s --start-period=1m --retries=3 \
	CMD ["/usr/local/bin/cashpilot-anyone-health"]

ENTRYPOINT ["/usr/local/bin/cashpilot-anyone"]
CMD ["anon", "-f", "/etc/anon/anonrc"]

LABEL org.opencontainers.image.title="cashpilot-anyone" \
	org.opencontainers.image.description="Unofficial Anyone Protocol relay for CashPilot. The vendor's signed anon package, run as an unprivileged user with no capabilities." \
	org.opencontainers.image.source="https://github.com/GeiserX/CashPilot" \
	org.opencontainers.image.licenses="GPL-3.0-or-later"
