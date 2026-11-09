# Moving your Mysterium node behind the fence

Through 2.0.6, CashPilot ran a [MystNodes](https://mystnodes.co/?referral_code=do7v7YOoBBpbOstKQovX2pUvZYKia4ZhH3QIdNtE)
node on the host's network. From 2.0.7 it runs in its own network namespace
on the fenced earner bridge, like every other earner, and the worker starts it
only once the LAN fence is confirmed. That is the `on` isolation mode. On a
network of your own (`CASHPILOT_CONTAINER_NETWORK`) CashPilot writes and checks
no fence, so your firewall rules, tested from inside the node, are what keep it
off your LAN.
[Mysterium on the fenced bridge](isolation.md#mysterium-on-the-fenced-bridge)
explains why and how. This page is the step-by-step move for a node you
already run, and how to prove afterwards that it worked.

A node deployed through 2.0.6 keeps running exactly as it is until you
redeploy it. Nothing moves on its own, so you choose when.

## What changes for the node

- It leaves the host's network and joins `cashpilot-isolated`. Its `NET_ADMIN`
  then reaches only its own namespace, and the host's fence drops anything it
  sends to your LAN, the host, a tailnet or cloud metadata.
- Its UDP range (`UDP_PORTS`) is published 1:1 on the host, so the forward on
  your router stays the same, as long as the range does. A node deployed
  before CashPilot set `UDP_PORTS` comes back on the catalog's default range,
  not the ports it used before: after the redeploy, run
  `docker inspect cashpilot-mysterium --format '{{range .Config.Env}}{{println .}}{{end}}' | grep UDP_PORTS`
  and make the router forward match that range. Read [Choosing the UDP port range](#choosing-the-udp-port-range)
  before you redeploy: on the host's network a busy port was skipped; now a
  busy port stops the whole start.
- Docker never starts it by itself. The worker starts it once it has read the
  fence back complete, and a guard stops it within 30 seconds if a fence rule
  goes missing or the container's shape changes.
- On a redeploy of a running node, the worker reads the node's identity before
  it removes the old container and again from the new one. If they differ,
  the new node is kept stopped.
- UPnP no longer works for it, since the fence drops your router. Forward the
  range by hand.

## Before you start

### 1. Back up the keystore

The node's identity lives in its data volume. If a redeploy ever comes up on
an empty volume, it creates a new identity, and the old one's reputation and
unsettled earnings stay with the old keys. The identity check above refuses
to replace a running node whose identity it cannot read, but a node that is
already stopped is replaced without the check. Take a backup first:
[Backing up node identities](backup.md).

### 2. Write down the current identity

On the machine running the node:

```bash
docker exec cashpilot-mysterium wget -qO- http://127.0.0.1:4050/identities
```

Keep the `0x...` address it prints. You compare against it after the move.

### 3. Check the isolation mode

The node runs only in two modes:

| Mode | Where the node runs |
|---|---|
| `on` | behind CashPilot's fence, on `cashpilot-isolated` |
| your own network (`CASHPILOT_CONTAINER_NETWORK` set) | on your network. CashPilot writes no fence there, so your firewall rules are the only thing keeping it off your LAN |

In any other mode the worker refuses the deploy before it touches the running
node, and the message says what to do:

| The message ends with | What to do |
|---|---|
| "isolation is legacy on this worker ... Switch isolation on in Fleet, then redeploy MystNodes." | On the **Fleet** page, press **Turn on isolation** for that worker. |
| "isolation is off on this worker ... Set CASHPILOT_ISOLATION=auto on this worker and restart it, then redeploy MystNodes." | Change the worker's environment and recreate the worker. |
| "isolation is unsupported on this worker ... Run it on Docker with isolation on, or on your own network (CASHPILOT_CONTAINER_NETWORK)." | The worker runs on Podman, which CashPilot cannot fence. Move the node to a Docker host, or bring your own network and rules. |

The Fleet page shows each worker's mode. [Modes](isolation.md#modes) has the
full table.

### 4. Upgrade the UI and the worker

Both, and the worker that runs Mysterium in particular. The dashboard refuses
to redeploy Mysterium onto an older worker.

### 5. Check how you reach the WebUI

On a Docker engine older than 28.0, a port published on `127.0.0.1` can still
be reached by other machines on the same LAN segment, so upgrade Docker or
block port 4449 with a `DOCKER-USER` rule first (`docker version` shows the
engine). If `UI_ADDRESS` holds only `127.0.0.1` on Docker 28.0 or later, skip
the rest of this step. If it holds a LAN address
for a reverse proxy on another machine, know that after the move port 4449 is
published through Docker's forwarding, so a host `INPUT` rule no longer limits
who reaches it. Before you move, either add a `DOCKER-USER` rule, or move the
proxy to the same machine and also take the LAN address out of `UI_ADDRESS`
in the deploy form (enter `localhost` for loopback only). Moving the proxy
alone leaves the LAN address published
([WebUI address](guides/mysterium.md#webui-address)).

### 6. Check the UDP range is free

See [Choosing the UDP port range](#choosing-the-udp-port-range) below. One port
in the range held by another program on the host is enough to stop the node
from starting.

## Move it

On the **Fleet** page, a node still on the host's network shows under its
worker with a **Redeploy MystNodes to move behind the fence** button. Press
it, or redeploy Mysterium on that machine from the dashboard; both do the
same. With isolation off, the page says to switch it on first. The node keeps
its data volume, so it keeps its identity and its earnings.

If the running node does not answer when the worker reads its identity, the
move is refused and the old container is left as it was: "its identity could
not be read from the running node ... Try again in a minute." A node that is
broken for good can be stopped from the dashboard first; a stopped node is
replaced without the check, so have your backup ready.

The
[upgrade notes](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md)
cover the same move, including going back to 2.0.6.

## Check that it worked

### Same identity

```bash
docker exec cashpilot-mysterium wget -qO- http://127.0.0.1:4050/identities
```

It must print the address you wrote down. If the worker saw a different one,
it stops the node and the Fleet page says why: "its identity is ..., not ...
as before the redeploy, so it is not running on the data volume that holds
its keystore". Restore the volume from your backup, then redeploy.

### Check isolation is clean

On the **Fleet** page, press **Check isolation** on the worker. It should
read **Isolated**, with no line about containers that "hold firewall
capabilities in this host's own network namespace". That line means a
Mysterium container is still on the host's network. [Reading the result](isolation.md#reading-the-result)
explains each line.

### Probe from inside the node

The node's own namespace should reach the internet and Mysterium's broker,
and nothing on your LAN. A target nothing listens on reads blocked with or
without a fence, so first pick targets that answer from the host itself: your
router's web page, another machine's SSH, a NAS share. Replace the addresses
below with yours.

```bash
# Control, from the host: each LAN target here must answer.
T='192.168.1.1:80 192.168.1.20:22'
for t in $T; do nc -z -w 3 ${t%:*} ${t#*:} && echo "host reaches $t" || echo "host cannot reach $t"; done

# From inside the node: each of the same targets must be blocked.
docker exec cashpilot-mysterium sh -c 'for t in 192.168.1.1:80 192.168.1.20:22; do
  nc -z -w 3 ${t%:*} ${t#*:} && echo "REACHED $t" || echo "blocked $t"; done'

# From inside the node: the internet and the broker must work.
docker exec cashpilot-mysterium nc -z -w 5 1.1.1.1 443 && echo "internet ok"
docker exec cashpilot-mysterium nc -z -w 5 broker.mysterium.network 4222 && echo "broker port reachable"
```

The broker line proves only that the TCP port answers, not that the node's
session with the broker works; the node's log shows that. Only a target the
host reached counts. A `REACHED` line from inside the node
means the fence is not doing its job on that path: run **Check isolation** and
follow its fix. [Test your isolation](isolation-check.md#mysterium) has a
version of this probe that runs in a separate container with no capabilities,
and how to read the fence's drop counters.

### The node can reach its forwarded ports

Each session first tries the forwarded range. The node checks those ports
from outside and logs the result:

```bash
docker logs cashpilot-mysterium 2>&1 | grep -E 'All ports .* are reachable|Failed to check manual ports' | tail -5
```

`All ports [<port> <port>] are reachable`, with ports from your range, means the router forward
works for the ports listed. The node checks only the ports it picked for that
session, not the whole range, so a forward that covers part of the range can
pass here while other sessions fail: check that the router rule covers the
whole range. `Failed to check manual ports ... globally` means the forward does
not work. Both lines appear only when a session starts, so wait for some
traffic.
[Port forwarding](guides/mysterium.md#port-forwarding) in the MystNodes guide
has the per-session count and the dashboard check that flags a node whose
sessions never connect directly.

## If the node does not start

- **The Fleet page says the node is held stopped.** The worker could not read
  the fence back complete, or the container changed shape (privileged, a
  capability or image its catalog entry does not give it, a restart policy, the
  wrong network). The message names which. For a missing fence rule, the
  worker writes the fence again and starts the node on a later check once it
  reads complete. For a container that changed shape, redeploy the node from
  the dashboard.
- **"address already in use" on a UDP port.** Another program on the host
  holds a port in the range. In releases after 2.1.0 the worker puts the old node back and
  starts it again when Docker refuses the new one, so you keep earning while
  you pick a free range; on an older worker the old container is already
  gone. See the next section.
- **An identity mismatch.** See [Same identity](#same-identity).

## Choosing the UDP port range

### Why one busy port now matters

On the host's network, Mysterium picked ports from its range by itself and
skipped any port another program held. On the bridge, Docker publishes the
range for the node, and it must reserve every port in it. If one port is
held by any process on the host, the whole start fails.

Linux hands out ports from its ephemeral range to any program that opens a
socket without choosing a port: DNS lookups, discovery daemons, NAS management
tools. Your host's range is in:

```bash
cat /proc/sys/net/ipv4/ip_local_port_range
```

It is commonly `32768 60999`. A Mysterium range inside it can be free today and
taken by some program at random tomorrow, and the node then fails on its next
start.

### The rule

1. **Pick a range below the start of the ephemeral range**, so the kernel never
   gives those ports to anyone else. If you must stay inside it, reserve the
   ports so the kernel never hands them out. The setting is one list, and
   writing it replaces what is there, so read it first and add your range to
   it:

    ```bash
    sysctl net.ipv4.ip_local_reserved_ports        # empty, or e.g. 8080,9000-9010
    sudo sysctl -w net.ipv4.ip_local_reserved_ports='8080,9000-9010,<start>-<end>'
    ```

    Put the same full list in a file under `/etc/sysctl.d/` so it survives a
    reboot, and check no other sysctl file (`/etc/sysctl.conf`, `/run/sysctl.d/`,
    `/usr/local/lib/sysctl.d/`, `/usr/lib/sysctl.d/`, `/lib/sysctl.d/`) sets
    it too. After the next
    reboot, read the value again. On Unraid, `/etc` is
    rebuilt at every boot: add the `sysctl -w` line to `/boot/config/go`,
    above the line that starts `emhttp`, so it runs before Docker starts.
2. **Check nothing holds the range now**, before you deploy:

    ```bash
    sudo ss -uanp '( sport >= :<start> and sport <= :<end> )'
    ```

    No rows under the header means the range is free. Two holders are expected: an old
    node still on the host's network shows as `myst`, and its sockets close
    when the move stops it; a node already on the bridge shows as
    `docker-proxy`. A `docker-proxy` can also belong to another container,
    so check which one publishes the ports with
    `docker ps --format '{{.Names}} {{.Ports}}' | grep udp`. Any holder but
    the node you are moving means a different range.

3. **Keep it small.** Each session uses about two ports, so 20 to 30 ports
   carry 10 to 15 sessions at once, more than a home node usually gets. See the
   memory cost below.
4. **Forward the same range on the router**, UDP, external and internal ports
   the same, to the machine's fixed LAN address.
5. **Several hosts behind one public IP need one range each.** A router
   forwards a port to one LAN address only, so two nodes in one house cannot
   share a range. Give each host its own range with no overlap, and one
   forward per host. Separate ranges only stop the ports clashing. Whether a
   second node on the same public IP gets any traffic is up to Mysterium:
   read the warning in the [MystNodes guide](guides/mysterium.md) before you
   count on it.

The catalog's default range is the `UDP_PORTS` field in
[services/bandwidth/mysterium.yml](https://github.com/GeiserX/CashPilot/blob/main/services/bandwidth/mysterium.yml).
Compare it with your host's ephemeral range before you accept it; set your own
in the deploy form when they overlap.

### What each port costs

With Docker's default settings (the userland proxy on), Docker runs its port
proxy, `docker-proxy`, as a separate host process per
published port and address family, so a range published on IPv4 and IPv6 runs
two processes per port. These run on the host, outside the node's container,
so `docker stats` does not count them and the node's memory limit does not
cap them.

Measured with 101 ports: 205 processes. By resident memory that was about
2.3 MB per process, or about 460 MB in total. By proportional set size, which
splits pages the processes share, it was about 250 MB
([Limits](isolation.md#limits)). Either way the cost grows with every port. A
30-port range runs about 60 of these processes.

To see what they cost on your host (this counts every container's published
ports, not only Mysterium's):

```bash
ps -C docker-proxy -o rss= | awk '{s+=$1} END {printf "%d processes, %.0f MB resident\n", NR, s/1024}'
```

### Changing the range of a running node

The node can only use the range it was started with, and the router can only
send sessions to the range it forwards. Change both in this order, so the node
always has a working forward:

1. Add a router forward for the new range, next to the old one.
2. Set `UDP_PORTS` to the new range in the deploy form, and redeploy the node
   on that machine.
3. Confirm the node runs with the new range, then that sessions reach it.
   `docker inspect cashpilot-mysterium --format '{{range .Config.Env}}{{println .}}{{end}}' | grep UDP_PORTS`
   must print the new range. Then look for `All ports [...] are reachable`
   with ports from the new range in the node's log
   ([Port forwarding](guides/mysterium.md#port-forwarding)). A
   `Method:manual Success:true` line does not name the range, so it cannot
   tell the old forward from the new one.
4. Delete the old forward.

To go back to the catalog's default range, typing it in is not enough: the
form treats the prefilled default as untouched and keeps the range on record.
Removing the service from that machine and deploying it again clears the
record, but the new container mounts the catalog's `mysterium-data` volume, and
the identity check has no running node to compare with.

First stop the node with **Stop** on the dashboard, so nothing writes while you
copy, then copy its data off the container, whatever the checks below say.
`docker cp` works on a stopped container and reads through every mount, so the
copy holds the identity wherever it lives, and with it you can restore the node
if it comes back as a new one:

```bash
B=./mysterium-backup-$(date +%Y%m%d-%H%M%S)   # a new folder each time
docker cp cashpilot-mysterium:/var/lib/mysterium-node "$B" && ls "$B/keystore"
```

The `ls` must list the keystore's files. If it fails, stop here and press
**Start** on the dashboard to bring the node back as it was.

Then check where the node keeps its data:

```bash
docker inspect cashpilot-mysterium --format '{{range .Mounts}}{{.Type}} {{if eq .Type "volume"}}{{.Name}}{{else}}{{.Source}}{{end}} -> {{.Destination}}{{println}}{{end}}'
```

A fresh deploy mounts the volume named exactly `mysterium-data` at
`/var/lib/mysterium-node`, and nothing else there. A volume with any other
name, even one that contains it such as `project-mysterium-data`, is not the
one the node comes back on. This prints `catalog volume` only when the name
matches exactly:

```bash
docker inspect cashpilot-mysterium --format '{{range .Mounts}}{{if and (eq .Type "volume") (eq .Name "mysterium-data") (eq .Destination "/var/lib/mysterium-node")}}catalog volume{{end}}{{end}}'
```

If it prints `catalog volume` and the first command shows no other mount below
`/var/lib/mysterium-node`, remove the service with **Remove** on the dashboard
(it keeps the volume) and deploy it again on the same worker: each worker has
its own `mysterium-data`. Otherwise, removing the node would bring it back with
a new identity:

- **A host folder or another volume at that path or above it, or a mount
  below it.** Keep your own range: press **Start** on the dashboard to bring
  the node back as it was, without a redeploy. Or move the data onto
  `mysterium-data` by hand first, while no other container uses that volume.
- **No mount at or above that path.** The data is inside the container
  itself, and any redeploy or removal deletes it with the container. Move the
  backup onto `mysterium-data` before you change anything.
