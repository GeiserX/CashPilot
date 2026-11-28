# Earner credentials outside Docker's container config

A worker starts each earner with the credentials you gave it: a password, a
token, an API key. By default it passes them the way Docker expects, as
environment variables and command-line arguments. Docker keeps both in the
container's config. So anyone who can run `docker inspect`, read
`/var/lib/docker/containers`, or talk to the Docker socket sees every earner
password in plain text. Backups of the Docker folder hold them too.

With `CASHPILOT_EARNER_SECRETS=file` on a worker, the worker keeps those
values out of the container config.

## How to turn it on

Add the variable to the worker and recreate it:

```yaml
services:
  cashpilot-worker:
    environment:
      # ...the variables it already has...
      - CASHPILOT_EARNER_SECRETS=file
```

```bash
docker compose up -d cashpilot-worker
```

Then redeploy each earner that has a password or a token (its service page,
**Redeploy**). Earners keep their old container until you redeploy them.
**Settings > Earner credentials** shows, for each worker, whether the setting is
on and how many earners still keep their credentials in Docker's config.

Turn it off the same way: remove the variable, recreate the worker, redeploy.

## What changes in the earner

For an earner whose catalog entry marks a variable as secret:

- Its environment in Docker has no secret variable. Its command line carries
  `${HONEYGAIN_PASSWORD}` (for example) where the password was.
- It gets a small volume of its own, `cashpilot-secret-<id>`, mounted at
  `/run/cashpilot-secret`. Between creating the container and starting it,
  the worker writes two files there through the Docker API: `env`, with the
  secret variables, and `cashpilot-env`, a small static program.
- Its entrypoint is `/run/cashpilot-secret/cashpilot-env`, followed by the
  earner's own entrypoint and command. The program reads `env`, sets the
  variables, puts each value in place of its `${NAME}` in the arguments, and
  starts the earner. The earner gets exactly what it got before.

The program needs no shell, so it works in images that have none. A
`docker restart`, a reboot or a crash restart runs the same steps again,
because the volume keeps both files. Removing the service removes the volume.

The socket proxy already allows this. Its policy lets the worker write into a
container only at `/run/cashpilot-secret`, so you do not change your compose
file beyond the one variable.

## Which earners it covers

Every catalog service with a secret variable and a published image:

| Service | Secret | Where the earner reads it |
|---|---|---|
| Bitping | password | environment |
| Earn.fm | token | environment |
| Honeygain | password | command line |
| IPRoyal Pawns | password | command line |
| ProxyBase | device ID | command line |
| ProxyRack | API key | environment |
| Repocket | API key | environment |
| Traffmonetizer | token | command line |
| URnetwork | password | command line |
| Sia hostd | dashboard password | environment |

Not covered:

- **Custom services.** They always keep the plain environment. CashPilot does
  not know which of their variables are secret.
- **Services with no secret variable.** Nothing to move.
- **A service whose catalog entry says `docker.secrets_in_file: false`.** That
  is the switch for an earner that cannot run this way.
- **Sia's wallet seed.** It already lives in a file in hostd's own volume, not
  in a variable.

Some earners cannot be started this way. The worker then logs a warning that
says why, and starts that earner the old way, with its credentials in plain
text in `docker inspect`. This happens when:

- the worker image has no `cashpilot-env`, or it cannot be read
- a credential holds a NUL byte
- another variable holds a credential's value, for example a login built from
  the password
- the entrypoint holds a credential
- the command already holds `${NAME}` text, or cannot be split into arguments

Check the worker log after you turn the setting on.

## What it does not protect against

Be clear about the limits:

- **Root on the host still reads the values.** The running earner has them in
  its environment, so `/proc/<pid>/environ` and `docker exec <earner> env`
  show them. The volume is a folder under `/var/lib/docker/volumes`, readable
  by root.
- **The CashPilot database still holds them, encrypted.** This setting is
  about the copy Docker keeps. To keep the database's key away from the
  database, see [Encryption key outside the data folder](encryption-key.md).

- **Anything with full Docker API access can still read the file.** `docker
  cp cashpilot-honeygain:/run/cashpilot-secret/env -` and `docker exec` both
  work for such a client, without root on the host.

What it does protect: `docker inspect` output and the container config, with
every copy of it. That covers backups of `/var/lib/docker/containers`, support
bundles, and `docker inspect` output pasted into a forum post.

## Check it

```bash
docker inspect cashpilot-honeygain --format '{{json .Config.Env}}'
docker inspect cashpilot-honeygain --format '{{json .Config.Cmd}}'
```

Before: `HONEYGAIN_PASSWORD=...` in the first, the password after `-pass` in
the second. After: no `HONEYGAIN_PASSWORD` in the first, and
`${HONEYGAIN_PASSWORD}` after `-pass` in the second.
