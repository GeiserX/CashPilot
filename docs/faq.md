# FAQ

**Is bandwidth sharing safe?**

Bandwidth sharing services generally route legitimate traffic (market research, ad verification, price comparison, content delivery) through your connection. That said, you are sharing your IP address, so review each service's terms of service and privacy policy carefully before signing up. Running these on a VPS rather than residential IP is an option for some services. **This is not legal advice -- consult with the particular services you intend to use and, if needed, seek independent legal counsel regarding your jurisdiction.**

**How much can I earn?**

Earnings vary widely based on location, ISP, number of devices, and which services you run. The dashboard tracks your actual earnings over time so you can optimize your setup. As a rough guide, and not a promise, one home server running 10 to 15 services makes about $30 to $100 a month, and it can make less, down to zero. More servers, or GPU compute, add to that.

**Can I run on a VPS or cloud server?**

Some services require a residential IP and will not pay (or will ban) VPS/datacenter IPs. The catalog lists "residential IP" under what they need. Services that work on VPS are a good way to scale up without additional home hardware.

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

The file always takes precedence over the environment variable, so setting `CASHPILOT_ENCRYPTION_KEY` on an instance that already has a key changes nothing and is safe. It is used only when no key file exists, which is exactly the restore case, and it is not written into `/data`. A key that decrypts none of the stored credentials stops the start, so a wrong value cannot slip through.

To keep the key out of the data folder for good, see [Encryption key outside the data folder](encryption-key.md).

If CashPilot cannot write the key to disk at all, because `/data` is unwritable or unmounted, it refuses to start rather than encrypting your credentials under a key that disappears on the next restart. Set `CASHPILOT_ALLOW_EPHEMERAL_KEY=true` if that is genuinely what you want.

<a id="forgot-password"></a>

### Forgot password or username

CashPilot has no e-mail reset. Whoever runs the server resets the password from the console of the CashPilot UI container. Your services, earnings and saved credentials are not affected: they are encrypted with `/data/.fernet_key`, not with your password.

The `python -m app.users` command needs CashPilot 2.3 or newer. On 2.2 or earlier it fails with `No module named app.users`. Update first: with Docker Compose, change the `drumsergio/cashpilot` and `drumsergio/cashpilot-worker` tags to `2.3` or newer (a pin such as `2.2` or `2.2.9` stays on that release), then run `docker compose up -d` ([Updating CashPilot](getting-started.md#updating-cashpilot)). On Unraid, update the container.

1. List the accounts. This also shows a username you forgot. Usernames are case-sensitive.

    ```bash
    docker exec -it cashpilot-ui python -m app.users list
    ```

2. Set a new random password for the account. Replace `alice` with the username from step 1.

    ```bash
    docker exec -it cashpilot-ui python -m app.users reset-password alice
    ```

    With exactly one owner you can leave the username out, and the command resets that owner. If the username starts with `-`, put `--` before it: `reset-password -- -alice`.

    The command prints the new password once.

3. If someone else may have had access to the account, restart the UI container now (`docker restart cashpilot-ui`). Browsers that were still signed in as that user are signed out only after a restart. If you only forgot the password, the restart is optional.
4. Sign in with the new password, then change it from the avatar menu (top right), **Change password**.

The container name depends on how you installed CashPilot:

| Install | UI container |
|---|---|
| `docker-compose.yml`, CasaOS | `cashpilot-ui` |
| Unraid | `cashpilot` (`docker exec -it cashpilot python -m app.users list`) |
| Runtipi | a generated name; `docker ps` shows it |

Portainer, Unraid and CasaOS also have a console button for a container. The command needs no terminal input, so it works there too.

To change a username:

```bash
docker exec -it cashpilot-ui python -m app.users rename OLD NEW
```

The new name follows the registration rule: 3 to 32 letters, digits, `_` or `-`. Sign out and back in to see it.

**After a suspected compromise**, for example a lost backup that holds `/data/.secret_key`, a password reset alone is not enough. Whoever has that key can sign a valid login cookie, and a reset does not stop it. Replace the key, then restart the UI container. The `&&` restarts it only when the new key is in place; if the command prints an error, fix that first:

```bash
docker exec cashpilot-ui python -m app.users rotate-session-key && docker restart cashpilot-ui
```

After the restart every browser is signed out, and everyone signs in again with their password. Saved credentials are not affected. If you set `CASHPILOT_SECRET_KEY` yourself, the command refuses: put a new random value in that variable and recreate the container instead. A `docker run` from the image does not see that variable and cannot refuse, so use `docker exec` on the UI container.

A new key ends forged cookies, but not what the attacker did while they were in. Two more steps:

1. Run `docker exec cashpilot-ui python -m app.users list`. Delete any account you do not recognise from the dashboard.
2. If the lost copy held all of `/data`, change the passwords of your provider accounts. `.fernet_key` and `cashpilot.db` together decrypt every saved credential.

If you later restore a backup taken before the rotation, leave out its `.secret_key` ([Backup and restore](backup-restore.md#restore)), or rotate and restart again. Otherwise the old key comes back. The restored database also brings back the accounts and passwords it held, so repeat the account check and any password reset.

**If the UI container does not start**, run the command from the same image against the same data. First find the host folder that holds the UI's `/data`. This works for a stopped container, and for a named volume as well as a bind mount (Unraid, CasaOS, Runtipi):

```bash
docker inspect -f '{{range .Mounts}}{{if eq .Destination "/data"}}{{.Source}}{{end}}{{end}}' cashpilot-ui
```

Then mount that folder and use the image tag you run:

```bash
docker run --rm -v "<folder>:/data" --entrypoint python drumsergio/cashpilot:<same tag> -m app.users list
```

Check that the list shows your accounts, then run the same line with `reset-password alice` in place of `list`.

A path with no database gives a "no database" error, and the command creates and changes nothing there. Docker may still leave an empty folder or volume with that name behind; remove it.

**Do not** delete the data volume: that erases `/data/.fernet_key` and with it every saved credential. **Do not** delete rows from the `users` table either.

**How do I remove CashPilot completely?**

`docker compose down -v` removes only CashPilot's own containers. The services it deployed keep running, and their data, the fenced network and a firewall table stay. [Removing CashPilot completely](uninstall.md) removes all of it, says what is lost for good, and shows how to check that nothing is left.

**What about security?**

Every service CashPilot deploys runs in its own container with every Linux capability dropped (a few services add back only the ones they declare) and `--security-opt no-new-privileges` set, so a process inside cannot gain privileges. Containers cannot see your host filesystem beyond the volumes a service declares. On a new install the worker also fences them off your LAN, the host, your tailnet and cloud metadata, so they reach the internet and nothing local ([Network isolation](isolation.md)). On Podman the fence is not available: earners run on Podman's default network, which can reach your LAN, and the Fleet page says so ([Network isolation](isolation.md) lists the options). An install upgraded from a release before 1.70 keeps its earners on Docker's default bridge, which can reach your LAN, until you click **Turn on isolation** on the Fleet page. Since 2.0.7 Mysterium runs behind the fence too; a node deployed through 2.0.6 stays on the host's network until you redeploy it ([Moving your Mysterium node behind the fence](mysterium-fence.md)). [Protecting your home network](home-network-security.md) covers firewalling your own bridge instead. Service credentials are encrypted at rest using Fernet symmetric encryption. The UI has no Docker access. With the shipped compose files the worker is never given the raw Docker socket: it reaches Docker through `cashpilot-socket-proxy`, which refuses privileged containers and binds of `/` or the socket (unless you put one of them, or a folder above the socket, in `CASHPILOT_PROXY_BIND_MOUNTS` or `CASHPILOT_COMPOSE_DIR`: the proxy takes those as given), and limits the worker to containers, volumes and networks with its owner label ([security defaults](security-defaults.md)). The Unraid templates and the TrueNAS app still mount the raw socket in the worker, which is root on the host ([app stores](app-stores.md)).

That said, no setup is bulletproof. You are still running third-party software that routes external traffic through your network. Docker isolation significantly reduces the attack surface compared to running these services directly on your host, but it does not eliminate all risk. We recommend running CashPilot on a dedicated machine or VLAN, keeping Docker and your host OS up to date, and reviewing the open-source code of any service before deploying it.

**What happens if a service container crashes?**

CashPilot monitors container health continuously. If a service container exits unexpectedly, it is automatically restarted. The dashboard shows uptime and health status for every running service.

**My Mysterium node will not start after a redeploy. Why?**

The most common cause is a port in its UDP range that another program on the host already holds. Docker must reserve every port in the range, so one busy port stops the start. [Choosing the UDP port range](mysterium-fence.md#choosing-the-udp-port-range) explains how to pick a range that stays free.

**My proxied copy is running but earns nothing. Why?**

The proxy may refuse to connect to that earner's servers, or allow only ports 80 and 443. CashPilot's **Test** checks only that the proxy reaches the internet. [Probe an earner's servers through the proxy](proxies.md#probe-an-earners-servers-through-the-proxy) shows how to check the earner's own host and port.

**Which services are heavy, and where should they run?**

Storage nodes, relays and VPN exits, and GPU work use the most. [Budgeting a small box](fleet.md#budgeting-a-small-box) lists them and shows how to measure each container before you decide.

<a id="worker-lost-docker"></a>

### The worker lost Docker after a Docker update

**What you see.** The worker stays online on the Fleet page, but CashPilot cannot start, stop or update its containers. The Fleet page shows **Docker unreachable** next to the worker. After 10 minutes the worker's healthcheck fails (`docker ps` shows the worker as `unhealthy`). After 30 minutes the bell and your notifications say that the worker cannot reach Docker. `docker logs cashpilot-socket-proxy` shows `upstream Docker socket unreachable`, and with a current compose file `docker ps` shows the proxy as `unhealthy` within about 3 minutes. Your earners keep running.

**Cause.** The shipped compose files bind the socket file `/var/run/docker.sock` into `cashpilot-socket-proxy`. A file bind holds that one file. A Docker update (for example `unattended-upgrades` installing a new `docker-ce`) restarts Docker, and Docker makes a new socket file at the same path. With Docker's live-restore on, the proxy keeps running through that restart and keeps the old file. Nothing answers on the old file.

**Quick fix.** On that machine, restart the proxy:

```bash
docker restart cashpilot-socket-proxy
```

The restart binds the new socket, and the worker finds Docker again at its next heartbeat. You do not have to restart the worker. On Unraid and TrueNAS the worker holds the socket itself, so restart the worker.

**Lasting fix.** Bind the socket's folder, not the socket file. A folder bind shows a replaced socket at once. In the `cashpilot-socket-proxy` service of your compose file, replace the line `- /var/run/docker.sock:/var/run/docker.sock:ro` with the bind below, and add the `SOCKGUARD_UPSTREAM_SOCKET` line to its `environment`:

```yaml
    volumes:
      - type: bind
        source: /var/run
        target: /host-run
        read_only: true
        bind:
          recursive: disabled
      - cashpilot_docker_api:/run/cashpilot-docker
    environment:
      # Keep the lines that are already there, and add this one:
      - SOCKGUARD_UPSTREAM_SOCKET=/host-run/docker.sock
```

Then run `docker compose up -d`. The same change works in `docker-compose.worker.yml` and `docker-compose.fleet.yml`. Compose reads those files only when you name them, so run `docker compose -f docker-compose.worker.yml up -d` or `docker compose -f docker-compose.fleet.yml up -d`, unless `COMPOSE_FILE` already names the file.

- `recursive: disabled` is necessary. `/var/run` holds other mounts, for example Docker's network namespaces under `/run/docker/netns` and `/run/user/...`. A recursive bind brings them all into the proxy. A non-recursive bind shows only the folder itself.
- `SOCKGUARD_UPSTREAM_SOCKET` sends the proxy to the new path. The policy block and its fingerprint stay as they are, because the environment variable overrides `upstream.socket` in the policy. Without the variable the proxy does not start (`upstream socket not found (/var/run/docker.sock)`).
- `cashpilot-migrate` can keep its file bind. It starts again at every `docker compose up`, so it always gets the current socket. If you give it the same folder bind, add `DOCKER_HOST=unix:///host-run/docker.sock` to its `environment`. Worker 2.8.4 and later read that variable. Never point it at the proxy's socket: the migrator needs the host's own.
- The folder bind gives the proxy every socket in `/var/run`, not only Docker's. On a typical server that includes systemd's own socket, D-Bus, and the sockets of tools such as Tailscale or snapd. `read_only` does not stop a program from connecting to a socket, and the proxy runs as root. Access to the Docker socket already gives root on the host, so a compromised proxy gains little that it did not have. If you want the proxy to hold only the Docker socket, keep the file bind and restart the proxy after a Docker update: the alert above tells you when.
- It needs Docker Compose 2.30.0 or newer. Older releases refuse the whole file with `Additional property recursive is not allowed`. Run `docker compose version` to check. Debian 13 packages Compose 2.26.1, so on Debian install Compose from Docker's own repository. The in-app update uses its own Compose 2.33, so it reads the changed file.
- It works only on Linux. Docker Desktop on macOS and Windows maps only `/var/run/docker.sock` into its virtual machine. There, `/var/run` is a folder on your Mac or PC, with no Docker socket in it.
- With rootless Docker the socket is in `/run/user/<your uid>`, which is a separate mount. Use that folder as `source`.
- On Podman, keep the file bind. We have not tested the folder bind there.

The shipped files keep the file bind, because the folder bind needs Compose 2.30 and Linux, and CashPilot also supports older Compose releases and Docker Desktop. A newer compose file that you download does not have your change, so make it again after you replace the file.
