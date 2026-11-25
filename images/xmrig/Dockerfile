# CashPilot's XMRig image: upstream XMRig, built from source at the release
# commit pinned in COMMIT, unmodified (its 1% dev fee stays). See README.md.
#
# alpine:3.24, pinned to its multi-arch index (amd64, arm64).
FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf AS build

RUN apk add --no-cache build-base cmake git hwloc-dev libuv-dev linux-headers openssl-dev

COPY VERSION COMMIT /pin/
WORKDIR /src

# Fetch the release tag and refuse to build unless it still points at the
# pinned commit: a moved tag or a VERSION/COMMIT mismatch stops the build.
RUN set -eu; \
	version=$(tr -d '[:space:]' </pin/VERSION); \
	commit=$(tr -d '[:space:]' </pin/COMMIT); \
	git init -q .; \
	git fetch -q --depth 1 https://github.com/xmrig/xmrig "refs/tags/v$version:refs/tags/v$version"; \
	got=$(git rev-parse "refs/tags/v$version^{commit}"); \
	if [ "$got" != "$commit" ]; then \
		echo "upstream tag v$version is commit $got, not the pinned $commit; refusing to build" >&2; \
		exit 1; \
	fi; \
	git -c advice.detachedHead=false checkout -q "$commit"

# CPU only: no CUDA or OpenCL plugin loaders.
RUN cmake -S . -B build -DCMAKE_BUILD_TYPE=Release -DWITH_CUDA=OFF -DWITH_OPENCL=OFF \
	&& cmake --build build -j"$(nproc)" \
	&& strip build/xmrig

FROM alpine:3.24@sha256:f59abe656b692d901e184be3445e084786602108599d2a51d229c0f5a48c71bf

RUN apk add --no-cache hwloc libcrypto3 libgcc libssl3 libstdc++ libuv

COPY --from=build /src/build/xmrig /usr/local/bin/xmrig
COPY health.sh /usr/local/bin/cashpilot-xmrig-health

# No root: huge pages work unprivileged once the host reserves them, and the
# MSR mod (which needs root and /dev/cpu/*/msr) is never used.
USER 10001:10001
WORKDIR /tmp

# Healthy = the miner's local HTTP API answers and reports a live pool
# connection. Needs --http-port=18088 on the command; see README.md.
HEALTHCHECK --interval=1m --timeout=10s --start-period=2m --retries=3 \
	CMD ["/usr/local/bin/cashpilot-xmrig-health"]

ENTRYPOINT ["/usr/local/bin/xmrig"]

LABEL org.opencontainers.image.title="cashpilot-xmrig" \
	org.opencontainers.image.description="Unofficial XMRig container for CashPilot. Upstream XMRig built from source at its signed release commit, unmodified." \
	org.opencontainers.image.source="https://github.com/GeiserX/CashPilot" \
	org.opencontainers.image.licenses="GPL-3.0-or-later"
