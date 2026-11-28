# Keeping the encryption key out of the data folder

CashPilot encrypts every credential it stores (provider passwords, API keys,
session cookies) with one key. On a default install that key is the file
`/data/.fernet_key`, in the same folder as the database it decrypts. So a copy
of the data folder holds both the locked box and its key. A backup of the
volume, a snapshot of the disk or a copy someone took holds every credential
you entered.

Keep the key somewhere else and a copy of the data folder alone decrypts
nothing. You can do it in the dashboard in a few minutes. This page explains
the steps, and gives tested recipes for Docker secrets and Infisical, plus
notes for Vault, 1Password and Bitwarden.

!!! warning "You now back up the key yourself"

    Once the key lives outside the data folder, a backup of the data folder
    no longer contains it. Keep a copy of the key in your secret manager or
    your password manager. Without it, the database cannot be decrypted, and
    nobody can recover it for you.

## Where CashPilot reads the key

The first source that is set wins:

| Order | Source | Notes |
|---|---|---|
| 1 | `CASHPILOT_ENCRYPTION_KEY_FILE` | A path to a file that holds the key. A Docker secret (`/run/secrets/...`), or a file a secret manager writes. If the variable is set and the file is missing, empty or holds no valid key, CashPilot does not start. It never falls back to another source and never makes a new key. |
| 2 | `/data/.fernet_key` | The default. Made on the first start. |
| 3 | `CASHPILOT_ENCRYPTION_KEY` | The key itself in an environment variable. Read on every start and never written to the data folder. |
| 4 | A new key | Made only when none of the above exists, and written to `/data/.fernet_key`. |

`/data/.fernet_key` comes before `CASHPILOT_ENCRYPTION_KEY`, as it always did:
setting the variable on a running install never swaps its key. To move to the
variable, delete the file once the variable holds the same key (the dashboard
does this for you, below).

This key is not `CASHPILOT_SECRET_KEY`. That one only signs login sessions.

## CashPilot refuses a key that reads nothing

At every start, CashPilot tries the key on the credentials already stored. If
the database holds encrypted credentials and the key decrypts none of them,
CashPilot stops with a message that says where the key came from. This
catches the common mistakes:

- a restore that brought back `cashpilot.db` without its key;
- a secret file that holds another install's key, or an old one;
- a key file moved aside by accident.

Before this check, a missing key meant a new key, and every stored credential
failed later with a provider login error that pointed nowhere near the cause.
A key that CashPilot made on that start is deleted again, so the data folder
stays as it was.

If the key is really lost, set `CASHPILOT_ACCEPT_UNREADABLE_CREDENTIALS=true`,
start CashPilot, enter your credentials again, then remove the variable.

## Move the key in the dashboard

Open **Settings > Credential encryption key**. The card says where the key
comes from now. Then:

1. Select **Move the key out of the data folder**, then **Show the key**.
   CashPilot asks for your password, writes the reveal to the audit log, and
   shows the key once. Copy it into your secret store.
2. Give the key to CashPilot from outside the data folder: a Docker secret
   (next section) or a secret manager.
3. Recreate the UI container, so it reads the new setting.
4. Open the card again. It shows that the key now comes from the file and that
   a copy is still in the data folder. Select **Delete the copy in the data
   folder** and enter your password. The card then says the data folder holds
   no copy of the key.

CashPilot deletes the copy only when the key from outside is exactly the same
key. If the data folder holds a different key, the card says so and leaves it.

Without the dashboard, read the key with
`docker exec cashpilot-ui cat /data/.fernet_key`, and delete it with
`docker exec cashpilot-ui rm /data/.fernet_key` after the UI has started on the
key from outside.

## Recipe: Docker secrets with Compose

Compose mounts a secret file at `/run/secrets/<name>` in the container. It
works without Swarm.

1. Put the key in a file next to your compose file. The UI runs as user 1000,
   so that user must be able to read it:

    ```bash
    mkdir -p secrets
    docker exec cashpilot-ui cat /data/.fernet_key > secrets/cashpilot_encryption_key
    sudo chown 1000:1000 secrets/cashpilot_encryption_key
    sudo chmod 400 secrets/cashpilot_encryption_key
    ```

2. Add the secret to `docker-compose.yml`:

    ```yaml
    secrets:
      cashpilot_encryption_key:
        file: ./secrets/cashpilot_encryption_key

    services:
      cashpilot-ui:
        # ...everything it already has...
        secrets:
          - cashpilot_encryption_key
        environment:
          # ...the variables it already has...
          - CASHPILOT_ENCRYPTION_KEY_FILE=/run/secrets/cashpilot_encryption_key
    ```

3. Recreate the UI and delete the copy in the data folder (dashboard step 4):

    ```bash
    docker compose up -d cashpilot-ui
    ```

The key is now on the host's disk in `./secrets`, outside the data volume.
Keep that folder out of the backups that hold the data volume, or the two meet
again.

## Recipe: Infisical

Store the key as a secret, for example `CASHPILOT_ENCRYPTION_KEY` in your
CashPilot project. Then pick one of two ways.

### The Infisical Agent writes the file

The agent signs in with a machine identity (Universal Auth) and renders the
secret into a file. CashPilot reads that file.

`agent.yaml`:

```yaml
infisical:
  address: "https://infisical.example.com"
auth:
  type: "universal-auth"
  config:
    client-id: "/etc/infisical/client-id"
    client-secret: "/etc/infisical/client-secret"
    remove_client_secret_on_read: false
sinks:
  - type: "file"
    config:
      path: "/etc/infisical/token"
templates:
  - source-path: /etc/infisical/key.tmpl
    destination-path: /run/cashpilot-key/cashpilot_encryption_key
    config:
      polling-interval: 300s
```

`key.tmpl` (the project id and the environment are yours):

```
{{- with secret "<project id>" "prod" "/" }}{{- range . }}{{- if eq .Key "CASHPILOT_ENCRYPTION_KEY" }}{{ .Value }}{{- end }}{{- end }}{{- end }}
```

Run the agent beside CashPilot and share the folder with the UI:

```yaml
volumes:
  cashpilot_key:

services:
  infisical-agent:
    image: infisical/cli:<pinned version>
    command: agent --config /etc/infisical/agent.yaml
    volumes:
      - ./infisical:/etc/infisical
      - cashpilot_key:/run/cashpilot-key
    restart: unless-stopped

  cashpilot-ui:
    # ...everything it already has...
    depends_on:
      - infisical-agent
    volumes:
      - cashpilot_data:/data
      - cashpilot_key:/run/cashpilot-key:ro
    environment:
      - CASHPILOT_ENCRYPTION_KEY_FILE=/run/cashpilot-key/cashpilot_encryption_key
```

The agent writes the file as root with mode 644 inside its volume, which user
1000 in the UI can read. If the UI starts before the agent wrote the file, it
stops with "could not be read"; `restart: unless-stopped` starts it again a few
seconds later.

### `infisical run` sets the variable

`infisical run` reads the project's secrets and starts a command with them in
its environment. Compose passes the variable on to the UI:

```yaml
services:
  cashpilot-ui:
    environment:
      - CASHPILOT_ENCRYPTION_KEY
```

```bash
infisical run --projectId <project id> --env prod -- docker compose up -d cashpilot-ui
```

Then delete the copy in the data folder from the dashboard: the card offers it
once the variable holds the same key. Docker keeps the variable in the UI
container's settings, so `docker inspect cashpilot-ui` shows it. The file way
above does not have that problem.

## Other secret managers

Anything that can write a file or set an environment variable works. Point
`CASHPILOT_ENCRYPTION_KEY_FILE` at the file, or set `CASHPILOT_ENCRYPTION_KEY`.
Not tested here, but each one is the same two steps:

- **HashiCorp Vault**: Vault Agent with a `template` stanza that writes the
  secret into a file, shared with the UI as in the Infisical Agent recipe.
- **1Password**: `op inject` renders a file from a template, and
  `op run -- docker compose up -d` sets the variable. 1Password Connect serves
  the same items to an agent that writes the file.
- **Bitwarden Secrets Manager**: `bws run -- docker compose up -d` sets the
  variable, or `bws secret get <id>` writes the value into the file.

## Undo

Put the key back as `/data/.fernet_key`, remove `CASHPILOT_ENCRYPTION_KEY_FILE`
(and `CASHPILOT_ENCRYPTION_KEY`), and recreate the UI:

```bash
docker cp secrets/cashpilot_encryption_key cashpilot-ui:/data/.fernet_key
docker exec cashpilot-ui chown 1000 /data/.fernet_key
docker exec cashpilot-ui chmod 600 /data/.fernet_key
docker compose up -d cashpilot-ui
```

## The earners' own credentials

This page is about the key on the UI. Each worker also hands earner passwords
to Docker, which keeps them in the container's settings. [Earner credentials
on each box](earner-secrets.md) covers that.
