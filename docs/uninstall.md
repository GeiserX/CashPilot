# Removing CashPilot completely

This page removes CashPilot and everything it created on a machine, so that a new install starts clean. Use it to reset a test instance, or to leave for good.

`docker compose down -v` is not enough on its own. It removes only CashPilot's own containers and their volumes. The services CashPilot deployed (the earners) keep running and earning. Their data, the fenced network and a firewall table also stay on the machine. The steps below remove those too.

Every command selects CashPilot's objects by their CashPilot labels or exact names. Nothing here prunes Docker, so your other containers, volumes and images are not touched.

The page assumes one CashPilot per Docker host. The label commands remove every CashPilot object on that host, so on a host with two installs they remove both. Run it only where the compose file holds CashPilot alone. If you merged CashPilot's services into a bigger compose file, step 2 and step 7 also remove your other services, their volumes and that file.

---

## Before you start

Removal deletes data that nothing can bring back. Decide first what you keep.

| Lost for good | What it means | Keep it with |
|---|---|---|
| Node identities: `mysterium-data`, `anon-data`, `proxybase-data`, `sia-hostd-data`, the Storj identity folder | The node's reputation, its unsettled earnings, and for ProxyBase and Sia the wallet. A new node starts from zero. | [Backing up node identities](backup.md) |
| The UI's `/data`: `cashpilot.db` and `.fernet_key` | The earnings history, the users and every saved credential | [Backing up and restoring](backup-restore.md) |

**Leaving for good.** Cash out each provider first: your balance stays at the provider, not in CashPilot. Storj pays the held-back amount only after a graceful exit ([Storj](guides/storj.md)). Sia keeps your collateral locked until the contracts end ([Sia](guides/sia-hostd.md)). Anyone keeps each relay's stake locked for its 180 days, so claim the rewards in your wallet first ([Anyone](guides/anyone-protocol.md)). The ProxyBase wallet lives in `proxybase-data`: save the mnemonic from the container's first-start logs, or back up the volume ([ProxyBase](guides/proxybase-xyz.md)).

**Starting fresh for a test.** Nothing above matters on a test instance. Run every step.

**Starting fresh but keeping your nodes.** Back up the identities, or keep their volumes. Step 5 shows the list of volumes, and you delete the lines you want to keep.

---

## Remove a standard install

This is for an install from `docker-compose.yml` ([Getting started](getting-started.md)). Run it on the machine itself, in a Linux or macOS shell (on Windows, in WSL). On macOS, type `bash` first: zsh, the default shell there, does not treat the `#` lines in the blocks as comments.

Go to the folder that holds `docker-compose.yml`. If you started CashPilot with `docker compose -p <name>`, or from a folder with another name, run `export COMPOSE_PROJECT_NAME=<name>` first. `docker compose ls` shows the name. Without it, step 2 finds nothing and still reports no error.

Paste steps 1 to 5 in one go, because steps 3 to 5 use values that step 1 sets.

```bash
cd /path/to/cashpilot

# 1. Write down what CashPilot's services use, before anything is removed.
docker ps -aq --filter label=cashpilot.managed=true > cashpilot-containers.txt
xargs -r docker inspect -f '{{range .Mounts}}{{if eq .Type "volume"}}{{println .Name}}{{end}}{{end}}' < cashpilot-containers.txt | grep -Ev '^([0-9a-f]{64})?$' > cashpilot-volumes.txt
xargs -r docker inspect -f '{{range .Mounts}}{{if eq .Type "bind"}}{{println .Source}}{{end}}{{end}}' < cashpilot-containers.txt | grep -v '^$' | sort -u > cashpilot-folders.txt
xargs -r docker inspect -f '{{.Config.Image}}' < cashpilot-containers.txt > cashpilot-images.txt
docker compose config --images >> cashpilot-images.txt
project=$(docker compose config | sed -n 's/^name: //p')
worker_image=$(docker compose config --images | grep -m 1 cashpilot-worker)

# 2. Stop CashPilot. This removes its own containers, volumes and network.
docker compose down -v

# 3. Stop the services, then remove them and any helper container left over.
xargs -r docker stop < cashpilot-containers.txt
for label in cashpilot.managed cashpilot.probe cashpilot.updater cashpilot.migrate; do
  docker ps -aq --filter label=$label
done | sort -u | xargs -r docker rm -fv

# 4. Remove the LAN fence: its network and its firewall tables.
docker network ls -q --filter label=cashpilot.isolation=managed | xargs -r docker network rm
docker network ls -q --filter label=cashpilot.deployed-by=worker | xargs -r docker network rm
for family in ip ip6; do
  docker run --rm --network host --user 0:0 --cap-add NET_ADMIN --entrypoint nft "$worker_image" delete table $family cashpilot
done

# 5. List the volumes that are left.
docker volume ls -q --filter label=cashpilot.deployed-by=worker >> cashpilot-volumes.txt
docker volume ls -q --filter label=cashpilot.backup-of >> cashpilot-volumes.txt
docker volume ls -q --filter label=com.docker.compose.project=$project >> cashpilot-volumes.txt
sort -u -o cashpilot-volumes.txt cashpilot-volumes.txt
cat cashpilot-volumes.txt
```

What the steps do:

- Step 1 saves the services' containers, volumes, host folders and images to files. After a container is gone, nothing links its volumes and images to CashPilot any more.
- Step 3 gives each service the stop time CashPilot set for it, 5 minutes for Storj. Storage nodes need that time: a forced stop makes Storj report an unclean shutdown.
- Step 4 stops the services' traffic rules. If a line says `No such file or directory`, that table was not there, and you can ignore it. On a host without nftables, step 4 removes only the network. A restart of the machine clears the rest ([Check that nothing is left](#check-that-nothing-is-left)).
- Step 5 prints every volume step 6 will delete. Read it now. It includes node identities such as `mysterium-data`, and the `-pre-isolation` copies of them that an upgrade made. To keep a volume, delete its line from `cashpilot-volumes.txt`.

Then remove the volumes and the images:

```bash
# 6. Remove the volumes and the images.
xargs -r docker volume rm < cashpilot-volumes.txt
sort -u cashpilot-images.txt | xargs -r docker image rm
```

Docker refuses to remove an image that another container still uses, and prints `conflict: unable to delete`. That image is shared with something else on the machine, so leave it.

The in-app updater also pulls `docker:27.5.1-cli`. Other programs use that image too, so remove it only if nothing else on the machine does.

Last, the files and folders. `cashpilot-folders.txt` lists the host folders the services used, such as the Storj or Sia storage. Read it, and delete only the folders you no longer want:

```bash
# 7. Remove the host folders you no longer want, then CashPilot's files.
cat cashpilot-folders.txt
sudo rm -rf cashpilot-migrate-state
rm -f "${COMPOSE_FILE:-docker-compose.yml}" .env cashpilot-containers.txt cashpilot-volumes.txt cashpilot-folders.txt cashpilot-images.txt
```

`cashpilot-migrate-state` belongs to root and holds a copy of the services' settings, credentials included. `.env` can hold your keys. If the folder holds nothing else, delete the folder itself.

!!! warning "Keep the old volumes and this folder together"
    If you kept `<project>_cashpilot_worker_data` or `<project>_cashpilot_fleet` in step 5, keep `cashpilot-migrate-state` too. Without the folder, the next install copies the old worker key and settings from those volumes into its new ones.

### If you built from source, or run the fleet file

Before step 1, tell `docker compose` which file you use, and every step then reads it:

```bash
export COMPOSE_FILE=docker-compose.fleet.yml   # or docker-compose.build.yml
```

Step 7 then deletes that file. On a source checkout, delete the whole checkout folder instead. A source build also leaves Docker's build cache. `docker builder prune` removes it, but it removes the cache of every other build on the machine too.

---

## Other ways to install

### A fleet: every machine runs its own uninstall

The **Remove** button on the **Fleet** page only deletes the worker from the dashboard's list. The machine keeps its containers, and its services keep running and earning. Run the steps on every machine that runs a worker.

On a machine that runs only a worker, set the file first, then run steps 1 to 7:

```bash
export COMPOSE_FILE=docker-compose.worker.yml
```

To reinstall one worker and keep the rest of the fleet, remove that worker on the **Fleet** page as well, so it enrols again with its new key.

### Unraid, CasaOS, Runtipi and TrueNAS

The app store installs keep their data in host folders, not in volumes. Change the steps like this:

- In step 1, leave out the three lines that call `docker compose`. Read the worker image from the worker container instead: `worker_image=$(docker inspect -f '{{.Config.Image}}' cashpilot-worker)`. On Runtipi the container has a generated name, and `docker ps` shows it.
- Replace step 2 with the platform's own removal: on Unraid, **Remove** on both the `cashpilot` and `cashpilot-worker` containers in the Docker tab. On CasaOS, Runtipi and TrueNAS, uninstall the app.
- Run steps 3 to 6 as written. In step 5, leave out the line with `com.docker.compose.project`.
- Step 6 then leaves the CashPilot images. The check below lists them. Remove each with `docker image rm <name>`.
- In step 7, delete the app's data folders instead of the compose files:

| Platform | Folders |
|---|---|
| Unraid | `/mnt/user/appdata/cashpilot` and `/mnt/user/appdata/cashpilot-worker` |
| CasaOS | `/DATA/AppData/cashpilot` |
| Runtipi | the `data` folder in the app's data folder (`app-data/cashpilot`) |
| TrueNAS | the storage you chose when you installed the app |

We have not checked whether each platform's uninstall deletes these folders. Look for them, and delete them if they are still there.

### A Portainer stack

Change the steps like this:

- In step 1, leave out the three lines that call `docker compose`. Set the project to the stack's name, `project=<stack name>`, and read the worker image as in the app store steps above.
- Replace step 2 with **Delete this stack** in Portainer.
- Run steps 3 to 6 as written. Step 5 then lists the stack's volumes too.
- Step 6 then leaves the CashPilot images. The check below lists them. Remove each with `docker image rm <name>`.

### Podman

The fence does not exist on Podman. Leave out the `for family` lines in step 4.

### Earners you started from an exported compose file

Those containers carry the same `cashpilot.managed=true` label, so step 1 and step 3 find and remove them too. Delete the exported compose file by hand.

---

## Check that nothing is left

Each command prints nothing on a clean machine:

```bash
docker ps -a --filter name=cashpilot --format '{{.Names}}'
docker ps -a --filter label=cashpilot.managed=true --format '{{.Names}}'
docker volume ls -q --filter name=cashpilot
docker volume ls -q --filter label=cashpilot.deployed-by=worker
docker volume ls -q --filter label=cashpilot.backup-of
docker network ls --filter name=cashpilot --format '{{.Name}}'
docker image ls --format '{{.Repository}}:{{.Tag}}' | grep -E 'drumsergio/cashpilot|codeswhat/sockguard'
docker volume ls -q | grep -xE 'mysterium-data|earnapp-data|bitping-data|urnetwork-data|proxybase-data|sia-hostd-data|anon-(data|config|run)'
```

If a line prints, remove that object by name: `docker rm -fv`, `docker volume rm`, `docker network rm` or `docker image rm`. Common cases are older CashPilot image tags from earlier updates and volumes from an install under another project name. Another is a service volume that an earlier removal from the dashboard kept. The last command lists the services' volumes by name, because the older ones carry no CashPilot label. Keep any you still want.

On Linux, check the firewall too. This also prints nothing on a clean machine:

```bash
sudo nft list tables 2>/dev/null | grep cashpilot
sudo iptables-legacy-save 2>/dev/null | grep -E 'CP6?-'
sudo ip6tables-legacy-save 2>/dev/null | grep -E 'CP6?-'
```

On Docker Desktop and Colima, the firewall table lives in Docker's own virtual machine. Restarting Docker Desktop or Colima clears it.

A host without nftables gets `CP-` and `CP6-` chains instead of the table, and step 4 does not remove them. A restart of the machine clears the table and the chains. It also clears the `MYST` chains and `myst` or `wg` interfaces that a Mysterium node deployed through 2.0.6 may have left on the host. The exception is a host that saves its whole firewall to a file, for example with `netfilter-persistent save`: remove the `cashpilot`, `CP-`, `CP6-` and `MYST` lines from that file too.

---

## Things you may have added yourself

CashPilot does not create these. Some pages in these docs suggest them. Check only the ones you set up:

| What | Where it came from | How to check |
|---|---|---|
| Router port forwards for Mysterium, Storj, Sia or Anyone | the service guides | your router's port forwarding page |
| A daily update entry in cron | [Getting started](getting-started.md#automating-updates-optional) | `crontab -l` |
| Firewall rules for `cp-isolated`, and a boot hook that adds them (`earner-fence.service`, Unraid `go` file) | [Protecting your home network](home-network-security.md), [Test your isolation](isolation-check.md) | `sudo iptables -S DOCKER-USER`, `systemctl status earner-fence` |
| A reserved UDP port range for Mysterium | [Moving Mysterium behind the fence](mysterium-fence.md) | `grep -rn reserved_ports /etc/sysctl.conf /etc/sysctl.d/` |
| gVisor runtimes in `/etc/docker/daemon.json` | [Protecting your home network](home-network-security.md#7-gvisor-optional) | `docker info --format '{{json .Runtimes}}'` |
| A Tailscale auth key, tag and exit node for proxied copies | [Proxied copies](proxies.md#tailscale-exit-nodes) | the Tailscale admin console |
| A reverse proxy in front of the dashboard | your own setup | your proxy's configuration |

The reserved port list is shared with other programs. Remove only the Mysterium range from it.

---

## At the providers

Removing the containers does not remove anything at the providers. Each provider keeps your account, your balance and an offline device or node. Cash out first, then delete the offline devices in each provider's dashboard if you want a clean list. The [service guides](guides/index.md) link each provider's dashboard.
