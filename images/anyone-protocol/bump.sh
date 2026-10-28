#!/usr/bin/env bash
# Point the image at the newest anon the vendor's live bookworm repository
# serves.
#
#   images/anyone-protocol/bump.sh
#
# Reads the anon Version from the repository's Packages index for amd64 and
# arm64, and rewrites VERSION and REVISION beside this script. Image tags carry
# only the upstream part (0.4.10.2-r<revision>), so REVISION goes back to 1
# only when that part changes; a repackage of the same anon raises it instead,
# or main would rebuild a tag that is already published. Prints the
# version, and writes nothing when it is already pinned. Exits non-zero when
# the two architectures disagree, when the index has no anon, or when the
# served version is older than the pin, so the weekly job opens no PR from a
# half-published release and never moves the pin backwards.
#
# The index is read unverified here: test.sh then installs the new pin through
# apt, which checks the repository signature against anon.asc.
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
REPO=https://deb.en.anyone.tech/dists/anon-live-bookworm/main

served=""
for arch in amd64 arm64; do
	v=$(curl -fsSL --retry 3 "$REPO/binary-$arch/Packages" |
		awk '/^Package: / { p = $2 } /^Version: / && p == "anon" { print $2 }' | sort -V | tail -n1)
	[[ "$v" =~ ^[0-9]+(\.[0-9]+)+-live-[0-9A-Za-z.+~-]+$ ]] || {
		echo "no live anon version in $REPO/binary-$arch/Packages (got '$v')" >&2
		exit 1
	}
	if [[ -n "$served" && "$v" != "$served" ]]; then
		echo "amd64 serves $served but $arch serves $v; waiting for the release to finish" >&2
		exit 1
	fi
	served=$v
done

current=$(tr -d '[:space:]' <"$DIR/VERSION")
if [[ "$served" == "$current" ]]; then
	echo "$served (already pinned)"
	exit 0
fi
if dpkg --compare-versions "$served" lt "$current" 2>/dev/null ||
	[[ "$(printf '%s\n' "$current" "$served" | sort -V | tail -n1)" != "$served" ]]; then
	echo "the repository serves $served, older than the pinned $current; refusing to move the pin backwards" >&2
	exit 1
fi

revision=1
if [[ "${served%%-live*}" == "${current%%-live*}" ]]; then
	revision=$(($(tr -d '[:space:]' <"$DIR/REVISION") + 1))
fi
printf '%s\n' "$served" >"$DIR/VERSION"
printf '%s\n' "$revision" >"$DIR/REVISION"
echo "$served (was $current), revision $revision"
