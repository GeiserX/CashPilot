#!/usr/bin/env bash
# Smoke test for the EarnApp image, run under exactly the hardening CashPilot's
# worker applies to every earner (app/orchestrator.py): every capability
# dropped, no-new-privileges, not privileged, 512 pids, 256 MB.
#
#   images/earnapp/smoke.sh <image>
#
# It downloads the real binary and starts EarnApp with a fresh, unlinked
# device id, so it needs the network. Everything it creates is named
# earnapp-smoke-<pid>* and removed on exit.
set -uo pipefail

IMAGE="${1:?usage: $0 <image>}"
P="earnapp-smoke-$$"
HARDEN=(--cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --memory 256m)
FAILURES=0
TMP=$(mktemp -d)

cleanup() {
	docker ps -aq --filter "name=^${P}" | xargs -r docker rm -f >/dev/null
	docker volume ls -q --filter "name=^${P}" | xargs -r docker volume rm >/dev/null
	rm -rf "$TMP"
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
wait_for() {
	local secs=$1
	shift
	for ((i = 0; i < secs; i++)); do
		"$@" >/dev/null 2>&1 && return 0
		sleep 1
	done
	return 1
}
# Capture first: under pipefail, grep -q closing the pipe early can fail
# docker logs with SIGPIPE and turn a present message into a miss.
logs_have() {
	local out
	out=$(docker logs "$1" 2>&1)
	grep -qF -- "$2" <<<"$out"
}
exit_code() { docker inspect -f '{{.State.ExitCode}}' "$1"; }

echo "== $IMAGE"

echo "-- the image carries no Bright Data code"
check "no earnapp binary in the image" \
	docker run --rm --entrypoint sh "$IMAGE" -c '! find / -xdev -name "earnapp*" -type f | grep -q . && [ ! -e /usr/bin/earnapp ]'

echo "-- fails closed"
docker run --name "$P-nouuid" "${HARDEN[@]}" -v "$P-nouuid:/etc/earnapp" "$IMAGE" >/dev/null 2>&1
check "exits 1 without EARNAPP_UUID" test "$(exit_code "$P-nouuid")" = 1
check "says EARNAPP_UUID is not set" logs_have "$P-nouuid" "EARNAPP_UUID is not set"

docker run --rm --entrypoint cat "$IMAGE" /opt/cashpilot-earnapp/SHA256SUMS |
	sed -E 's/^[0-9a-f]{8}/00000000/' >"$TMP/SHA256SUMS"
docker run --name "$P-badsum" "${HARDEN[@]}" -v "$P-badsum:/etc/earnapp" \
	-v "$TMP/SHA256SUMS:/opt/cashpilot-earnapp/SHA256SUMS:ro" "$IMAGE" verify >/dev/null 2>&1
check "exits 1 when the download does not match the pinned sha256" test "$(exit_code "$P-badsum")" = 1
check "says sha256 mismatch" logs_have "$P-badsum" "sha256 mismatch"
check "leaves no unverified binary behind" \
	docker run --rm -v "$P-badsum:/etc/earnapp" --entrypoint sh "$IMAGE" -c '! find /etc/earnapp/bin -type f 2>/dev/null | grep -q .'

echo "-- falls back to the served build when the CDN has dropped the pinned one"
# 0.0.1 is not on the CDN (404), as an old pin will not be once Bright Data moves on.
echo 0.0.1 >"$TMP/VERSION"
for arch in x64 aarch64 arm7l; do echo "$(printf '0%.0s' {1..64})  earnapp-ssl3-$arch-0.0.1"; done >"$TMP/SHA256SUMS.old"
docker run --name "$P-gone" "${HARDEN[@]}" -v "$P-gone:/etc/earnapp" \
	-v "$TMP/VERSION:/opt/cashpilot-earnapp/VERSION:ro" -v "$TMP/SHA256SUMS.old:/opt/cashpilot-earnapp/SHA256SUMS:ro" \
	"$IMAGE" verify >/dev/null 2>&1
check "exits 0 with a pin the CDN no longer serves" test "$(exit_code "$P-gone")" = 0
check "warns that it runs the served build instead" logs_have "$P-gone" "no longer serves the pinned EarnApp 0.0.1"
check "checks the served build against the CDN's .sha256" logs_have "$P-gone" "sha256 matches the CDN's .sha256 file"

echo "-- runs under CashPilot's hardening"
uuid="sdk-node-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n')"
docker run -d --name "$P-run" "${HARDEN[@]}" -e EARNAPP_UUID="$uuid" -v "$P-data:/etc/earnapp" "$IMAGE" >/dev/null
check "downloads the binary and the sha256 matches" wait_for 120 logs_have "$P-run" "sha256 matches the pin"
check "earnapp start ran (status enabled)" \
	wait_for 120 docker exec "$P-run" grep -q enabled /etc/earnapp/status
check "writes the given device id" test "$(docker exec "$P-run" cat /etc/earnapp/uuid)" = "$uuid"
sleep 20
check "earnapp run is still up after 20 s" bash -c "docker exec $P-run sh -c 'cat /proc/[0-9]*/cmdline 2>/dev/null | tr \"\\0\" \" \"' | grep -q 'earnapp run'"
check "container still running" test "$(docker inspect -f '{{.State.Running}}' "$P-run")" = true
check "health check passes while earnapp run is up" docker exec "$P-run" /usr/local/bin/cashpilot-earnapp-health
check "health check fails on status enabled with no earnapp run" \
	docker run --rm --entrypoint bash "$IMAGE" -c 'mkdir -p /etc/earnapp && echo enabled >/etc/earnapp/status && ! cashpilot-earnapp-health'
docker stats --no-stream --format '  info  memory {{.MemUsage}}, pids {{.PIDs}}' "$P-run"

echo "-- restarts earnapp run inside the container, not the container"
# Kill `earnapp run` the way a crash would. procps is not in the image, so
# find it through /proc.
kill_run() {
	docker exec "$1" bash -c 'for d in /proc/[0-9]*; do tr "\0" " " <"$d/cmdline" 2>/dev/null | grep -q "^/usr/bin/earnapp run" && kill -9 "${d#/proc/}"; done' >/dev/null 2>&1
}
# restarts_are <container> <waits...>: the internal restarts logged so far
# waited exactly these many seconds, in order.
restarts_are() {
	local out
	out=$(docker logs "$1" 2>&1 | sed -nE 's/.*Restarting it inside this container in ([0-9]+)s;.*/\1/p' | paste -sd' ' -)
	shift
	[[ "$out" == "$*" ]]
}
kill_run "$P-run"
check "logs an internal restart" wait_for 15 logs_have "$P-run" "the container itself keeps running"
check "earnapp run is back after the backoff" wait_for 60 docker exec "$P-run" /usr/local/bin/cashpilot-earnapp-health

echo "-- a run that lasted over a minute is restarted after 5 s, not a doubled wait"
# EarnApp 1.665.73 exits after about 100 s whenever one of the agents Bright
# Data assigns to the IP is down. A doubling wait left such a node offline for
# 300 s after every 100 s run.
sleep 65
kill_run "$P-run"
check "second restart also waits 5 s" wait_for 15 restarts_are "$P-run" 5 5
check "earnapp run is back" wait_for 60 docker exec "$P-run" /usr/local/bin/cashpilot-earnapp-health
check "container kept running" test "$(docker inspect -f '{{.State.Running}}' "$P-run")" = true
check "container restart count is 0" test "$(docker inspect -f '{{.RestartCount}}' "$P-run")" = 0

echo "-- stops cleanly"
t0=$(date +%s)
docker stop "$P-run" >/dev/null
took=$(($(date +%s) - t0))
check "docker stop takes under 10 s (took ${took}s)" test "$took" -lt 10
check "exits 0 on SIGTERM" test "$(exit_code "$P-run")" = 0

echo "-- a recreated container reuses the checked binary"
docker rm "$P-run" >/dev/null
docker run -d --name "$P-run2" "${HARDEN[@]}" -e EARNAPP_UUID="$uuid" -v "$P-data:/etc/earnapp" "$IMAGE" >/dev/null
check "uses the cached copy" wait_for 30 logs_have "$P-run2" "Using cached"
check "does not download again" bash -c "! docker logs $P-run2 2>&1 | grep -q Downloading"
docker rm -f "$P-run2" >/dev/null

echo "-- a cached binary that lost its execute bit still runs"
docker run --rm -v "$P-data:/etc/earnapp" --entrypoint sh "$IMAGE" -c 'chmod 644 /etc/earnapp/bin/earnapp-*'
docker run --name "$P-noexec" "${HARDEN[@]}" -v "$P-data:/etc/earnapp" "$IMAGE" verify >/dev/null 2>&1
check "verify exits 0 on the cached copy" test "$(exit_code "$P-noexec")" = 0
check "uses the cached copy, no download" bash -c "! docker logs $P-noexec 2>&1 | grep -q Downloading"

if ((FAILURES)); then
	echo "-- logs of $P-noexec"
	docker logs --tail 30 "$P-noexec" 2>&1
	echo "FAILED: $FAILURES check(s)"
	exit 1
fi
echo "All checks passed"
