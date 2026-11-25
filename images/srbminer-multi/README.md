# cashpilot-srbminer-multi

This unofficial [CashPilot](https://github.com/GeiserX/CashPilot) image starts SRBMiner-Multi on Linux amd64. It contains the startup script and its runtime tools. The miner's license restricts redistribution of its binaries.

On first start, the script downloads the [official release](https://github.com/doktor83/SRBMiner-Multi/releases/tag/3.9.0). It needs outbound HTTPS to GitHub and its release asset host. The script checks the archive's pinned SHA-256 before it extracts the executable into `/var/lib/srbminer`. It discards the archive.

The script verifies the cached executable on each start. It downloads a fresh copy if the pinned version is missing or the cached file fails verification. Keep the volume attached across container replacements to reuse the download. The container runs as UID and GID 10001. If you use a bind mount, make it writable by that user.

## Check the version

```sh
docker run --rm --cap-drop ALL --security-opt no-new-privileges:true \
  --mount type=volume,src=srbminer-cache,dst=/var/lib/srbminer \
  drumsergio/cashpilot-srbminer-multi:3.9.0-r1 --version
```

The startup script reads `--version` from the miner's help output. It passes mining arguments directly to SRBMiner-Multi. Use NVIDIA Container Toolkit and a GPU grant to mine on an NVIDIA host.

## Tags and upgrades

- `3.9.0-r1` pins an image revision. The workflow refuses to replace it with different image inputs.
- `3.9.0` points at the newest published revision of that version.

Update the version and both SHA-256 pins in a pull request. Compute the archive and executable hashes from the official release. These pins use trust on first use. They identify the exact bytes the image accepts. Reset `REVISION` to 1 for a new release. Raise it for a change to the image at the same miner version.

GitHub Actions builds and tests the image on amd64. It runs only `--version`, with zero GPUs and no pool arguments. A push to main publishes the tested image and syncs this README to Docker Hub.

Source: https://github.com/GeiserX/CashPilot/tree/main/images/srbminer-multi
