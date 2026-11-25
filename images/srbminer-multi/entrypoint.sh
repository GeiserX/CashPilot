#!/bin/sh
set -eu

pins=/usr/local/share/srbminer
version=$(cat "$pins/VERSION")
archive_hash=$(cat "$pins/ARCHIVE_SHA256")
binary_hash=$(cat "$pins/BINARY_SHA256")
cache=/var/lib/srbminer
miner="$cache/SRBMiner-MULTI-$version"

fail() {
    printf 'SRBMiner-Multi: %s\n' "$*" >&2
    exit 1
}

verify() {
    printf '%s  %s\n' "$1" "$2" | sha256sum --check --status
}

if [ ! -x "$miner" ] || ! verify "$binary_hash" "$miner"; then
    release="SRBMiner-Multi-$(printf '%s' "$version" | tr . -)"
    url="https://github.com/doktor83/SRBMiner-Multi/releases/download/$version/$release-Linux.tar.gz"
    # A container killed with SIGKILL mid-download cannot run its trap, so
    # clear any staging folder an earlier start left behind. Only one
    # container uses this volume, so no other install is running now.
    rm -rf -- "$cache"/.install.*
    tmp=$(mktemp -d "$cache/.install.XXXXXX") ||
        fail "mount a writable volume at $cache for uid 10001"
    cleanup() {
        rm -f -- "$tmp/release.tar.gz" "$tmp/SRBMiner-MULTI"
        rmdir -- "$tmp"
    }
    trap cleanup EXIT
    trap 'exit 130' INT
    trap 'exit 143' TERM

    printf 'Downloading SRBMiner-Multi %s from GitHub\n' "$version" >&2
    curl --disable --fail --silent --show-error --location \
        --proto '=https' --proto-redir '=https' --connect-timeout 10 \
        --max-time 120 --retry 2 --retry-max-time 90 \
        --output "$tmp/release.tar.gz" "$url" ||
        fail 'download failed. Allow outbound HTTPS to GitHub and its release asset host.'
    verify "$archive_hash" "$tmp/release.tar.gz" ||
        fail "release archive SHA-256 mismatch for $version"
    tar -xOzf "$tmp/release.tar.gz" -- "$release/SRBMiner-MULTI" > "$tmp/SRBMiner-MULTI"
    verify "$binary_hash" "$tmp/SRBMiner-MULTI" ||
        fail "extracted executable SHA-256 mismatch for $version"
    chmod 0755 "$tmp/SRBMiner-MULTI"
    mv -fT -- "$tmp/SRBMiner-MULTI" "$miner"
    printf 'Verified and installed SRBMiner-Multi %s\n' "$version" >&2
    cleanup
    trap - EXIT INT TERM
fi

cd "$cache"
if [ "$#" -eq 1 ] && [ "$1" = --version ]; then
    # Upstream prints its version in --help and has no --version option.
    help=$("$miner" --help)
    printf '%s\n' "$help" | grep -Fx "SRBMiner-MULTI $version"
    exit
fi
exec "$miner" "$@"
