# The Secure VM on Linux

The Secure VM puts your earners inside a virtual machine on the same computer.
An earner that breaks out of its container then lands in the VM, not on your
host. The VM is fenced off your LAN, the host and your tailnet, so it reaches
the internet and nothing else.

It is one more layer, and it is off until you install it. There is one Secure
VM per computer, shared by every earner you put in it. Earners that reach each
other inside it do not matter. Reaching anything outside it does.

```
host
 └─ fence on the host (a network namespace the guest cannot change)
     └─ the Secure VM (QEMU/KVM, Debian 13)
         └─ the guest worker's own LAN fence
             └─ Docker, earners under gVisor (runsc)
                 └─ runc only for earners that need it (Mysterium)
```

The Secure VM is a CashPilot worker. The Fleet page shows it under its host as
"Secure VM on <host>". To put an earner in it, deploy that earner to the Secure
VM's worker. Both workers leave through the same public IP, so the egress
warning about shared IPs is still right.

## What you need

- An x86_64 Linux computer with KVM (`/dev/kvm`). Most home servers and
  desktops have it. Many VPS plans and some small boards do not. Without KVM
  the installer stops and says so. Use [gVisor](home-network-security.md#7-gvisor-optional)
  and the [LAN fence](isolation.md) there instead: neither needs a VM.
- systemd, or Unraid.
- Free memory for the guest and 512 MB for the host. The guest gets 2 GB by
  default.
- About 6 GB of free disk to start. The guest's disk grows as earners pull
  their images, up to 20 GB by default.
- A UI address the computer can reach over IPv4, the same one your workers use.

We tested it on Ubuntu 24.04, Debian 13, Fedora 45 and Rocky Linux 10 (both
with SELinux enforcing), Arch Linux and Unraid 7.4. The installer adds the
packages it needs (QEMU, `dosfstools`, `mtools`, `iptables`) through the
system's package manager.

## Install

The Fleet page shows one command for the host. It downloads `cashpilot-vm` from
the release your UI runs, checks it against a SHA-256, and runs it as root:

```bash
curl -fsSLo cashpilot-vm https://raw.githubusercontent.com/GeiserX/CashPilot/<release>/scripts/cashpilot-vm \
  && echo "<sha256>  cashpilot-vm" | sha256sum -c - \
  && sudo bash cashpilot-vm install --ui http://<ui-host>:8080 --host-worker <name> --ref <release>
```

It shows what it will do, asks once to continue, and asks for your fleet key
(the `CASHPILOT_API_KEY` your workers use). The key is never on the command
line, so it is not in your shell history. Then it:

1. Checks KVM, memory and disk, and stops with the numbers if one is short.
2. Downloads the Debian 13 cloud image, pinned by build, and checks its
   SHA-512 before the first boot.
3. Writes the fence and checks it.
4. Starts the guest. On its first boot the guest installs Docker, gVisor
   (pinned by release and SHA-512), the socket proxy and the CashPilot worker
   (its compose file pinned by SHA-256).
5. Waits for the worker to enrol with your UI.
6. Runs the self-test.

Options:

- `--ref TAG`: the release that the guest takes its compose file from. Give
  the same release as the script, because the script checks the file against
  its own SHA-256. The Fleet page's command already does.
- `--ram MB`: 1024 at least.
- `--cpus N` and `--disk GB`.
- `--port PORT`: the host port where the UI reaches the guest's worker. Without
  it, the first free port of 18081, 18091, 18181 and 28081. A port you give
  must be free, or the install stops.
- `--worker-url URL`: when the UI reaches this computer through NAT or a port
  forward.
- `--net 10.x.y`: when `10.213.0.0/29` is in use here.

## How the fence works

The guest's only network link is a tap device inside a network namespace of its
own, `cashpilot-vm`. A veth pair joins that namespace to the host. The fence
lives in the namespace.

A firewall reload on the host (`firewalld`, `ufw`, Docker starting) or an
`nft flush ruleset` acts on the host's own namespace, so it never touches the
fence. A reload can remove only what is on the host side: the NAT and the
forwarding rule for the veth. Without them the guest is offline. It is never on
the LAN.

The fence drops everything the guest sends to:

- private ranges: `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`
- `100.64.0.0/10`, carrier-grade NAT and every Tailscale address
- `169.254.0.0/16`, link-local and cloud metadata
- loopback, multicast and reserved ranges
- every address of the host itself, and any public subnet connected to it (a
  LAN numbered in public space, a VPS's neighbours)
- your home's own public IP. Most home routers loop a connection to their own
  public address back into the LAN (NAT loopback).

Two holes, both one TCP port on one address:

- The guest can open a connection to the UI's address and port, because its
  worker must report.
- The UI can open a connection to the guest's worker through one port on the
  host (18081). The guest sees those connections come from the namespace, never
  from the UI's own address.

The guest's replies on those connections pass as replies only. Every packet of
a connection that the guest opens itself goes through the drops. IPv6 is off in the namespace and in the guest. The
host also drops anything from the veth to the host itself, as a second layer.

Inside the guest the worker writes its own LAN fence for its earners, as on any
worker. Earners run under gVisor (`runsc` with network passthrough, see
[gVisor](home-network-security.md#7-gvisor-optional)). Docker's own default
runtime in the guest stays `runc`, because the worker's fence helper must
write rules into the guest's real kernel. Earners whose catalog entry needs
`runc` (Mysterium) get it, and Bitping gets the gVisor build with raw sockets.

## The guard

The guard runs at boot and every 60 seconds. It reads everything in the
namespace that decides where a packet can go: links, addresses, routing rules,
routes, sysctls and the whole ruleset. All of it must match what it recorded
when it wrote the fence, exactly.

- On any drift it takes the guest's link down at once, writes the fence again,
  reads it back, and brings the link up only on an exact match. If the link
  does not go down, the guard stops the guest.
- At boot the link starts down. The guard brings it up only after the fence
  reads back as written: the rules it wrote and no other rule in any table.
- When the host's addresses or your public IP change, the guard cuts the link,
  writes the new fence and reconnects. This takes well under a second.
- The guard looks up your public IP every 2 minutes. If every lookup fails, it
  keeps the last address for up to an hour. After that, and on an install where
  no lookup ever worked, the guest stays cut off, because the fence cannot drop
  an address it does not know.
- `verify --prove-red` holds the guard off while the fence is open. If that run
  dies, the next guard pass finds it gone and puts the fence back.

It logs each change to the journal (`journalctl -t cashpilot-vm`), or to syslog
on Unraid.

## Verify

```bash
sudo cashpilot-vm verify
```

The self-test runs probes from inside the guest. It checks:

- every address of the host, the namespace's gateway, your router and up to
  four other LAN devices, your tailnet's DNS and the metadata address: each must
  be blocked
- the UI's address and port: must be reachable
- the internet by name: must work
- gVisor is registered in the guest. The guest's own LAN fence is checked too,
  but it appears only with the first earner.

For each target, the self-test also runs a control from outside the fence. A
blocked probe proves the fence only when its control reaches the target. Then
the line says `ok`. When the control gets no answer either, the line says
`skip`: the target was not there to reach, so the probe proves nothing. The
fence drops packets without an answer. So any answer to the guest (a
connection, a refusal or an error) fails the test, and so does a target with no
result.

The Fleet page's self-test button runs the same checks, and the page shows the
result.

`--json` prints the result for scripts. `--prove-red` is for a throwaway test
host only. It opens the fence for one probe run, so you can see every target
turn red. Then it lets the guard put the fence back and runs again green.

## Status and remove

```bash
sudo cashpilot-vm status
sudo cashpilot-vm remove
```

`remove` asks the UI to forget the Secure VM's worker and stops the guest. Then
it deletes the guest, its disk, the image, the namespace and its links, the
host's firewall rules, the guard, the units and the service user. Last, it
checks that none of them is left, and says what is left if something is. When
the guest is stopped or cut off, it cannot ask the UI, so `remove` says so, and
you delete the worker on the Fleet page. A UI
that cannot forget a worker on request (3.0.x and older) gets no request.
`remove` then says so, and you delete the worker on the Fleet page.

## Unraid

Unraid cannot run gVisor on the host (see
[gVisor](home-network-security.md#7-gvisor-optional)), so the Secure VM is how
its earners get one more layer. It uses the QEMU that Unraid already ships, and
needs no VM Manager and no plugin. Unraid has no systemd, so `install` adds one
line to `/boot/config/go`. At each boot that line puts back the script and an
event hook. The hook starts the guest when the array is mounted, and stops it
before the array unmounts. The guard runs from a cron file in
`/boot/config/plugins/dynamix`, which Unraid reads itself. The guest's disk
lives in the `domains` share. When that share is set to stay on a pool
("only" or "prefer"), the disk is written straight to the pool. Otherwise it
goes through `/mnt/user`, so the mover can move it and the guest still finds it.

## What it costs

| | Measured |
|---|---|
| Host memory | 1.9 to 2 GB just after the first boot, which fills the guest's page cache. 580 to 810 MB after a restart, with one earner running. Never more than the guest's 2 GB. |
| Disk | 1.6 GB after the first boot: 330 MB for the Debian image and 1.3 GB for Docker, gVisor and the worker. 1.7 GB with one earner. |
| First boot | About 2 minutes on a physical host, for the whole install. 3 to 4 minutes when the host is itself a VM. |
