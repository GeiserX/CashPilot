#!/usr/bin/env bash
# Point the image at XMRig's newest release, only when XMRig itself signed the
# release commit.
#
#   images/xmrig/bump.sh          the newest release (releases/latest)
#   images/xmrig/bump.sh v6.27.0  that release tag
#
# Resolves the tag to its commit and refuses unless GitHub marks that commit's
# signature verified AND the committer is XMRig's own account (GitHub login
# "xmrig", email support@xmrig.com). GitHub verifies a signature only against
# a key registered to the account that owns the committer email, so together
# they mean XMRig's key signed it. "verified" alone also passes a web-UI commit
# or merge by anyone with write access, which GitHub's web-flow key signs.
# Then it rewrites VERSION, COMMIT and REVISION beside this script. Writes
# nothing when the version is already pinned, and refuses a version older
# than the pin, so a pulled release never moves it backwards.
# Set GITHUB_TOKEN to raise the API rate limit.
set -euo pipefail

DIR=$(cd "$(dirname "$0")" && pwd)
API=https://api.github.com/repos/xmrig/xmrig
SIGNER_LOGIN=xmrig
SIGNER_EMAIL=support@xmrig.com
CURL=(curl -fsSL --retry 3 -H "Accept: application/vnd.github+json")
if [[ -n "${GITHUB_TOKEN:-}" ]]; then CURL+=(-H "Authorization: Bearer $GITHUB_TOKEN"); fi

die() {
	echo "$*" >&2
	exit 1
}

tag=${1:-$("${CURL[@]}" "$API/releases/latest" | jq -r '.tag_name // empty')}
[[ "$tag" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "unexpected release tag '$tag'; expected vX.Y.Z"
version=${tag#v}

current=$(tr -d '[:space:]' <"$DIR/VERSION")
if [[ "$version" == "$current" ]]; then
	echo "$version (already pinned)"
	exit 0
fi
if [[ "$(printf '%s\n' "$current" "$version" | sort -V | tail -n1)" != "$version" ]]; then
	die "$tag is older than the pinned $current; refusing to move the pin backwards"
fi

# A lightweight tag points at the commit; an annotated one at a tag object.
ref=$("${CURL[@]}" "$API/git/ref/tags/$tag")
type=$(jq -r '.object.type' <<<"$ref")
sha=$(jq -r '.object.sha' <<<"$ref")
if [[ "$type" == tag ]]; then
	ref=$("${CURL[@]}" "$API/git/tags/$sha")
	type=$(jq -r '.object.type' <<<"$ref")
	sha=$(jq -r '.object.sha' <<<"$ref")
fi
[[ "$type" == commit && "$sha" =~ ^[0-9a-f]{40}$ ]] || die "$tag does not resolve to a commit (got $type $sha)"

commit=$("${CURL[@]}" "$API/commits/$sha")
verification=$(jq -c '.commit.verification' <<<"$commit")
[[ "$(jq -r '.verified' <<<"$verification")" == true ]] ||
	die "GitHub does not report a valid signature on $sha ($tag): $verification. Refusing to pin it."
login=$(jq -r '.committer.login // empty' <<<"$commit")
email=$(jq -r '.commit.committer.email // empty' <<<"$commit")
[[ "$login" == "$SIGNER_LOGIN" && "$email" == "$SIGNER_EMAIL" ]] ||
	die "$sha ($tag) is signed, but committed by '${login:-no account}' <$email>, not XMRig's own $SIGNER_LOGIN <$SIGNER_EMAIL>. Refusing to pin it."

# VERSION goes last: it is what marks the bump done. A run interrupted before
# it leaves the old VERSION, so the next run redoes the whole bump.
printf '%s\n' "$sha" >"$DIR/COMMIT"
printf '1\n' >"$DIR/REVISION"
printf '%s\n' "$version" >"$DIR/VERSION"
echo "$version (was $current), commit $sha, signed by $SIGNER_LOGIN <$SIGNER_EMAIL>, verified by GitHub"
