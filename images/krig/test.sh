#!/usr/bin/env bash
set -euo pipefail

image=$1
version=$(cat "$(dirname "$0")/VERSION")
miner="/var/lib/krig/krig-miner-$version"
tmp=$(mktemp -d)
name="cpm-test-krig-${tmp##*.}"
cache="$name-cache"
mismatch="$name-mismatch"
override="$name-pins"

cleanup() {
    containers=$(docker ps -aq --filter "name=$name")
    if [[ -n "$containers" ]]; then
        # Docker can leave a container running if the client hit its timeout.
        xargs docker rm -f <<<"$containers" >/dev/null
    fi
    docker volume rm "$cache" "$mismatch" "$override" >/dev/null
    rmdir -- "$tmp"
}
trap cleanup EXIT
docker volume create "$cache" >/dev/null
docker volume create "$mismatch" >/dev/null
docker volume create "$override" >/dev/null

harden=(--rm --init --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --log-driver none)
cache_mount=(--mount "type=volume,src=$cache,dst=/var/lib/krig")
mismatch_mount=(--mount "type=volume,src=$mismatch,dst=/var/lib/krig")

docker run "${harden[@]}" --name "$name-empty" --network none "${cache_mount[@]}" \
    --entrypoint sh "$image" -c 'entries=$(ls -A /var/lib/krig) && test -z "$entries"'
out=$(timeout 150s docker run "${harden[@]}" --name "$name-first" "${cache_mount[@]}" \
    "$image" --version 2>&1 | head -c 65536) || {
    printf '%s\n' "$out" >&2
    exit 1
}
printf '%s\n' "$out"
grep -F "Verified and installed KRig $version" <<<"$out"
grep -F "krig-miner v$version (" <<<"$out"

out=$(timeout 15s docker run "${harden[@]}" --name "$name-offline" --network none \
    "${cache_mount[@]}" "$image" --version | head -c 65536)
grep -F "krig-miner v$version (" <<<"$out"

# A cached executable must still match the image's pin.
docker run "${harden[@]}" --name "$name-corrupt" --network none "${cache_mount[@]}" \
    --entrypoint sh "$image" -c 'printf corrupt > "$1"' sh "$miner"
if out=$(timeout 15s docker run "${harden[@]}" --name "$name-reject-cache" --network none \
    "${cache_mount[@]}" "$image" --version 2>&1 | head -c 65536); then
    echo "the container accepted a corrupted cache" >&2
    exit 1
fi
grep -F 'download failed.' <<<"$out"

# Exercise both checks with a fresh cache and one deliberately wrong pin.
reject_pin() {
    local pin=$1 expected=$2 out
    docker run "${harden[@]}" --name "$name-wrong-pin" --network none --user 0:0 \
        --mount "type=volume,src=$override,dst=/override" \
        --entrypoint sh "$image" -c '
            cp /usr/local/share/krig/* /override/
            printf "%064d\n" 0 > "/override/$1"
        ' sh "$pin"
    if out=$(timeout 150s docker run "${harden[@]}" --name "$name-reject-pin" "${mismatch_mount[@]}" \
        --mount "type=volume,src=$override,dst=/usr/local/share/krig,readonly" \
        "$image" --version 2>&1 | head -c 65536); then
        echo "the container accepted an incorrect $pin" >&2
        exit 1
    fi
    grep -F "$expected" <<<"$out"
    docker run "${harden[@]}" --name "$name-after-mismatch" --network none "${mismatch_mount[@]}" \
        --entrypoint sh "$image" -c 'entries=$(ls -A /var/lib/krig) && test -z "$entries"'
}

reject_pin ARCHIVE_SHA256 'release archive SHA-256 mismatch'
reject_pin BINARY_SHA256 'extracted executable SHA-256 mismatch'

# A start killed with SIGKILL mid-download leaves its staging folder behind;
# the next start must clear it.
docker run "${harden[@]}" --name "$name-stale" --network none "${mismatch_mount[@]}" \
    --entrypoint sh "$image" -c 'mkdir /var/lib/krig/.install.stale && printf x > /var/lib/krig/.install.stale/release.tar.gz'
if timeout 15s docker run "${harden[@]}" --name "$name-clear-stale" --network none \
    "${mismatch_mount[@]}" "$image" --version >/dev/null 2>&1; then
    echo "the container ran without a verified executable" >&2
    exit 1
fi
docker run "${harden[@]}" --name "$name-after-stale" --network none "${mismatch_mount[@]}" \
    --entrypoint sh "$image" -c 'entries=$(ls -A /var/lib/krig) && test -z "$entries"'
