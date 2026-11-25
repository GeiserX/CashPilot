#!/usr/bin/env bash
# Build the image for one platform on a host of that architecture and test it
# without mining: nothing here connects to a pool or hashes, and every
# container runs with --network none.
#
#   images/xmrig/test.sh [linux/amd64|linux/arm64]   (default: the host's)
#   XMRIG_TEST_LIVE=1 images/xmrig/test.sh           also start a miner daemon
#
# CI runs it once on an amd64 runner and once on an arm64 runner, so both
# builds are compiled and tested natively, with no emulation. CI stops at
# --version, --help, --dry-run and the health script against a stand-in API:
# GitHub's terms forbid mining on Actions, so no miner process runs there.
# XMRIG_TEST_LIVE=1 (local hosts only, never CI) adds a miner daemon with no
# network, which waits for a job that never comes: its API answers, it shows
# unhealthy, and it stops fast and cleanly.
set -uo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
VERSION=$(tr -d '[:space:]' <"$DIR/VERSION")
case "${1:-}" in
"") case "$(uname -m)" in x86_64 | amd64) PLATFORM=linux/amd64 ;; aarch64 | arm64) PLATFORM=linux/arm64 ;; *) PLATFORM=unknown ;; esac ;;
*) PLATFORM=$1 ;;
esac
case "$PLATFORM" in
linux/amd64) ARCH="x86-64" ;;
linux/arm64) ARCH="ARMv8" ;;
*)
	echo "unsupported platform $PLATFORM; this image ships linux/amd64 and linux/arm64" >&2
	exit 2
	;;
esac
if [[ "${XMRIG_TEST_LIVE:-}" == 1 && -n "${CI:-}" ]]; then
	echo "XMRIG_TEST_LIVE=1 starts a miner process; never set it in CI" >&2
	exit 2
fi
P="cashpilot-xmrig-test-$$"
IMG="$P:image"
# The hardening CashPilot's worker gives every container (app/orchestrator.py),
# plus no network at all.
HARDEN=(--init --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --memory 256m --network none)
# A real wallet (the Monero General Fund's donation address) so the config
# parses; with no network the miner never reaches a pool.
WALLET=44AFFq5kSiGBoZ4NMDwYtN18obc8AemS33DBLWs3H7otXft3XjrpDtQGv7SqSsaBYBb98uNbr2VBBEt7f2wfn3RVGQBEP3A
MINE=(-o pool.supportxmr.com:443 --tls -u "$WALLET" -p cashpilot-test -t 1 --no-color)
FAILURES=0

cleanup() {
	docker ps -aq --filter "name=^${P}" | xargs -r docker rm -f >/dev/null
	docker image rm -f "$IMG" >/dev/null 2>&1 || true
}
trap cleanup EXIT

pass() { echo "  ok    $1"; }
fail() {
	echo "  FAIL  $1"
	FAILURES=$((FAILURES + 1))
}
check() {
	local name=$1
	shift
	if "$@" >/dev/null 2>&1; then pass "$name"; else fail "$name"; fi
}
has() { grep -qF -- "$2" <<<"$1"; }
lacks() { ! grep -qE -- "$2" <<<"$1"; }
not() { ! "$@"; }
indent() { sed 's/^/        /'; }
wait_for() {
	local secs=$1
	shift
	for ((i = 0; i < secs; i++)); do
		"$@" >/dev/null 2>&1 && return 0
		sleep 1
	done
	return 1
}

echo "== build $PLATFORM (XMRig $VERSION)"
if ! docker build --quiet --platform "$PLATFORM" -t "$IMG" "$DIR" >/dev/null; then
	echo "FAILED: the image did not build" >&2
	exit 1
fi

echo "-- the binary"
# stdout only: the docker CLI can print a warning of its own on stderr.
version=$(docker run --rm "${HARDEN[@]}" "$IMG" --version)
indent <<<"$version"
check "--version reports XMRig $VERSION" test "$(head -n1 <<<"$version")" = "XMRig $VERSION"
help=$(docker run --rm "${HARDEN[@]}" "$IMG" --help 2>&1)
check "built without the CUDA and OpenCL loaders" lacks "$help" "--(cuda|opencl)"
check "runs as uid 10001, not root" test "$(docker run --rm "${HARDEN[@]}" --entrypoint id "$IMG" -u)" = 10001

echo "-- --dry-run under CashPilot's hardening"
dry=$(docker run --rm "${HARDEN[@]}" "$IMG" --dry-run "${MINE[@]}" --donate-level=0 --randomx-wrmsr=-1 2>&1)
rc=$?
indent <<<"$dry"
check "--dry-run exits 0" test "$rc" = 0
check "--dry-run says config OK" has "$dry" "config   OK"
check "built for $ARCH" has "$dry" "built for Linux $ARCH"
# Upstream's floor is 1%: asking for 0 still donates 1%, so the fee is unmodified.
check "dev fee is upstream's 1% floor, even when asked for 0" has "$dry" "DONATE       1%"

echo "-- health check"
check "image health check runs cashpilot-xmrig-health" \
	has "$(docker inspect -f '{{json .Config.Healthcheck.Test}}' "$IMG")" /usr/local/bin/cashpilot-xmrig-health
check "unhealthy when the HTTP API is off" \
	not docker run --rm "${HARDEN[@]}" --entrypoint /usr/local/bin/cashpilot-xmrig-health "$IMG"
# The health script against a stand-in wget that prints a /2/summary answer.
# The script is single-quoted on purpose: it expands inside the container.
fake_api() {
	# shellcheck disable=SC2016
	docker run --rm "${HARDEN[@]}" -e SUMMARY="$1" --entrypoint sh "$IMG" -c '
		mkdir -p /tmp/bin
		cat >/tmp/bin/wget <<"FAKE"
#!/bin/sh
printf "%s\n" "$SUMMARY"
FAKE
		chmod +x /tmp/bin/wget
		PATH=/tmp/bin:$PATH /usr/local/bin/cashpilot-xmrig-health'
}
# A miner with no pool, as /2/summary printed it on a real run: the miner's own
# uptime is past zero, so a check that read it instead of the connection's
# uptime would pass here and show up as a failure.
NOPOOL='{
    "uptime": 119,
    "connection": {
        "pool": "",
        "ip": null,
        "uptime": 0,
        "uptime_ms": 0,
        "accepted": 0,
        "rejected": 0
    }
}'
# A connected miner, as /2/summary printed it on a real run.
CONNECTED='{
    "uptime": 119,
    "connection": {
        "pool": "pool.supportxmr.com:3333",
        "ip": "141.94.96.71",
        "uptime": 119,
        "uptime_ms": 119462,
        "accepted": 1,
        "rejected": 0
    }
}'
check "unhealthy while no pool is connected" not fake_api "$NOPOOL"
check "healthy once a pool connection is up" fake_api "$CONNECTED"

if [[ "${XMRIG_TEST_LIVE:-}" == 1 ]]; then
	echo "-- a live miner with no network (XMRIG_TEST_LIVE=1)"
	# XMRig waits for a job that never comes and never hashes.
	docker run -d --name "$P-nopool" "${HARDEN[@]}" "$IMG" "${MINE[@]}" --http-port=18088 >/dev/null
	check "the HTTP API answers without a pool" \
		wait_for 30 docker exec "$P-nopool" wget -qO- -T 2 http://127.0.0.1:18088/2/summary
	# Let the miner's own uptime pass zero, so a check that read it instead of
	# the connection's uptime would pass here and show up as a failure.
	sleep 3
	check "unhealthy while no pool is connected (live)" not docker exec "$P-nopool" /usr/local/bin/cashpilot-xmrig-health
	t0=$(date +%s)
	docker stop "$P-nopool" >/dev/null
	took=$(($(date +%s) - t0))
	check "docker stop takes under 10 s (took ${took}s)" test "$took" -lt 10
	check "exits 0 on SIGTERM" test "$(docker inspect -f '{{.State.ExitCode}}' "$P-nopool")" = 0
fi

if ((FAILURES)); then
	echo "FAILED: $FAILURES check(s) on $PLATFORM"
	exit 1
fi
echo "All checks passed on $PLATFORM"
