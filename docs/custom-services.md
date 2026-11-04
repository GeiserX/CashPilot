# Custom services

A custom service is an image you add yourself, from Docker Hub or any other registry, for a
service the catalog does not list yet. CashPilot deploys it to your workers, shows it on the
dashboard and lets you start, stop, restart, read the logs of and remove it like any other
service. You do not edit any YAML.

CashPilot has not reviewed a custom image. It runs with exactly the restrictions every catalog
service runs with, and CashPilot cannot read its earnings.

## Adding one

Open **Catalog**. Above the list, under **Your custom services**, choose **Add custom service**.
Only an owner account sees it. Then fill in:

| Field | What it takes |
|---|---|
| **Name** | What the dashboard calls it, up to 60 characters. Its internal name, `custom-<name>`, never changes after you create it, so renaming moves nothing. A second service with the same name becomes `custom-<name>-v2`, and a name ending in a number loses the dash before it (`Node 2` is `custom-node2`), because `-2` on a container name means a second copy. A deleted service's internal name is never given out again. |
| **Image** | `publisher/image:tag`, a full registry path such as `ghcr.io/publisher/image:1.4.2`, or a digest such as `publisher/image@sha256:...`. CashPilot accepts an image with no tag or the `latest` tag but warns you, because every redeploy then pulls whatever the publisher pushed last. |
| **Environment variables** | Up to 50 name and value pairs. CashPilot stores every value encrypted. Tick **Secret** for a token or password: its value is never sent back to the browser, and leaving it blank when you edit keeps the stored one. |
| **Command** | Optional. One line, passed to the image as its command. `${NAME}` is replaced by the value of variable `NAME`. |
| **Data path** | Optional. A path inside the container, such as `/data`. CashPilot keeps it in a Docker volume of its own, `cashpilot-custom-<name>-data`, so it survives redeploys. The container itself is `cashpilot-custom-<name>`. Blank means nothing is kept. |
| **Memory limit** | From `32m` to `16g`. Defaults to `512m`. |

Then open the service and deploy it to one or more boxes, as with a catalog service. A service
with a data path runs one copy per box; one without can run several.

## What it is allowed to do

The same as a catalog service with no special needs, and nothing more:

- every Linux capability dropped, and none added back;
- `no-new-privileges`, a process limit and the memory limit above;
- never privileged, never on the host network, no host devices;
- no host directories: its only mount is its own named volume;
- no published ports;
- on the bridge network you set with `CASHPILOT_CONTAINER_NETWORK`, when you set one. See
  [protecting your home network](home-network-security.md).

The worker enforces this on its own side as well. It grants capabilities, devices and host
networking only to services its own catalog declares them for, and no catalog service may use
the `custom-` prefix, so a custom service cannot be given them even by a hand-crafted request.
The worker also refuses an image whose main process is an init system such as systemd, as it does for
catalog services. [Configuration](configuration.md#a-services-image) explains why.

These limits mean an image that needs a published port, a capability like `NET_ADMIN`, a device
such as `/dev/net/tun`, or host networking will not work as a custom service. Such a service
belongs in the catalog, where those grants are reviewed: open an issue or a pull request.

## What it does not do

- **No earnings.** CashPilot has no collector for it, so the dashboard shows no balance for it.
  Check its earnings on the provider's own site.
- **No architecture choice.** If the image is published for one architecture only, a worker on
  another fails at the pull or start with Docker's own error.
- **Redeploys use the saved definition.** The image and variables are changed by editing the
  service, never in the deploy form. After an edit, **Redeploy running instances** applies it.
  The dashboard shows **update available** when a box runs an older image than the definition.

## Removing it

1. Open the service and choose **Remove from this box** on each box. You are asked whether to
   delete its data volume too; cancelling keeps the data for a later deploy. Deleting it needs
   an owner account and cannot be undone. CashPilot asks this itself because the worker cannot
   tell whether data of a service it does not know is irreplaceable, so it only deletes it when
   explicitly told to.
2. When no box runs it any more, choose **Delete**. CashPilot refuses while any box still runs or
   holds a record of it. A data volume you kept in step 1 stays on that box; a new custom service
   never gets the same internal name, so it never mounts it. Delete it by hand when you no longer
   need it: `docker volume rm cashpilot-custom-<name>-data`.
