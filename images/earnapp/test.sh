#!/usr/bin/env bash
# Build the image for every platform it ships and test each one: the full
# smoke test on the host's architecture, and on the others a `verify` run under
# QEMU, which downloads that architecture's build, checks it against its pinned
# sha256 and runs `earnapp --version`. That proves every SHA256SUMS line, not
# only the one the host uses.
#
#   images/earnapp/test.sh     (needs docker buildx; QEMU for foreign platforms)
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
VERSION=$(tr -d '[:space:]' <"$DIR/VERSION")
TAG="cashpilot-earnapp-test:$$"

cleanup() { docker image ls -q "cashpilot-earnapp-test:$$*" | xargs -r docker rmi -f >/dev/null; }
trap cleanup EXIT

for platform in linux/amd64 linux/arm64 linux/arm/v7; do
	img="$TAG-${platform//\//-}"
	echo "== build $platform"
	docker buildx build --quiet --platform "$platform" --load -t "$img" "$DIR" >/dev/null
	if [[ "$platform" == linux/amd64 ]]; then
		"$DIR/smoke.sh" "$img"
	else
		echo "== verify $platform"
		out=$(docker run --rm --platform "$platform" --cap-drop ALL --security-opt no-new-privileges:true \
			--pids-limit 512 --memory 256m "$img" verify)
		echo "$out"
		grep -q "sha256 matches the pin" <<<"$out" && grep -qF "$VERSION" <<<"$out" || {
			echo "FAILED: $platform did not verify and report $VERSION" >&2
			exit 1
		}
	fi
done
echo "All platforms passed"
