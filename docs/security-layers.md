# Security layers

You decide how many layers protect your computer from the earners. Each layer
guards one thing. Stacked, they mean an attacker needs one separate escape per
layer.

The Fleet page shows the layers of each worker in its **Security layers** row.
For each earner it shows the layers that the earner really got. It says whether
the earner is fenced, and whether it runs under Docker's own runtime (Standard,
runc) or under gVisor.

| Layer | What it guards | Default | What it costs |
|---|---|---|---|
| Socket proxy | Docker on the host, from the worker: no privileged containers, no host folders, only CashPilot's own containers | On in the shipped compose files | Nothing |
| LAN fence | Your LAN, this host, your tailnet and cloud metadata, from each earner | On for new installs. An upgraded install turns it on with one click on the Fleet page | Nothing |
| gVisor | The host's kernel, from an earner that escapes its container | Off. You install it and choose it per earner | Throughput close to Standard, and about six times the CPU for the same traffic ([measured](home-network-security.md#what-it-costs)) |
| Secure VM | The host's kernel, files and passwords | Not available yet. The Fleet page shows whether the host has KVM, which it needs | RAM for the VM |

Nothing turns a layer on by itself. An upgrade offers a new layer and leaves your
earners as they are.

## The socket proxy

The worker never holds the raw Docker socket in the shipped compose files. It
talks to a proxy that refuses privileged containers, binds of `/` and of the
socket, and anything without CashPilot's owner label
([security defaults](security-defaults.md)). The Fleet page shows **Socket
proxy: off** for a worker that holds the raw socket, as the Unraid and TrueNAS
listings still do.

## The LAN fence

Earners sit on CashPilot's own network, `cashpilot-isolated`, behind firewall
rules that let them reach the internet and nothing else
([network isolation](isolation.md)). Each earner shows **fenced** or **not
fenced**.

## gVisor

gVisor runs each earner against a kernel written in user space, so a kernel bug
an earner exploits hits gVisor, not your host. It needs root on the host to
install, which the worker does not have and must not get. So the Fleet page
gives you one command to run on the host.

1. **Install.** Open the worker's **Security layers** row and copy the install
   command. It downloads the helper from this repository at your release's tag
   and checks its sha256 before it runs anything with `sudo`. The helper shows
   what it will change and asks before it does. It installs a pinned gVisor
   release, checked by sha512, in its own folder, and registers two runtimes in
   `/etc/docker/daemon.json` after a backup. Docker reloads its settings, so your
   running containers keep running.
2. **Check.** Press **Check gVisor**. The worker starts a short probe under each
   gVisor runtime, on the earners' network. Green needs gVisor's own kernel and a
   working name lookup. Red says which one failed.
3. **Choose.** Set **Runtime for earners you deploy here from now on**, or press
   **Run under gVisor** on one earner. A running earner is redeployed at once, and
   the page asks first.
4. **Undo.** Switch every earner back to Standard, then run the remove command.
   It restores `daemon.json`, deletes gVisor and its backup, reloads Docker and
   checks that nothing is left. It refuses while an earner still runs under
   gVisor.

Some earners cannot run under gVisor. The Fleet page locks their choice and says
why:

- **Mysterium** needs `iptables-nft` and kernel WireGuard, which gVisor does not
  have.
- **GPU miners** need the GPU, which gVisor cannot pass in.
- **Bitping** needs raw sockets. It gets the gVisor runtime registered with
  `--net-raw`, so it can run under gVisor.

An environment variable on the worker wins over the page:
`CASHPILOT_CONTAINER_RUNTIME` sets the runtime of every bridge-networked earner,
and `CASHPILOT_CONTAINER_RUNTIME_OVERRIDES` sets it per earner. The page shows
the choice locked and names the variable.

gVisor cannot run on Unraid at all, and Docker Desktop already runs every
container in a VM. The helper refuses both and says why.

## The Secure VM

A Secure VM runs the earners in a fenced VM on the same host, so an escape lands
in the VM, not on your computer. It is not available yet. The Fleet page shows
**KVM available** or **no KVM** for each worker, because the VM needs it.
