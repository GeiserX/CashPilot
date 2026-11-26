# GPU services

Some catalog services need a GPU, such as a GPU miner. CashPilot gives that GPU
to that one container, and to no other. This page says what it passes in, what it
never does, and what your host needs first.

!!! warning "Beta"

    The GPU grant stays in beta until it runs on a real NVIDIA host.

## Who gets a GPU

A GPU goes only to a **catalog service whose entry declares `docker.gpu`**.
The worker uses its own catalog to check the grant and the image digest.
Update the worker if its catalog lacks the service or has a different grant.

- **A custom service never gets one.** An image you add yourself has not been
  reviewed ([custom services](custom-services.md)).
- **A proxied copy never gets one.** It lives inside its tunnel's network
  namespace ([proxied copies](proxies.md)).
- **One copy per machine.** Two copies would share the same GPU.
- **The worker sets `NVIDIA_VISIBLE_DEVICES=void`** when it creates a service
  container without an NVIDIA grant. CUDA base images set that variable to
  `all`. The worker's value hides the GPUs even on hosts whose default Docker
  runtime is `nvidia`.

## What CashPilot passes in

| Vendor | What the container gets |
|---|---|
| NVIDIA | One Docker device request: driver `nvidia`, capability `gpu`, one GPU or all of them, as the catalog entry says. The NVIDIA Container Toolkit on the host mounts the driver and the device nodes. |
| AMD | That vendor's DRM render node (`/dev/dri/renderD128` to `renderD135`), the first one or all of them. With ROCm, also `/dev/kfd`. |
| Intel | That vendor's render node, the same way. |

**What it never passes in:** a `card*` node (those control the display), a
whole `/dev/dri` folder or a GPU of another vendor. It also adds no extra
groups (`GroupAdd`), no privileged mode and no capability that the catalog
entry does not declare. The [socket proxy](security-defaults.md#docker-socket-proxy) refuses each of these
as well.

The worker finds the GPUs in sysfs (`/sys/bus/pci/devices` and
`/sys/class/drm`), which every container sees, so it needs no device of its
own. When sysfs shows no GPU of the service's vendor, the worker refuses the
deploy and says what it found. The running container is not touched.

## What your host needs

=== "NVIDIA"

    Install the
    [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html),
    then point Docker at it and restart Docker:

    ```sh
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
    ```

    Without it, Docker refuses the start with
    `could not select device driver "nvidia" with capabilities: [[gpu]]`.
    CashPilot then puts the running copy back and tells you to install the
    toolkit. Keep the toolkit up to date: its hook runs as root on the host each
    time a GPU container starts.

=== "AMD and Intel"

    Load the GPU's kernel driver (`amdgpu` or `i915`/`xe`) so that
    `/dev/dri/renderD*` exists. For ROCm, the `amdgpu` driver must also create
    `/dev/kfd`.

    A render node is `root:render` with mode `0660`. The proxy refuses
    `GroupAdd`, so an image that does not run as root inside its container
    cannot open it.

## Where it does not see the GPU

- **WSL2.** The GPU is not on the PCI bus there. It reaches Linux through
  `/dev/dxg`. The worker says it cannot tell, and still passes an NVIDIA
  request: Docker Desktop and Docker in WSL with the toolkit can serve it. AMD
  and Intel are refused on WSL.
- **Docker VMs without GPU passthrough.** When the worker's PCI read shows no
  GPU of the requested vendor, it refuses the deploy.
- **Docker on another machine.** sysfs describes the machine the worker runs
  on. When `DOCKER_HOST` names a network endpoint (`tcp://`, `ssh://`), Docker
  may run elsewhere, so the worker says it cannot tell. It reads sysfs only for
  a Unix socket, which is what the shipped compose files use.
- **A read that fails part way.** An empty or unreadable sysfs file means the
  worker cannot tell, never "no GPU". Only a complete read refuses a deploy for
  a missing vendor.
- **More than 8 render nodes.** Only `renderD128` to `renderD135` are passed in.
  SR-IOV virtual functions count as GPUs.

When the worker cannot tell, it still passes an NVIDIA request, which Docker
checks at start. It refuses AMD and Intel, because it cannot pick their render
node.

## Your compose file

The proxy's policy must allow the GPU. If your compose file is older than this
feature, the worker refuses a GPU service's deploy with the command that updates
the policy ([upgrading](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md)).
Nothing else is affected.

A service exported as a Compose file carries the same request. For NVIDIA it
is a `deploy.resources.reservations.devices` entry. For AMD and Intel it is the
render node a deploy on that worker would pass in (and `/dev/kfd` for ROCm).
That node differs between machines: on a box with an Intel iGPU and an AMD card,
`renderD128` is often the iGPU. So name the worker the file is for:

```
GET  /api/compose/<slug>?worker_id=<id>
POST /api/compose            {"slugs": ["<slug>"], "worker_id": <id>}
```

The export reads the node from that worker's last heartbeat. Without a worker,
or when the worker cannot tell, the export of an AMD or Intel service is
refused with the reason. The export of every service (`GET /api/compose`)
leaves such a service out instead.
