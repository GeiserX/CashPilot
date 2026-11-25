# GPU services

Some catalog services need a GPU, such as a GPU miner. CashPilot gives that GPU
to that one container, and to no other. This page says what it passes in, what it
never does, and what your host needs first.

!!! warning "Beta"

    The GPU grant is new and has not yet run on a real NVIDIA, AMD or Intel
    host. Its tests and the socket proxy's live check pass. It stays beta until
    it has run on one real host. Tell us how it goes on yours: open an issue
    with the card, the driver and the error, if any.

## Who gets a GPU

A GPU goes only to a **catalog service whose entry declares `docker.gpu`**. The
worker reads that from its own catalog, never from the deploy request.

- **A custom service never gets one.** An image you add yourself has not been
  reviewed ([custom services](custom-services.md)).
- **A proxied copy never gets one.** It lives inside its tunnel's network
  namespace ([proxied copies](proxies.md)).
- **One copy per machine.** Two copies would share the same GPU.
- **Every other container gets `NVIDIA_VISIBLE_DEVICES=void`.** CUDA base images
  set that variable to `all`. On a host whose default Docker runtime is
  `nvidia`, such an image would get every GPU with no grant at all. The
  container's own value wins over the image's, so it gets none.

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
- **macOS and Windows hosts.** Docker runs in a virtual machine that has no
  GPU. A deploy is refused when the worker reads that machine's PCI bus and finds
  no GPU of that vendor.
- **More than 8 render nodes.** Only `renderD128` to `renderD135` are passed in.
  SR-IOV virtual functions count as GPUs.

## Your compose file

The proxy's policy must allow the GPU. If your compose file is older than this
feature, the worker refuses a GPU service's deploy with the command that updates
the policy ([upgrading](https://github.com/GeiserX/CashPilot/blob/main/UPGRADING.md)).
Nothing else is affected.

A service exported as a Compose file carries the same request: a
`deploy.resources.reservations.devices` entry for NVIDIA, or
`/dev/dri/renderD128` (and `/dev/kfd` for ROCm) for AMD and Intel. Compose cannot
read sysfs, so change the render node if yours has another number.
