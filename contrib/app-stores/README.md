# App store packages

The packages we submit to home-server app stores live here, so they are
versioned with the app they install. Nothing here is used at runtime, and
nothing here triggers a release.

| Folder | Store | Where it goes upstream |
|---|---|---|
| `casaos/CashPilot/` | CasaOS app store | `Apps/CashPilot/` in https://github.com/IceWhaleTech/CasaOS-AppStore |
| `runtipi/cashpilot/` | Runtipi app store | `apps/cashpilot/` in https://github.com/runtipi/runtipi-appstore |

Unraid Community Applications and the TrueNAS community train are not here:
the Unraid templates live in `unraid/` and in GeiserX/docker-templates, and the
TrueNAS app is maintained in https://github.com/truenas/apps under
`ix-dev/community/cashpilot`.

## Rules for these packages

- Pin an exact release tag, such as `1.72.1`, never `latest`. The stores'
  own update bots bump an exact tag; a floating tag leaves users unable to tell
  what they run.
- The UI and the worker carry the same tag. A UI and a worker on different
  versions is a support problem.
- Only `cashpilot-socket-proxy` mounts `/var/run/docker.sock`, read-only, as in
  the repository's `docker-compose.yml`. The worker reaches Docker through the
  proxy's filtered socket (`DOCKER_HOST`), never the raw one, which is root on
  the host. `scripts/socket_proxy_policy.py` writes the proxy's policy into
  these files along with the shipped compose files.
- CasaOS interpolates its file twice (on import, then again when Compose loads
  what it saved). So the CasaOS file writes each `$` in the policy as `$$$$`,
  and uses no `${VAR:-default}`: CasaOS turns an unset variable into an empty
  string, never the default.
- The worker's `/data` stays
  apart from the UI's `/data`, which holds the credential store and its key.
  `/fleet` is shared, because it holds only the enrolment key both sides need.

`tests/test_app_store_templates.py` checks these rules on every compose file
under this folder, and simulates the CasaOS install. `tests/test_socket_proxy.py`
holds the Runtipi file to the same proxy rules as the shipped compose files.

## Refreshing a package before a submission

1. Set both image tags to the newest release (https://github.com/GeiserX/CashPilot/releases).
2. CasaOS: update `version`, `update_at` and `release_notes` in the `x-casaos`
   block at the end of the file.
3. Runtipi: update `version` and `updated_at` (milliseconds since the epoch) in
   `config.json`, and add 1 to `tipi_version`, so existing installs see the update.
4. Run `uv run python scripts/socket_proxy_policy.py --check`, then
   `uv run pytest tests/test_app_store_templates.py tests/test_socket_proxy.py`.
5. Copy the folder into your fork of the store and open the pull request there.
