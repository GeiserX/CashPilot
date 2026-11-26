# LAN miner readings

Fleet can show hashrate, temperature, power, best share difficulty and the active pool for miners on your network. Each reading comes from the worker that can reach the miner. The miner must already be running.

## Add a miner

Set `CASHPILOT_MINERS` on the worker to a comma-separated list of up to 64 addresses. Put it in the Compose `.env` file or in the advanced **LAN miners** setting on Unraid. Apply the change by recreating the worker.

```dotenv
CASHPILOT_MINERS=axeos://192.168.1.50,cgminer://192.168.1.51:4028
```

- `axeos://host[:port]` uses port 80 by default.
- `cgminer://host[:port]` uses port 4028 by default.
- Give each miner a DHCP reservation. You can also use a hostname that resolves only to private IPv4 or IPv6 addresses. The worker refuses public and link-local addresses, loopback and Tailscale addresses in `100.64.0.0/10`. URLs accept a host and optional port only.

Open **Fleet** and look under **Miners this worker reads**. The worker reads each miner about once a minute. A failed read shows the error. An offline worker or a reading older than three minutes shows when the last read finished. Only the owner can see the miner's pool username.

If you track a mining pool, use the readings as a starting point for its **Wall draw (W)** field under **Running costs**. Enter the total measured at the wall for every miner using that pool account. Bitaxe reports DC input at the board, before power-supply loss. Running costs use the value you save in the wall-draw field.

## Firmware support

| Firmware | Hashrate | Power and temperature |
| --- | --- | --- |
| Bitaxe with AxeOS | Current and, when available, one-hour average | DC power at the board, chip and regulator temperatures |
| NerdQaxe with an AxeOS-compatible API | Current and, when available, one-hour average | Board power and maximum chip temperature |
| Stock Antminer (bmminer) | Current and average | Neither field is available from the commands CashPilot uses |
| Whatsminer API v2 | Current and average when available | Power and temperature from the summary when available |
| Avalon | Average and any current reading the summary includes | CashPilot skips firmware-specific power and temperature fields |
| Braiins OS with legacy cgminer API | Current and average when available | CashPilot skips the tuner and authenticated APIs |

AxeOS serves `GET /api/system/info` on the local network. It can return HTTP 401 for a worker connecting from outside RFC1918, for example over Tailscale without a subnet router that rewrites the source.

For cgminer, enable `--api-listen` and allow the worker to connect. Use `--api-network` for network access and `--api-allow` to limit who can connect. Use read-only access and leave off the `W:` group. CashPilot sends only `summary` and `pools`. The worker displays an active pool only when the device identifies it as active.

On Whatsminer, enable the API in WhatsMinerTool. CashPilot supports the legacy v2 API. Whatsminer API v3 on port 4433 and Braiins APIs that require sign-in are outside this feature.
