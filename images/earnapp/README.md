# cashpilot-earnapp

An unofficial EarnApp container for [CashPilot](https://github.com/GeiserX/CashPilot). It is not made, endorsed or supported by Bright Data, and it is not affiliated with them.

> **Running EarnApp in Docker breaks EarnApp's terms.** Bright Data's help centre says installing EarnApp in Docker containers, virtual machines, hosting services or personal or home servers "is strictly prohibited", and that it terminates the account without notice and cancels pending payments when it detects one: https://help.earnapp.com/hc/en-us/articles/10199416541969. This image does not hide that it is a container and does nothing to avoid detection. Use it only if you accept that risk for your account and its balance.

## What it is

The image holds no Bright Data code. It contains a Debian base, an entrypoint, the EarnApp version it is pinned to (`VERSION`) and the sha256 of that version's build for each architecture (`SHA256SUMS`).

At first start the entrypoint downloads the pinned build straight from Bright Data's CDN (`https://cdn-earnapp.b-cdn.net/static/earnapp-ssl3-<arch>-<version>`), checks its sha256 against the pin, and refuses to start on a mismatch or a failed download. It picks the build from the image's own architecture (`dpkg --print-architecture`), not the kernel's, so a 32-bit Raspberry Pi OS on a 64-bit kernel gets the arm7l build it can run. The checked binary is cached in the `/etc/earnapp` volume, so recreating the container checks the copy again instead of downloading it.

It then runs EarnApp in lite mode: no systemd, no installer, no shims. Bash is PID 1, writes `EARNAPP_UUID` to `/etc/earnapp/uuid`, runs `earnapp start`, then keeps `earnapp run` in the foreground. If `earnapp run` exits, the entrypoint starts it again inside the same container after 5 s, and says so in the log. A run that dies within a minute of starting backs off, doubling up to 5 minutes; the container itself is not restarted. `docker stop` stops it cleanly.

It runs under the hardening CashPilot gives every earner: all capabilities dropped, `no-new-privileges`, not privileged, 512 pids and 256 MB of memory. EarnApp uses about 80 MB.

## Use

CashPilot's EarnApp entry (`services/bandwidth/earnapp.yml`) deploys this image. To run it by hand:

```sh
docker run -d --name earnapp \
  --cap-drop ALL --security-opt no-new-privileges:true --pids-limit 512 --memory 256m \
  -e EARNAPP_UUID=sdk-node-$(head -c 16 /dev/urandom | od -An -tx1 | tr -d ' \n') \
  -v earnapp-data:/etc/earnapp \
  --restart unless-stopped \
  drumsergio/cashpilot-earnapp:1.665.73-r2
```

Then open `https://earnapp.com/r/<your EARNAPP_UUID>` once while logged in to link the device. The log prints that link. Keep the same `EARNAPP_UUID` and volume when you recreate the container.

| Variable | Required | What it is |
|---|---|---|
| `EARNAPP_UUID` | yes | `sdk-node-` followed by 32 lowercase hex characters |

The health check passes while `/etc/earnapp/status` reads `enabled` and an `earnapp run` process is alive. It does not prove the device registered or is online: `earnapp start` writes `enabled` even when registration fails, and EarnApp's log is encrypted. Check the device on the EarnApp dashboard.

## Tags

- `<earnapp version>-r<revision>`, for example `1.665.73-r1`: never changes once pushed. Pin this one.
- `<earnapp version>`, for example `1.665.73`: the newest revision of that EarnApp version.

There is no `latest` tag. Platforms: `linux/amd64`, `linux/arm64`, `linux/arm/v7`.

## Upgrades

EarnApp's own upgrader needs systemd, so it never runs here; the image pin is the upgrade path. A daily job reads `VERSION=` from Bright Data's `install.sh` (it reads the script and never runs it), fetches the CDN's `.sha256` file for each architecture's build, tests the new pin on all three platforms, and opens a pull request. Merging it publishes the new tag.

Bright Data's CDN keeps only the build its installer serves today, so a pinned build disappears from it soon after a new release. A device that already has the pinned build cached keeps running it. A new device, or one with an empty volume, would have nothing to download, so the entrypoint then falls back: it reads the version `install.sh` serves now (only if it is newer than the pin), checks that build against the CDN's `.sha256` file, runs it, and logs a warning on every start that it is not running the pinned build. Upgrade to the newer tag to get back onto a pinned hash.

The CDN's `.sha256` files are not signed. The pin catches a swapped or corrupt download from the moment it is recorded; it cannot prove who published the build.

Source: https://github.com/GeiserX/CashPilot/tree/main/images/earnapp
