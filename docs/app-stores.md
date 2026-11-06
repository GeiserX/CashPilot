# App stores

You can install CashPilot from the app store of several home-server systems.
Each listing installs two containers: the dashboard (`drumsergio/cashpilot`)
and the worker (`drumsergio/cashpilot-worker`). The listings do not yet include
the socket proxy that `docker-compose.yml` runs, so there the worker mounts the
Docker socket itself to start and stop the service containers.

Whichever store you use, keep the dashboard on your LAN or VPN. It can command
the worker, and the worker's Docker socket is root on the host.

## Listed today

### Unraid Community Applications

Search for **CashPilot** in the Apps tab and install both templates:
`cashpilot` (the dashboard) and `cashpilot-worker`. Set the same
`CASHPILOT_API_KEY` on both.

The templates come from https://github.com/GeiserX/docker-templates and follow
the `latest` image tag, so Community Applications users get each release
without a template change.

### TrueNAS SCALE

CashPilot is in the TrueNAS **community** train. Open Apps, then Discover Apps,
and search for **CashPilot**.

The app definition is maintained at
https://github.com/truenas/apps/tree/master/ix-dev/community/cashpilot and pins
an exact image digest. TrueNAS's own bots move it to new releases, so it can be
a few releases behind the newest CashPilot.

## Waiting for review

### CasaOS

A pull request to the CasaOS app store is open:
https://github.com/IceWhaleTech/CasaOS-AppStore/pull/1088

Until it is merged, install it as a custom app: in CasaOS choose App Store,
then Custom Install, then Import, and paste the contents of
https://github.com/GeiserX/CashPilot/blob/main/contrib/app-stores/casaos/CashPilot/docker-compose.yml

## Prepared, not yet submitted

### Runtipi

The package is ready in
https://github.com/GeiserX/CashPilot/tree/main/contrib/app-stores/runtipi/cashpilot
but not yet in the Runtipi app store. To use it now, add it to a custom app
store you control, following the Runtipi docs:
https://runtipi.io/docs/guides/create-your-own-app-store

## Not offered

Umbrel needs a different worker design, because Umbrel apps reach Docker
through a Docker-in-Docker container rather than the host socket. We have not
tested that, so there is no Umbrel package yet.

For any other system, use `docker-compose.yml` from the repository, as in
[Getting started](getting-started.md).
