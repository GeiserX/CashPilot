#!/usr/bin/env bash
# CashPilot's EarnApp container: fetch the pinned EarnApp build from Bright
# Data's CDN, check it against the sha256 pinned in this image, then run it in
# lite mode (no systemd) until the container is stopped.
#
# If the CDN has dropped the pinned build, it runs the build Bright Data's
# installer serves today instead, checked against the CDN's .sha256 file, and
# says so loudly in the log.
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
INSTALLER=https://brightdata.com/static/earnapp/install.sh
EARNAPP=/usr/bin/earnapp # a symlink to $BIN_DIR/earnapp, made in the Dockerfile
# Give up on a transfer that stalls (under 1 KB/s for 60 s) instead of hanging
# at startup forever; the container then exits and its restart policy retries.
CURL=(curl --retry 3 --connect-timeout 20 --speed-time 60 --speed-limit 1024)

log() { echo "[cashpilot-earnapp] $*"; }
die() {
	log "ERROR: $*"
	exit 1
}

VERSION=$(tr -d '[:space:]' <"$PIN_DIR/VERSION")

# The build follows the image's userspace, not the kernel: a 64-bit ARM kernel
# under a 32-bit (armhf) Docker reports aarch64 in `uname -m`, yet only the
# arm7l build can run in the arm/v7 image.
case "$(dpkg --print-architecture)" in
amd64) arch=x64 ;;
arm64) arch=aarch64 ;;
armhf) arch=arm7l ;;
*) die "unsupported architecture $(dpkg --print-architecture); this image runs on amd64, arm64 and arm/v7" ;;
esac

# The OpenSSL 3 build. arm7l is linked statically; x64 and aarch64 link
# glibc, which the Debian base provides.
FILE="earnapp-ssl3-$arch-$VERSION"
EXPECTED=$(awk -v f="$FILE" '$2 == f { print $1 }' "$PIN_DIR/SHA256SUMS")
[[ "$EXPECTED" =~ ^[0-9a-f]{64}$ ]] || die "no sha256 pinned for $FILE in $PIN_DIR/SHA256SUMS; this image is broken, report it"

sha_of() { sha256sum "$1" | cut -d' ' -f1; }

# use_build <file> <sha256> <source of the sha256>: make <file>, checked
# against <sha256>, the binary /usr/bin/earnapp runs, reusing the cached copy
# when it matches. Sets GONE=1 and returns when the CDN answers 404 for <file>;
# dies on any other failure.
use_build() {
	local file=$1 expected=$2 what=$3
	GONE=0
	local cached="$BIN_DIR/$file"
	mkdir -p "$BIN_DIR"
	if [[ -f "$cached" ]]; then
		if [[ "$(sha_of "$cached")" == "$expected" ]]; then
			# A volume restored from a backup can lose the execute bit.
			chmod 755 "$cached"
			log "Using cached $file (sha256 matches $what)"
		else
			log "Cached $file does not match its sha256; downloading it again"
			rm -f "$cached"
		fi
	fi
	if [[ ! -f "$cached" ]]; then
		local tmp="$BIN_DIR/.download" code got
		log "Downloading $CDN_BASE/$file"
		code=$("${CURL[@]}" -sSL -o "$tmp" -w '%{http_code}' "$CDN_BASE/$file") || code=failed
		if [[ "$code" != 200 ]]; then
			rm -f "$tmp"
			if [[ "$code" == 404 ]]; then
				GONE=1
				return 0
			fi
			die "could not download $CDN_BASE/$file (HTTP $code). Nothing was started."
		fi
		got=$(sha_of "$tmp")
		if [[ "$got" != "$expected" ]]; then
			rm -f "$tmp"
			die "sha256 mismatch for $file: expected $expected, got $got. Refusing to run it."
		fi
		chmod 755 "$tmp"
		mv -f "$tmp" "$cached"
		log "Downloaded $file, sha256 matches $what"
	fi
	ln -sfn "$file" "$BIN_DIR/earnapp"
	# Earlier builds are 35 to 55 MB each; keep only the current one.
	find "$BIN_DIR" -maxdepth 1 -type f -name 'earnapp-*' ! -name "$file" -delete
}

# Bright Data's CDN keeps only the build its installer serves. When it has
# dropped the pinned one, a new device would never start, so fall back to the
# version install.sh names today (read, never run), checked against the CDN's
# own .sha256 file. That is the same unsigned source the weekly bump pins
# from, without a person looking at it first; the log says so on every start.
use_served_build() {
	local served file line hash
	served=$("${CURL[@]}" -fsSL "$INSTALLER" | sed -nE 's/^VERSION="([0-9]+\.[0-9]+\.[0-9]+)"$/\1/p' | head -n1) ||
		die "the pinned $FILE is gone from the CDN and $INSTALLER could not be read. Nothing was started."
	[[ -n "$served" ]] || die "the pinned $FILE is gone from the CDN and $INSTALLER names no VERSION. Nothing was started."
	[[ "$(printf '%s\n' "$VERSION" "$served" | sort -V | tail -n1)" == "$served" && "$served" != "$VERSION" ]] ||
		die "the pinned $FILE is gone from the CDN and the installer serves $served, which is not newer. Nothing was started."
	file="earnapp-ssl3-$arch-$served"
	line=$("${CURL[@]}" -fsSL "$CDN_BASE/$file.sha256") ||
		die "no sha256 file for $file on the CDN. Nothing was started."
	hash=${line%% *}
	[[ "$hash" =~ ^[0-9a-f]{64}$ && "$line" == *"$file" ]] || die "unexpected sha256 file for $file: $line"
	log "WARNING: Bright Data no longer serves the pinned EarnApp $VERSION. Running $served instead, checked only against the CDN's unsigned .sha256 file, not a hash pinned in this image. A newer image pins it properly."
	use_build "$file" "$hash" "the CDN's .sha256 file"
	((GONE == 0)) || die "the installer names $served but the CDN answers 404 for $file. Nothing was started."
	RUNNING=$served
}

fetch_binary() {
	RUNNING=$VERSION
	use_build "$FILE" "$EXPECTED" "the pin"
	if ((GONE)); then use_served_build; fi
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
log "EarnApp $RUNNING, device $EARNAPP_UUID"
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
