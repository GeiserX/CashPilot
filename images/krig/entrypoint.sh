#!/bin/sh
set -eu

pins=/usr/local/share/krig
version=$(cat "$pins/VERSION")
archive_hash=$(cat "$pins/ARCHIVE_SHA256")
binary_hash=$(cat "$pins/BINARY_SHA256")
cache=/var/lib/krig
miner="$cache/krig-miner-$version"

fail() {
    printf 'KRig: %s\n' "$*" >&2
    exit 1
}

verify() {
    printf '%s  %s\n' "$1" "$2" | sha256sum --check --status
}

if [ ! -x "$miner" ] || ! verify "$binary_hash" "$miner"; then
    url="https://github.com/kryptex/krig-miner/releases/download/v$version/krig-miner-$version-linux-x64.tar.gz"
    # A container killed with SIGKILL mid-download cannot run its trap, so
    # clear any staging folder an earlier start left behind. Only one
    # container uses this volume, so no other install is running now.
    rm -rf -- "$cache"/.install.*
    tmp=$(mktemp -d "$cache/.install.XXXXXX") ||
        fail "mount a writable volume at $cache for uid 10001"
    cleanup() {
        rm -f -- "$tmp/release.tar.gz" "$tmp/krig-miner"
        rmdir -- "$tmp"
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    printf 'Downloading KRig %s from GitHub\n' "$version" >&2
    curl --disable --fail --silent --show-error --location \
        --proto '=https' --proto-redir '=https' --connect-timeout 10 \
        --max-time 120 --retry 2 --retry-max-time 90 \
        --output "$tmp/release.tar.gz" "$url" ||
        fail 'download failed. Allow outbound HTTPS to GitHub and its release asset host.'
    verify "$archive_hash" "$tmp/release.tar.gz" ||
        fail "release archive SHA-256 mismatch for $version"
    tar -xOzf "$tmp/release.tar.gz" -- krig-miner > "$tmp/krig-miner"
    verify "$binary_hash" "$tmp/krig-miner" ||
        fail "extracted executable SHA-256 mismatch for $version"
    chmod 0755 "$tmp/krig-miner"
    mv -fT -- "$tmp/krig-miner" "$miner"
    printf 'Verified and installed KRig %s\n' "$version" >&2
    cleanup
    trap - EXIT INT TERM
fi

cd "$cache"
exec "$miner" "$@"
