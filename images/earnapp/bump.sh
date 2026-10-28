#!/usr/bin/env bash
# Point the image at the EarnApp version Bright Data's installer serves today.
#
#   images/earnapp/bump.sh
#
# Reads VERSION= from install.sh (read, never run), fetches the sha256 sidecar
# of each build the image uses, and rewrites VERSION, SHA256SUMS and REVISION
# beside this script. Prints the version, and writes nothing when it is
# already pinned. Exits non-zero when anything it reads looks wrong, so the
# weekly job opens no PR from a half-read answer.
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
INSTALLER=https://brightdata.com/static/earnapp/install.sh
CDN_BASE=https://cdn-earnapp.b-cdn.net/static
ARCHES=(x64 aarch64 arm7l)

version=$(curl -fsSL --retry 3 "$INSTALLER" | sed -nE 's/^VERSION="([0-9]+\.[0-9]+\.[0-9]+)"$/\1/p' | head -n1)
[[ -n "$version" ]] || {
	echo "no VERSION=\"x.y.z\" line in $INSTALLER; the installer changed shape" >&2
	exit 1
}

current=$(tr -d '[:space:]' <"$DIR/VERSION")
if [[ "$version" == "$current" ]]; then
	echo "$version (already pinned)"
	exit 0
fi

sums=""
for arch in "${ARCHES[@]}"; do
	file="earnapp-ssl3-$arch-$version"
	line=$(curl -fsSL --retry 3 "$CDN_BASE/$file.sha256")
	hash=${line%% *}
	[[ "$hash" =~ ^[0-9a-f]{64}$ && "$line" == *"$file" ]] || {
		echo "unexpected sidecar for $file: $line" >&2
		exit 1
	}
	sums+="$hash  $file"$'\n'
done

printf '%s' "$sums" >"$DIR/SHA256SUMS"
printf '%s\n' "$version" >"$DIR/VERSION"
printf '1\n' >"$DIR/REVISION"
echo "$version (was $current)"
