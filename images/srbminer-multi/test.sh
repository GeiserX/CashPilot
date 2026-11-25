#!/usr/bin/env bash
set -euo pipefail

image=$1
version=$(cat "$(dirname "$0")/VERSION")
miner="/var/lib/srbminer/SRBMiner-MULTI-$version"
tmp=$(mktemp -d)
name="cpm-test-srbminer-${tmp##*.}"
cache="$name-cache"
mismatch="$name-mismatch"

cleanup() {
    containers=$(docker ps -aq --filter "name=$name")
    if [[ -n "$containers" ]]; then
        # Docker can leave a container running if the client hit its timeout.
        xargs docker rm -f <<<"$containers" >/dev/null
    fi
    docker volume rm "$cache" "$mismatch" >/dev/null
    rm -f -- "$tmp/ARCHIVE_SHA256"
    rmdir -- "$tmp"
}
trap cleanup EXIT
docker volume create "$cache" >/dev/null
docker volume create "$mismatch" >/dev/null

harden=(--rm --init --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --log-driver none)
cache_mount=(--mount "type=volume,src=$cache,dst=/var/lib/srbminer")
mismatch_mount=(--mount "type=volume,src=$mismatch,dst=/var/lib/srbminer")

docker run "${harden[@]}" --name "$name-empty" --network none "${cache_mount[@]}" \
    --entrypoint sh "$image" -c 'test -z "$(ls -A /var/lib/srbminer)"'
out=$(timeout 150s docker run "${harden[@]}" --name "$name-first" "${cache_mount[@]}" \
    "$image" --version 2>&1 | head -c 65536) || {
    printf '%s\n' "$out" >&2
    exit 1
}
printf '%s\n' "$out"
grep -F "Verified and installed SRBMiner-Multi $version" <<<"$out"
grep -iFx "SRBMiner-MULTI $version" <<<"$out"

out=$(timeout 15s docker run "${harden[@]}" --name "$name-offline" --network none \
    "${cache_mount[@]}" "$image" --version | head -c 65536)
grep -iFx "SRBMiner-MULTI $version" <<<"$out"

# A cached executable must still match the image's pin.
docker run "${harden[@]}" --name "$name-corrupt" --network none "${cache_mount[@]}" \
    --entrypoint sh "$image" -c 'printf corrupt > "$1"' sh "$miner"
if out=$(timeout 15s docker run "${harden[@]}" --name "$name-reject-cache" --network none \
    "${cache_mount[@]}" "$image" --version 2>&1 | head -c 65536); then
    echo "the container accepted a corrupted cache" >&2
    exit 1
fi
grep -F 'download failed.' <<<"$out"

# A successful HTTPS download alone must not install an unpinned archive.
printf '%064d\n' 0 > "$tmp/ARCHIVE_SHA256"
chmod 0444 "$tmp/ARCHIVE_SHA256"
if out=$(timeout 150s docker run "${harden[@]}" --name "$name-reject-archive" "${mismatch_mount[@]}" \
    --mount "type=bind,src=$tmp/ARCHIVE_SHA256,dst=/usr/local/share/srbminer/ARCHIVE_SHA256,readonly" \
    "$image" --version 2>&1 | head -c 65536); then
    echo "the container accepted an archive with a different SHA-256" >&2
    exit 1
fi
grep -F 'release archive SHA-256 mismatch' <<<"$out"
docker run "${harden[@]}" --name "$name-after-mismatch" --network none "${mismatch_mount[@]}" \
    --entrypoint sh "$image" -c 'test -z "$(ls -A /var/lib/srbminer)"'
