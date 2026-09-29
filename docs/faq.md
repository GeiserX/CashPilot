# FAQ

**Is bandwidth sharing safe?**

Bandwidth sharing services generally route legitimate traffic (market research, ad verification, price comparison, content delivery) through your connection. That said, you are sharing your IP address, so review each service's terms of service and privacy policy carefully before signing up. Running these on a VPS rather than residential IP is an option for some services. **This is not legal advice -- consult with the particular services you intend to use and, if needed, seek independent legal counsel regarding your jurisdiction.**

**How much can I earn?**

Earnings vary widely based on location, ISP, number of devices, and which services you run. The dashboard tracks your actual earnings over time so you can optimize your setup.

**Can I run on a VPS or cloud server?**

Some services require a residential IP and will not pay (or will ban) VPS/datacenter IPs. These are marked as "Residential Only" in the service catalog. Services that work on VPS are a good way to scale up without additional home hardware.

**How are credentials stored?**

All service credentials are encrypted at rest in the SQLite database using a Fernet key stored at `/data/.fernet_key`, which is generated automatically on first run. The database file lives in the mounted Docker volume (`cashpilot_data:/data`). No credentials are ever sent anywhere except to the service containers themselves.

Note that this is a different key from `CASHPILOT_SECRET_KEY`, which only signs login sessions.

### Backing up the encryption key

Your credentials are only as recoverable as `/data/.fernet_key`. If you lose that file you will have to re-enter every credential, because there is no way to decrypt the stored values without it.

```bash
# Back it up
docker exec cashpilot-ui cat /data/.fernet_key

# Restore onto a fresh volume: pass the saved value when starting CashPilot.
# It must reach the container, so put it on the same command line (or export it,
# or set it in your .env) - a bare shell assignment on its own line does nothing.
CASHPILOT_ENCRYPTION_KEY=<the value you saved> docker compose up -d
```

The file always takes precedence over the environment variable, so setting `CASHPILOT_ENCRYPTION_KEY` on an instance that already has a key changes nothing and is safe. It is adopted only when no key file exists, which is exactly the restore case.

If the key cannot be written to disk at all — an unwritable or unmounted `/data` — CashPilot refuses to start rather than encrypting your credentials under a key that disappears on the next restart. Set `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` if that is genuinely what you want.

**What about security?**

Every service CashPilot deploys runs in its own container with every Linux capability dropped (a few services add back only the ones they declare) and `--security-opt no-new-privileges` set, so a process inside cannot gain privileges. Containers cannot see your host filesystem beyond the volumes a service declares. They CAN reach your local network by default, because Docker does not block that; [Protecting Your Home Network](home-network-security.md) shows how to put them on a firewalled bridge that reaches the internet but not your LAN, router or host. That bridge does not cover a service on host networking (Mysterium, today); the guide says what to do about those. Service credentials are encrypted at rest using Fernet symmetric encryption. Only the worker container requires Docker socket access; the UI container has no privileged access.

That said, no setup is bulletproof. You are still running third-party software that routes external traffic through your network. Docker isolation significantly reduces the attack surface compared to running these services directly on your host, but it does not eliminate all risk. We recommend running CashPilot on a dedicated machine or VLAN, keeping Docker and your host OS up to date, and reviewing the open-source code of any service before deploying it.

**What happens if a service container crashes?**

CashPilot monitors container health continuously. If a service container exits unexpectedly, it is automatically restarted. The dashboard shows uptime and health status for every running service.
