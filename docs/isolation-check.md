# Test your isolation, and fix it on your platform

Bandwidth-sharing services carry other people's traffic. A buyer of residential
proxy access sends requests through your earner container, and that container
connects wherever the buyer asks. If it can reach your router, your NAS or the
machine it runs on, so can the buyer. A Mysterium node does the same thing for
VPN users.

So the goal is narrow: earners may reach the internet, and nothing else. Not
your LAN, not the host, not your VPN or overlay network (Tailscale, ZeroTier,
WireGuard), not cloud metadata.

[Protecting your home network](home-network-security.md) explains the rules for
a plain Linux Docker host. This page is about two things that page cannot do for
you: proving the rules work on *your* machine, and the platforms and setups
where the plain recipe does not hold.

## 1. Test it

The dashboard can run this test for you: **Check isolation** on the Fleet page
([how to read it](isolation.md#check-it-from-the-dashboard)). The manual steps
below do the same by hand.

Run this on the machine that runs the earners. It starts a small throwaway
container inside an earner's own network namespace, so it sees exactly what the
earner sees, and tries to open connections.

Edit `CHECKS` first. Each entry is an address on one of your networks with a
port you **know** is open: your router's web page, your NAS, the SSH port of the
Docker host itself, a device on your Tailscale network. A closed port proves
nothing, because it fails whether or not the firewall works.

```sh
# The earner to test. Any running earner container works.
TARGET=container:cashpilot-honeygain
# Addresses on YOUR networks, with a port you know is open. Edit these.
CHECKS="192.168.1.1:80 192.168.1.10:22 100.101.102.103:22"

docker run --rm --network "$TARGET" -e CHECKS="$CHECKS" alpine:3.22 sh -c '
  for c in $CHECKS 169.254.169.254:80; do
    if nc -z -w 3 "${c%:*}" "${c##*:}" 2>/dev/null; then echo "REACHABLE $c"; else echo "blocked   $c"; fi
  done
  if wget -q -T 8 -O /dev/null https://example.com; then echo "internet  works"; else echo "internet  FAILED"; fi
'
```

What you want to see: every check `blocked`, and `internet works`.

One line can read `REACHABLE` on a fenced host and still be fine:
`100.100.100.100:53`, Tailscale's DNS address. If you added the DNS rewrite from
the name-lookups paragraph under [With Tailscale on the host](#with-tailscale-or-another-overlay-network-on-the-host),
the host sends port 53 traffic to that address on to a public resolver before
the fence sees it, so the probe connects to `1.1.1.1`, not to Tailscale. Two
checks tell the rewrite apart from a missing fence, and neither can be fooled by
Tailscale's resolver forwarding the query to the same public server:

- The rewrite rule's packet counter goes up with the query. Read it, send one
  lookup from the earner, read it again:

  ```sh
  sudo iptables -t nat -L PREROUTING -v -n -x | grep 100.100.100.100
  docker run --rm --network "$TARGET" alpine:3.22 nslookup example.com 100.100.100.100
  sudo iptables -t nat -L PREROUTING -v -n -x | grep 100.100.100.100
  ```

- Every other port on that address stays `blocked`. `tailscaled` serves a status
  page on `100.100.100.100:80`, so add `100.100.100.100:80` to `CHECKS`: the
  control below reaches it, the fenced earner must not.

**Then run the control.** Change `TARGET` to `bridge` (Docker's default network,
which you have not fenced) and run it again. The addresses you put in `CHECKS`
should now say `REACHABLE`. If one still says `blocked`, its address or port is
wrong, and the first run told you nothing about it. Fix the list until the
control passes. The metadata address `169.254.169.254` stays `blocked` in both
runs unless the machine is a cloud server.

The same command works on every platform below, including Docker Desktop, a
Synology and Unraid. On a Linux host you can also enter the namespace directly,
with tools from the host:

```sh
PID=$(docker inspect -f '{{.State.Pid}}' cashpilot-honeygain)
sudo nsenter -t "$PID" -n curl -m 3 -sS http://192.168.1.1/
```

!!! note "Containers under gVisor"

    `--network container:` and `nsenter` both need the earner to use the kernel's
    network stack. Under `runsc-hostnet` it does, and the test works. Under plain
    `runsc` it does not; test from a probe container on the same network instead:
    `--network cashpilot-isolated`.

## 2. Fix it, by platform

### Plain Docker on Linux

Use the rules in
[Protecting your home network](home-network-security.md#2-firewall-the-containers-off-your-lan-and-the-host)
and run the test above. If the test passes and you have no VPN or overlay network
on the host, you are done.

### With Tailscale, or another overlay network, on the host

This is the case most guides get wrong, and we got wrong too.

Two separate problems:

- **Tailscale puts its own rule first.** `tailscaled` inserts its `ts-forward`
  chain at the top of `FORWARD` every time it starts, and that chain accepts
  anything leaving through `tailscale0`. Docker moves its `DOCKER-USER` jump back
  to the top when Docker starts. Whichever started last wins. When Tailscale
  wins, a `DOCKER-USER` rule never sees traffic headed for your tailnet or for
  the subnet routes it carries, and the earner reaches them. We found exactly
  this on a host where the plain recipe had been applied and looked correct.
- **The 100.64.0.0/10 range.** Tailscale addresses come from the carrier-grade
  NAT range, which is not one of the private ranges. Every rule list must name it.

The fix that does not depend on chain order is to drop the traffic in the
`mangle` table. Its `FORWARD` and `INPUT` chains run before the `filter` table,
and neither Docker nor Tailscale puts anything there.

```sh
#!/bin/sh
# Earners on the cp-isolated bridge reach the internet only. Safe to run again.
iptables -t mangle -N EARNER-FWD 2>/dev/null; iptables -t mangle -F EARNER-FWD
iptables -t mangle -A EARNER-FWD -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
for NET in 10.0.0.0/8 172.16.0.0/12 192.168.0.0/16 100.64.0.0/10 169.254.0.0/16; do
  iptables -t mangle -A EARNER-FWD -d "$NET" -j DROP
done
iptables -t mangle -N EARNER-IN 2>/dev/null; iptables -t mangle -F EARNER-IN
iptables -t mangle -A EARNER-IN -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
iptables -t mangle -A EARNER-IN -j DROP
iptables -t mangle -C FORWARD -i cp-isolated -j EARNER-FWD 2>/dev/null || iptables -t mangle -A FORWARD -i cp-isolated -j EARNER-FWD
iptables -t mangle -C INPUT -i cp-isolated -j EARNER-IN 2>/dev/null || iptables -t mangle -A INPUT -i cp-isolated -j EARNER-IN
```

- `EARNER-FWD` covers other machines, `EARNER-IN` covers the host itself.
- The `RELATED,ESTABLISHED` lines keep replies flowing, so ports you published
  (a Storj node, an Anyone relay) still answer.
- `-d` matches the address after Docker's port forwarding, so a port published on
  the host counts as private too.
- It drops instead of rejecting, because the `mangle` table cannot reject. That
  only matters for name lookups, below.
- It is IPv4 only. Docker bridges have IPv6 off unless you turned it on. If you
  did, add the same two chains with `ip6tables`, dropping `fc00::/7` (private
  addresses, Tailscale's included), `fe80::/10` and your LAN's own IPv6 prefix
  (`ip -6 route` shows it). We checked that those rules load, but tested the
  blocking only over IPv4.

**Name lookups.** Docker gives containers the host's DNS servers. With Tailscale,
that list often starts with `100.100.100.100`. Dropped, every lookup waits about
four seconds before Docker tries the next server; we measured exactly that. Two
ways out:

- Let CashPilot give earners public DNS servers. Containers it deploys onto
  `CASHPILOT_CONTAINER_NETWORK` get `1.1.1.1` and `9.9.9.9`
  ([details](home-network-security.md#name-lookups-need-a-resolver-the-rules-allow)).
  Containers deployed before you set it keep the old list until their next
  redeploy.
- Or send their Tailscale DNS queries to a public resolver, which also works for
  containers you cannot redeploy right now:

```sh
for PROTO in udp tcp; do
  R="-i cp-isolated -d 100.100.100.100 -p $PROTO --dport 53 -j DNAT --to-destination 1.1.1.1"
  iptables -t nat -C PREROUTING $R 2>/dev/null || iptables -t nat -I PREROUTING 1 $R
done
```

After either, the first lookup inside an earner should take tens of
milliseconds, not four seconds:

```sh
docker run --rm --network container:cashpilot-honeygain alpine:3.22 \
  sh -c 'time nslookup example.org >/dev/null'
```

The same applies to ZeroTier, Nebula, Netbird and a WireGuard VPN: find the
address range the overlay uses and add it to the list, then run the test with a
peer's address in `CHECKS`.

### Hosts with ufw

ufw does not filter container traffic. Docker forwards it before ufw's `INPUT`
rules run, which
[Docker's documentation](https://docs.docker.com/engine/network/packet-filtering-firewalls/)
states plainly. A host where `ufw status` looks strict can still let every
container reach the LAN. Use the rules above, outside ufw, and run them at boot
from a systemd unit ordered after `docker.service` (example below). Two more
things to check on such a host:

- **Rule files that flush.** If a script of yours flushes `DOCKER-USER` and
  rebuilds it, any isolation rule added by a different script disappears the
  next time the first one runs. Keep every rule for a chain in one script. The
  `mangle` rules above avoid this, since nothing else uses those chains.
- **A broad ufw allow.** A rule such as "allow 172.16.0.0/12 to port 8123" meant
  for one app also lets any container on a Docker bridge in that range reach the
  port. The `EARNER-IN` chain stops earners before ufw sees them.

A systemd unit that applies a script at boot:

```ini
# /etc/systemd/system/earner-fence.service
[Unit]
Description=Keep CashPilot earners off private networks
After=docker.service
Wants=docker.service

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/sbin/earner-fence.sh

[Install]
WantedBy=multi-user.target
```

`sudo systemctl enable --now earner-fence.service`, then run the test.

### Unraid

- **Where it persists.** Unraid rebuilds its root file system at every boot. Put
  the script on the flash drive, for example `/boot/config/earner-fence.sh`, and
  run it from `/boot/config/go` (`sh /boot/config/earner-fence.sh`) or from a
  User Scripts entry set to *At Startup of Array*. The `mangle` rules do not
  depend on Docker running first.
- **Two firewall backends.** Unraid's own `iptables` command uses the legacy
  backend. A container that manages the firewall itself, such as Mysterium,
  writes its rules with the `nf_tables` backend. Both are active, but
  `iptables -S` on the host only shows the legacy ones; read the others with
  `iptables-nft -S` and `iptables-nft -t nat -S`. Your rules in the legacy
  tables still apply to that traffic, and a drop in either backend wins.
- **Docker's default bridge.** Containers you started from Unraid's Docker tab
  often sit on `bridge` next to other apps, so you cannot fence that bridge
  without fencing them too. Move the earners to `cashpilot-isolated` instead:
  `docker network connect cashpilot-isolated <name>` then
  `docker network disconnect bridge <name>`. Published ports move with it.

### Synology and QNAP

Both run Docker on Linux with iptables, so the `mangle` script works the same
way. What differs is how it survives a reboot:

- **Synology DSM:** Control Panel, Task Scheduler, Create, Triggered Task,
  User-defined script, user `root`, event *Boot-up*, and the script's path under
  Task Settings
  ([Synology's Task Scheduler help](https://kb.synology.com/en-global/DSM/help/DSM/AdminCenter/system_taskscheduler)).
- **QNAP QTS:** call the script from `autorun.sh`, and turn on Control Panel,
  Hardware, General, *Run user defined startup processes (autorun.sh)*
  ([QNAP's guide](https://www.qnap.com/en/how-to/faq/article/running-your-own-application-at-startup)).

The NAS firewall in either web interface does not filter traffic between
containers and the LAN. Run the test after every DSM or QTS update, since an
update can replace Docker and its rules.

### Docker Desktop on Windows and macOS

Containers run inside a Linux virtual machine that Docker Desktop manages, and
their traffic leaves through the Docker Desktop process on your computer. The
firewall on Windows or macOS sees one application, not individual containers, so
there is no rule there that blocks an earner while leaving the rest of Docker
alone, and the VM's own firewall is not yours to keep.

What works here:

- Put the computer on a guest network or VLAN that cannot reach your other
  devices ([own network segment](home-network-security.md#1-give-it-its-own-network-segment)).
- Or run the earners on a small Linux VM or a separate device and apply the
  Linux recipe there.

The test in section 1 still works on Docker Desktop, so you can see what an
earner reaches before and after.

### Mysterium, which uses host networking

A Mysterium node runs with `network_mode: host`. Its customers' traffic does not
leave through a Docker bridge. It arrives through WireGuard interfaces named
`myst0`, `myst1` and so on, which exist only while a session is open, and the
host forwards it. Two layers apply.

**The node's own list.** Mysterium blocks some destinations for its customers
itself. Its default list is `10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16,
127.0.0.0/8`, which leaves out link-local addresses and the 100.64.0.0/10 range
that Tailscale uses. Since 1.46.0 CashPilot's catalog starts the node with the
full list, `--firewall.protected.networks=10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,100.64.0.0/10,169.254.0.0/16`.
A node deployed before that keeps the default list until you redeploy it from
the dashboard; the identity lives in its data volume and is kept. For a node
you run outside CashPilot, add the ranges in its config file
(`/var/lib/mysterium-node/config-mainnet.toml` inside the container) and
restart it:

```toml
[firewall.protected]
  networks = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,127.0.0.0/8,100.64.0.0/10,169.254.0.0/16"
```

The dashboard's **Check isolation** reads this list back from the node and says
when a range is missing. When the next customer connects, the node's NAT rules
should list the new ranges:

```sh
sudo iptables -t nat -S MYST | grep 240.0.0.1      # Unraid: iptables-nft -t nat -S MYST
```

**A host rule as a backstop.** The node's list only applies while the node is
running and configured. Add these lines to the end of the `mangle` script. The
script rebuilds `EARNER-IN` on every run, so the two DNS lines are added fresh
each time, just ahead of its final drop. They are the one exception: the node
answers its customers' DNS on port 11253 of the host (its `MYST` NAT chain shows
the redirect; check the port on your node).

```sh
iptables -t mangle -I EARNER-IN 2 -i myst+ -p udp --dport 11253 -j RETURN
iptables -t mangle -I EARNER-IN 2 -i myst+ -p tcp --dport 11253 -j RETURN
iptables -t mangle -C FORWARD -i myst+ -j EARNER-FWD 2>/dev/null || iptables -t mangle -A FORWARD -i myst+ -j EARNER-FWD
iptables -t mangle -C INPUT -i myst+ -j EARNER-IN 2>/dev/null || iptables -t mangle -A INPUT -i myst+ -j EARNER-IN
```

`myst+` matches every interface whose name starts with `myst`, including ones
created after the rule.

**Testing it without a paying customer.** You cannot open a Mysterium session to
your own node on demand, but you can build an interface that looks like one.
This needs root on a Linux host. It creates a network namespace behind an
interface named `mysttest0`, which `myst+` matches, gives it an address in
Mysterium's range, and tries your checks from inside. Replace `eth0` with the
interface your host reaches the internet through (`ip route get 1.1.1.1` shows
it). It removes everything it added when it exits.

```sh
#!/bin/bash
WAN=eth0
CHECKS="192.168.1.1:80 192.168.1.10:22 100.101.102.103:22"
cleanup() {
  ip netns del mysttest 2>/dev/null; ip link del mysttest0 2>/dev/null
  iptables -t nat -D POSTROUTING -s 10.182.250.0/24 -o "$WAN" -j MASQUERADE 2>/dev/null
  iptables -D FORWARD -s 10.182.250.0/24 -j ACCEPT 2>/dev/null
  iptables -D FORWARD -d 10.182.250.0/24 -j ACCEPT 2>/dev/null
}
trap cleanup EXIT
ip netns add mysttest
ip link add mysttest0 type veth peer name mt-peer
ip link set mt-peer netns mysttest
ip addr add 10.182.250.1/24 dev mysttest0; ip link set mysttest0 up
ip -n mysttest addr add 10.182.250.2/24 dev mt-peer
ip -n mysttest link set lo up; ip -n mysttest link set mt-peer up
ip -n mysttest route add default via 10.182.250.1
# What a real session gets from the node: forwarding and NAT to the internet.
iptables -A FORWARD -s 10.182.250.0/24 -j ACCEPT
iptables -A FORWARD -d 10.182.250.0/24 -j ACCEPT
iptables -t nat -I POSTROUTING -s 10.182.250.0/24 -o "$WAN" -j MASQUERADE
for c in $CHECKS; do
  if ip netns exec mysttest timeout 3 bash -c "</dev/tcp/${c%:*}/${c##*:}" 2>/dev/null
  then echo "REACHABLE $c"; else echo "blocked   $c"; fi
done
ip netns exec mysttest curl -sS -m 8 -o /dev/null -w "internet  %{http_code}\n" https://1.1.1.1/cdn-cgi/trace
iptables -t mangle -L EARNER-FWD -v -n | grep DROP
```

Every check should be `blocked`, the internet line should show `200`, and the
drop counters should go up. As a control, run it once with
`iptables -t mangle -I EARNER-FWD 1 -s 10.182.250.0/24 -j RETURN` added first:
the LAN checks should then be reachable. Then delete it, or test traffic keeps
skipping the fence:
`iptables -t mangle -D EARNER-FWD -s 10.182.250.0/24 -j RETURN`.

If you cannot run this, or the node runs somewhere you do not control, put the
whole machine on its own network segment. That covers Mysterium without relying
on any rule.

## 3. Keep it true

- **Run the test after every change** to the host: a Docker or Tailscale
  update, a new firewall tool, a NAS update, a reboot.
- **Run it after adding a service.** A new earner deployed onto Docker's default
  bridge instead of `cashpilot-isolated` is not covered.
- **Check both chain orders if you use Tailscale.** Restart `tailscaled`, then
  run the test again; that puts its chain first, which is the case that leaks.
