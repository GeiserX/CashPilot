# cashpilot-krig

This unofficial [CashPilot](https://github.com/GeiserX/CashPilot) image runs
KRig on Linux amd64. The [KRig license](https://github.com/kryptex/krig-miner/blob/v1.8.2/LICENSE)
permits redistribution of the release binaries. The image downloads KRig at
first start, like CashPilot's SRBMiner-Multi image.

## First start

The startup script downloads the [pinned release](https://github.com/kryptex/krig-miner/releases/tag/v1.8.2).
It needs outbound HTTPS to GitHub and its release asset host. It checks the
archive's SHA-256, extracts and verifies the executable, then discards the archive.

The script checks the cached executable on each start. It downloads a fresh
copy if the pinned version is missing or fails verification. Give each
container its own volume at `/var/lib/krig`. Keep the volume when replacing that
container to reuse the download. If you use a bind mount, give UID and GID
10001 write access.

## Check the version

```sh
docker run --rm --cap-drop ALL --security-opt no-new-privileges:true \
  --mount type=volume,src=krig-cache,dst=/var/lib/krig \
  drumsergio/cashpilot-krig:1.8.2-r1 --version
```

The script passes arguments to KRig. Mining needs a GPU grant and the NVIDIA
Container Toolkit. The startup checks run with zero GPUs and only use
`--version`.

## Tags and upgrades

- `1.8.2-r1` pins an image revision. The workflow rejects changes to its image inputs.
- `1.8.2` points to the newest published revision of that miner version.

For a release bump, download the official Linux x64 archive. Compare its
SHA-256 with the release asset digest in GitHub's API. Compute the SHA-256 of
`krig-miner` from that archive and update both pins. Reset `REVISION` to 1 for a
new version, or raise it for an image change at the same version. Update this
README when either value changes.

GitHub Actions publishes the tested image on pushes to main and syncs this
README to Docker Hub.

Source: https://github.com/GeiserX/CashPilot/tree/main/images/krig
