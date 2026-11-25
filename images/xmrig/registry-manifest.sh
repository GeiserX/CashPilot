#!/usr/bin/env bash
# Print a public Docker Hub manifest. Exit 44 for a missing tag or repository.
set -euo pipefail

repo=$1
tag=$2
manifest=$(mktemp)
trap 'rm -- "$manifest"' EXIT

token=$(curl -fsS --retry 3 --max-time 30 \
	"https://auth.docker.io/token?service=registry.docker.io&scope=repository:$repo:pull" | jq -er '.token')
code=$(curl -sS --retry 3 --max-time 30 -o "$manifest" -w '%{http_code}' \
	-H "Authorization: Bearer $token" \
	-H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json' \
	"https://registry-1.docker.io/v2/$repo/manifests/$tag")
case "$code" in
	200) cat "$manifest"; exit 0 ;;
	404) exit 44 ;;
	401)
		# Before the first publish, the registry can deny access because the
		# public repository itself does not exist yet.
		hub_code=$(curl -sS --retry 3 --max-time 30 -o /dev/null -w '%{http_code}' \
			"https://hub.docker.com/v2/repositories/$repo/")
		if [[ "$hub_code" == 404 ]]; then exit 44; fi
		;;
esac
echo "Docker Hub registry answered $code for $repo:$tag" >&2
exit 1
