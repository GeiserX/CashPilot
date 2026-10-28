#!/usr/bin/env bash
# Smoke test for the Anyone Protocol image, run under exactly the hardening
# CashPilot's worker applies to every earner (app/orchestrator.py): every
# capability dropped and none added, no-new-privileges, not privileged, 512
# pids, and the catalog's 1536 MB.
#
#   images/anyone-protocol/smoke.sh <image>
#
# Every relay it starts has a fresh throwaway identity and
# PublishServerDescriptor 0, so it never announces itself to the network. It
# needs the network to bootstrap. Everything it creates is named
# anyone-smoke-<pid>* and removed on exit.
set -uo pipefail

IMAGE="${1:?usage: $0 <image>}"
# The image CashPilot's catalog deploys today (ghcr.io/anyone-protocol/ator-protocol:latest,
# built 2025-04-23), pinned, to prove this image takes over a volume it wrote.
VENDOR=ghcr.io/anyone-protocol/ator-protocol@sha256:62af1d6e0245667765f217bcce90d31c82fe687203abc66af7cf117e12581265
# The capabilities the vendor image cannot start without. Only its run here gets them.
VENDOR_CAPS=(--cap-add CHOWN --cap-add DAC_OVERRIDE --cap-add FOWNER --cap-add SETUID --cap-add SETGID)
P="anyone-smoke-$$"
HARDEN=(--cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --memory 1536m)
VERSION=$(tr -d '[:space:]' <"$(dirname "$0")/VERSION")
# The command CashPilot's UI tells operators to run for the relay fingerprint,
# taken from the catalog so the hint and this test cannot drift apart.
HINT=$(sed -n 's#.*<b>docker exec cashpilot-anyone-protocol \([^<]*\)</b>.*#\1#p' \
	"$(dirname "$0")/../../services/depin/anyone-protocol.yml")
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
logs_have() { docker logs "$1" 2>&1 | grep -qF -- "$2"; }
exit_code() { docker inspect -f '{{.State.ExitCode}}' "$1"; }
healthy() { test "$(docker inspect -f '{{.State.Health.Status}}' "$1")" = healthy; }
notices_have() { docker exec "$1" grep -qF -- "$2" /etc/anon/notices.log; }
# The anonrc the fleet's relays use, with a test nickname and the descriptor
# kept off the network. `User anond` stays in: every existing anonrc has it.
# ORPORTS replaces the ORPort line.
anonrc() {
	cat <<RC
User anond
DataDirectory /var/lib/anon
Log [~guard]notice [guard]warn file /etc/anon/notices.log
${ORPORTS:-ORPort 9001 IPv4Only}
ExitRelay 0
SocksPort 0
Nickname $1
PublishServerDescriptor 0
AgreeToTerms 1
${EXTRA:-}
RC
}
# put_anonrc <volume> <nickname> <image> [chown]: write anonrc into a config volume.
put_anonrc() {
	local cmd='cat > /etc/anon/anonrc' user=100
	if [[ "${4:-}" == chown ]]; then
		cmd+=' && chown -R 100:101 /etc/anon'
		user=0
	fi
	anonrc "$2" | docker run --rm -i -u "$user" -v "$1:/etc/anon" --entrypoint sh "$3" -c "$cmd"
}
relay() { # relay <name> <volume prefix> <docker run options... and the image>
	local name=$1 vol=$2
	shift 2
	docker run -d --name "$name" \
		-v "$vol-data:/var/lib/anon" -v "$vol-conf:/etc/anon" -v "$vol-run:/run/anon" "$@" >/dev/null
}

echo "== $IMAGE"

echo "-- the image"
check "runs as anond, uid 100 gid 101 (the vendor image's ids)" \
	test "$(docker run --rm --entrypoint id "$IMAGE")" = "uid=100(anond) gid=101(anond) groups=101(anond)"
check "carries anon ${VERSION%%-live*}" \
	bash -c "docker run --rm --entrypoint anon '$IMAGE' --version | grep -qF 'Anon version ${VERSION%%-live*}-live'"

echo "-- fails closed, with a message that says what to do"
docker run --name "$P-noconf" "${HARDEN[@]}" -v "$P-noconf:/etc/anon" "$IMAGE" >/dev/null 2>&1
check "exits 1 without an anonrc" test "$(exit_code "$P-noconf")" = 1
check "says there is no anonrc" logs_have "$P-noconf" "no readable /etc/anon/anonrc"

put_anonrc "$P-ro-conf" CashPilotSmokeRo "$IMAGE"
mkdir "$TMP/data" && chmod 755 "$TMP/data"
docker run --name "$P-ro" "${HARDEN[@]}" -v "$P-ro-conf:/etc/anon" -v "$TMP/data:/var/lib/anon" "$IMAGE" >/dev/null 2>&1
check "exits 1 when the data directory is not anond's" test "$(exit_code "$P-ro")" = 1
check "says to chown it to 100:101" logs_have "$P-ro" "chown -R 100:101"

echo "-- runs a relay under CashPilot's hardening, no capabilities added"
put_anonrc "$P-a-conf" CashPilotSmokeA "$IMAGE"
relay "$P-a" "$P-a" "${HARDEN[@]}" "$IMAGE"
check "becomes healthy" wait_for 120 healthy "$P-a"
check "bootstraps to 100%" wait_for 180 notices_have "$P-a" "Bootstrapped 100%"
check "anon is PID 1, as uid 100" bash -c "docker exec $P-a grep -qE '^Uid:\s+100\s' /proc/1/status"
check "with no effective capabilities" bash -c "docker exec $P-a grep -qE '^CapEff:\s+0+$' /proc/1/status"
# 1536m is CashPilot's limit; half of it, and a relay that bootstrapped with it.
check "caps MaxMemInQueues at half the container's memory limit" \
	bash -c "docker exec $P-a tr '\\0' ' ' </proc/1/cmdline | grep -qF -- '--MaxMemInQueues 768 MB'"
check "made an identity in a fresh named volume, no chown" docker exec "$P-a" test -s /var/lib/anon/keys/ed25519_master_id_secret_key
# The fingerprint file's line, or --list-fingerprint's spaced form of it.
check "the catalog's fingerprint command ($HINT) prints the fingerprint" \
	bash -c "docker exec $P-a $HINT | grep -qE '^CashPilotSmokeA [0-9A-F ]{40,}$'"
fp_a=$(docker exec "$P-a" cat /var/lib/anon/fingerprint-ed25519 2>/dev/null)
docker stats --no-stream --format '  info  memory {{.MemUsage}}, pids {{.PIDs}}' "$P-a"

check "health check fails with nothing listening on the ORPort" \
	docker run --rm -v "$P-a-conf:/etc/anon:ro" --entrypoint sh "$IMAGE" -c '! cashpilot-anyone-health'

echo "-- leaves MaxMemInQueues alone when anonrc sets it"
EXTRA="MaxMemInQueues 300 MB" put_anonrc "$P-m-conf" CashPilotSmokeM "$IMAGE"
relay "$P-m" "$P-m" "${HARDEN[@]}" "$IMAGE"
check "starts" wait_for 60 logs_have "$P-m" "running as anond"
check "passes no MaxMemInQueues of its own" \
	bash -c "! docker exec $P-m tr '\\0' ' ' </proc/1/cmdline | grep -qF -- --MaxMemInQueues"
docker rm -f "$P-m" >/dev/null

echo "-- reloads anonrc on SIGHUP and keeps running"
docker kill -s HUP "$P-a" >/dev/null
check "logs the reload" wait_for 15 notices_have "$P-a" "Received reload signal (hup)"
sleep 3
check "still running after the reload" test "$(docker inspect -f '{{.State.Running}}' "$P-a")" = true
check "still listening on the ORPort after the reload" wait_for 15 docker exec "$P-a" cashpilot-anyone-health

echo "-- health check reads the ORPort anon listens on, not an advertised-only one"
# The port-forward setup: advertise 9003, listen on 9001, NoListen line first.
ORPORTS=$'ORPort 9003 NoListen IPv4Only\nORPort 9001 NoAdvertise IPv4Only' put_anonrc "$P-nl-conf" CashPilotSmokeNl "$IMAGE"
relay "$P-nl" "$P-nl" "${HARDEN[@]}" "$IMAGE"
check "healthy with a NoListen ORPort listed first" wait_for 60 docker exec "$P-nl" cashpilot-anyone-health
docker rm -f "$P-nl" >/dev/null

echo "-- stops cleanly and keeps its identity"
t0=$(date +%s)
docker stop "$P-a" >/dev/null
took=$(($(date +%s) - t0))
check "docker stop takes under 10 s (took ${took}s)" test "$took" -lt 10
check "exits 0 on SIGTERM" test "$(exit_code "$P-a")" = 0
docker rm "$P-a" >/dev/null
relay "$P-a2" "$P-a" "${HARDEN[@]}" "$IMAGE"
check "a recreated container becomes healthy" wait_for 120 healthy "$P-a2"
check "and has the same identity" test -n "$fp_a" -a "$(docker exec "$P-a2" cat /var/lib/anon/fingerprint-ed25519 2>/dev/null)" = "$fp_a"

echo "-- takes over a relay the vendor image created, same identity"
# Set up the way docs/guides/anyone-protocol.md says: anonrc written as root, chowned to 100:101.
put_anonrc "$P-v-conf" CashPilotSmokeV "$VENDOR" chown
relay "$P-v" "$P-v" "${HARDEN[@]}" "${VENDOR_CAPS[@]}" "$VENDOR"
check "the vendor image made an identity" wait_for 120 docker exec "$P-v" test -s /var/lib/anon/fingerprint-ed25519
sleep 5
fp_v=$(docker exec "$P-v" cat /var/lib/anon/fingerprint-ed25519 2>/dev/null)
rsa_v=$(docker exec "$P-v" cat /var/lib/anon/fingerprint 2>/dev/null)
check "the catalog's fingerprint command works on the vendor image too" \
	bash -c "docker exec $P-v $HINT | grep -qE '^CashPilotSmokeV [0-9A-F ]{40,}$'"
echo "  info  vendor identity ${fp_v:-none}"
docker stop "$P-v" >/dev/null
docker rm "$P-v" >/dev/null
relay "$P-v2" "$P-v" "${HARDEN[@]}" "$IMAGE"
# Healthy also proves it could append to the notices.log the vendor's relay
# wrote: anon exits at start when it cannot open a Log file.
check "this image starts on the vendor's volumes and becomes healthy" wait_for 120 healthy "$P-v2"
check "with the same ed25519 identity" test -n "$fp_v" -a "$(docker exec "$P-v2" cat /var/lib/anon/fingerprint-ed25519 2>/dev/null)" = "$fp_v"
check "and the same RSA fingerprint" test -n "$rsa_v" -a "$(docker exec "$P-v2" cat /var/lib/anon/fingerprint 2>/dev/null)" = "$rsa_v"

if ((FAILURES)); then
	for c in "$P-a2" "$P-v2"; do
		echo "-- logs of $c"
		docker logs --tail 30 "$c" 2>&1
	done
	echo "FAILED: $FAILURES check(s)"
	exit 1
fi
echo "All checks passed"
