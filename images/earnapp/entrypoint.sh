#!/usr/bin/env bash
# CashPilot's EarnApp container: fetch the pinned EarnApp build from Bright
# Data's CDN, check it against the sha256 pinned in this image, then run it in
# lite mode (no systemd) until the container is stopped.
#
# The image never contains Bright Data's binary. It is downloaded on the
# user's machine at first start and cached in the /etc/earnapp volume, so a
# recreated container reuses it and checks it again instead of downloading.
#
#   cashpilot-earnapp           run EarnApp (needs EARNAPP_UUID)
#   cashpilot-earnapp verify    fetch and check the binary, print its version, exit
set -euo pipefail

CONFIG_DIR=/etc/earnapp
BIN_DIR="$CONFIG_DIR/bin"
PIN_DIR=/opt/cashpilot-earnapp
CDN_BASE=https://cdn-earnapp.b-cdn.net/static
EARNAPP=/usr/bin/earnapp # a symlink to $BIN_DIR/earnapp, made in the Dockerfile

log() { echo "[cashpilot-earnapp] $*"; }
die() {
	log "ERROR: $*"
	exit 1
}

VERSION=$(tr -d '[:space:]' <"$PIN_DIR/VERSION")

case "$(uname -m)" in
x86_64 | amd64) arch=x64 ;;
aarch64 | arm64) arch=aarch64 ;;
armv7l | armv8l) arch=arm7l ;;
*) die "unsupported CPU architecture $(uname -m); this image runs on amd64, arm64 and arm/v7" ;;
esac

# The OpenSSL 3 build on every architecture. It links OpenSSL statically, so
# it needs nothing from the base image.
FILE="earnapp-ssl3-$arch-$VERSION"
EXPECTED=$(awk -v f="$FILE" '$2 == f { print $1 }' "$PIN_DIR/SHA256SUMS")
[[ "$EXPECTED" =~ ^[0-9a-f]{64}$ ]] || die "no sha256 pinned for $FILE in $PIN_DIR/SHA256SUMS; this image is broken, report it"

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

fetch_binary() {
	mkdir -p "$BIN_DIR"
	local cached="$BIN_DIR/$FILE"
	if [[ -f "$cached" ]]; then
		if [[ "$(sha_of "$cached")" == "$EXPECTED" ]]; then
			log "Using cached $FILE (sha256 matches the pin)"
		else
			log "Cached $FILE does not match the pinned sha256; downloading it again"
			rm -f "$cached"
		fi
	fi
	if [[ ! -f "$cached" ]]; then
		local tmp="$BIN_DIR/.download"
		log "Downloading $CDN_BASE/$FILE"
		if ! curl -fsSL --retry 3 --connect-timeout 20 -o "$tmp" "$CDN_BASE/$FILE"; then
			rm -f "$tmp"
			die "could not download $CDN_BASE/$FILE. Bright Data may have moved or removed this version; a newer image will pin one it serves. Nothing was started."
		fi
		local got
		got=$(sha_of "$tmp")
		if [[ "$got" != "$EXPECTED" ]]; then
			rm -f "$tmp"
			die "sha256 mismatch for $FILE: expected $EXPECTED, got $got. Refusing to run a binary that is not the pinned one."
		fi
		chmod 755 "$tmp"
		mv -f "$tmp" "$cached"
		log "Downloaded $FILE, sha256 matches the pin"
	fi
	ln -sfn "$FILE" "$BIN_DIR/earnapp"
	# Earlier pinned builds are 35 to 55 MB each; keep only the current one.
	find "$BIN_DIR" -maxdepth 1 -type f -name 'earnapp-*' ! -name "$FILE" -delete
}

if [[ "${1:-}" == verify ]]; then
	fetch_binary
	"$EARNAPP" --version
	exit 0
fi

[[ -n "${EARNAPP_UUID:-}" ]] || die "EARNAPP_UUID is not set. Generate one with: echo sdk-node-\$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \\n')"
[[ "$EARNAPP_UUID" =~ ^sdk-node-[0-9a-f]{32}$ ]] || die "EARNAPP_UUID must be sdk-node- followed by 32 lowercase hex characters"

fetch_binary

printf %s "$EARNAPP_UUID" >"$CONFIG_DIR/uuid"
touch "$CONFIG_DIR/status"
log "EarnApp $VERSION, device $EARNAPP_UUID"
log "Link this device once, while logged in: https://earnapp.com/r/$EARNAPP_UUID"

# Bash is PID 1 and only handles a signal between foreground commands, so
# every long-running command runs in the background and is waited on.
child=""
shutdown() {
	log "Stopping EarnApp"
	[[ -n "$child" ]] && kill "$child" 2>/dev/null || true
	"$EARNAPP" stop >/dev/null 2>&1 || true
	exit 0
}
trap shutdown TERM INT

wait_child() {
	"$@" &
	child=$!
	local rc=0
	wait "$child" || rc=$?
	child=""
	return "$rc"
}

backoff=5
MAX_BACKOFF=300
while true; do
	"$EARNAPP" start || log "earnapp start exited with $?"
	started=$(date +%s)
	rc=0
	wait_child "$EARNAPP" run || rc=$?
	ran=$(($(date +%s) - started))
	# A run that lasted ten minutes was a healthy one: start over from 5 s.
	((ran >= 600)) && backoff=5
	log "earnapp run exited with code $rc after ${ran}s. Restarting it inside this container in ${backoff}s; the container itself keeps running and was not restarted."
	"$EARNAPP" stop >/dev/null 2>&1 || true
	wait_child sleep "$backoff" || true
	backoff=$((backoff * 2))
	((backoff > MAX_BACKOFF)) && backoff=$MAX_BACKOFF
done
