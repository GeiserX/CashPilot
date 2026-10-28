#!/usr/bin/env bash
# Check the vendor's signing key, build the image for every platform it ships
# and test each one: the full smoke test on amd64, and on arm64 an
# `anon --version` run under QEMU and CashPilot's hardening. The arm64 build
# goes through the same signed apt install, so it proves that platform's
# package too.
#
#   images/anyone-protocol/test.sh   (needs gpg and docker buildx; QEMU for arm64)
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
VERSION=$(tr -d '[:space:]' <"$DIR/VERSION")
ANON=${VERSION%%-live*}
# Published in https://github.com/anyone-protocol/ator-protocol/blob/main/README.md
FINGERPRINT=DC73B31AA1F797B180A87CBC7571AA42A0CBEFE9
TAG="cashpilot-anyone-test:$$"

got=$(gpg --show-keys --with-colons "$DIR/anon.asc" | awk -F: '$1 == "fpr" { print $10; exit }')
if [[ "$got" != "$FINGERPRINT" ]]; then
	echo "FAILED: anon.asc has primary key $got, not the vendor's $FINGERPRINT" >&2
	exit 1
fi
echo "== anon.asc is the vendor's key $FINGERPRINT"

cleanup() { docker image ls -q "cashpilot-anyone-test:$$*" | xargs -r docker rmi -f >/dev/null; }
trap cleanup EXIT

for platform in linux/amd64 linux/arm64; do
	img="$TAG-${platform//\//-}"
	echo "== build $platform"
	docker buildx build --quiet --platform "$platform" --load -t "$img" "$DIR" >/dev/null
	if [[ "$platform" == linux/amd64 ]]; then
		"$DIR/smoke.sh" "$img"
	else
		echo "== verify $platform"
		out=$(docker run --rm --platform "$platform" --cap-drop ALL --security-opt no-new-privileges:true \
			--pids-limit 512 --memory 1536m --entrypoint anon "$img" --version)
		echo "$out"
		if ! grep -qF "Anon version $ANON-live" <<<"$out"; then
			echo "FAILED: $platform did not report anon $ANON" >&2
			exit 1
		fi
	fi
done
echo "All platforms passed"
