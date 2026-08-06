# Backing up and restoring CashPilot

Two files decide whether a restore works. If you read nothing else on this page,
read this box.

!!! danger "`.fernet_key` is not recoverable"

    Every credential you have entered — provider passwords, API keys, session
    cookies — is encrypted in the database with the key in
    `/data/.fernet_key`. **The database alone is not enough.** Restore
    `cashpilot.db` without that key and every stored credential is permanently
    undecryptable. There is no recovery, no reset, no support path: the
    plaintext does not exist anywhere else.

    Back up **both**, always, together.

This page covers the CashPilot UI's own data. Backing up the *node identities*
your services generate — the Mysterium keystore and friends — is a separate job
and lives in [Backing Up Node Identities](backup.md).

---

## What is in `/data`

The UI's `/data` volume (`cashpilot_data` in the shipped compose files):

| Path | What it is | Lose it and… |
|---|---|---|
| `cashpilot.db` | SQLite: earnings history, deployments, workers, users, settings | you lose your history |
| `.fernet_key` | Encrypts every stored credential, at rest | **every credential is permanently unreadable** |
| `.secret_key` | Signs login sessions | everyone is logged out once; nothing else |

`.secret_key` **may not exist**, and that is normal. It is only written when
`CASHPILOT_SECRET_KEY` is unset — set the variable and the file is never
created. Verified on a live install: `/data` held `.fernet_key` and nothing
else.

`.secret_key` and `.fernet_key` are **different keys with different jobs**, and
they are easy to confuse because both are set by an environment variable with a
similar name. `CASHPILOT_SECRET_KEY` signs sessions. `CASHPILOT_ENCRYPTION_KEY`
is the credential key. Restoring the wrong one gets you a working login and
unreadable credentials.

There are two other volumes, and neither is precious:

- `cashpilot_fleet` (`/fleet/.fleet_key`) — the shared enrollment key. Shared by
  the UI and its co-located worker. If you lose it, set `CASHPILOT_API_KEY`
  explicitly or let it regenerate and re-enroll the workers.
- `cashpilot_worker_data` (`/data/.worker_key`) — that worker's own issued key.
  Lose it and the worker re-enrolls on its next heartbeat. Nothing is destroyed.

    The worker's `/data` is a **separate volume from the UI's, deliberately**.
    The worker holds the Docker socket, which is root on the host; it has no
    business being able to read the credential store. Do not consolidate them.

---

## Backup

Stop nothing. SQLite is in WAL mode, but a plain file copy of a live database
can still catch a torn write, so use SQLite's own backup command for the
database and copy the keys alongside it.

```bash
# Everything that matters, into one dated directory.
OUT="cashpilot-backup-$(date +%Y%m%d)"
mkdir -p "$OUT"

# The database, consistently, without stopping the container.
docker exec cashpilot-ui sh -c \
  'python -c "import sqlite3,sys; s=sqlite3.connect(\"/data/cashpilot.db\"); d=sqlite3.connect(\"/tmp/backup.db\"); s.backup(d); d.close(); s.close()"'
docker cp cashpilot-ui:/tmp/backup.db "$OUT/cashpilot.db"
docker exec cashpilot-ui rm -f /tmp/backup.db

# THE key. Without it the database above is half a backup.
docker cp cashpilot-ui:/data/.fernet_key "$OUT/.fernet_key"

# Only present if CASHPILOT_SECRET_KEY is unset, so do not fail without it.
docker cp cashpilot-ui:/data/.secret_key "$OUT/.secret_key" 2>/dev/null \
  || echo "no .secret_key (CASHPILOT_SECRET_KEY is set in the environment) — fine"

chmod 600 "$OUT"/.*key 2>/dev/null
ls -la "$OUT"
```

!!! warning "The backup is now as sensitive as the server"

    `.fernet_key` plus `cashpilot.db` is every provider credential you own, in a
    directory. Treat that pair the way you would treat the passwords themselves:
    encrypted storage, restricted permissions, and not in a git repository.

### Verify it, or it is not a backup

An untested backup is a hope. Check that the two files are non-empty and that
the database opens:

```bash
test -s "$OUT/.fernet_key" && echo "key present"   # the one that cannot be regenerated
sqlite3 "$OUT/cashpilot.db" "PRAGMA integrity_check;"   # expect: ok
sqlite3 "$OUT/cashpilot.db" "SELECT count(*) FROM earnings;"
```

---

## Restore

Onto a fresh install, before it has generated its own keys:

```bash
docker compose down

# Recreate the volume and put all three files back TOGETHER.
docker volume create cashpilot_data
docker run --rm -v cashpilot_data:/data -v "$PWD/$OUT":/backup alpine sh -c '
  cp /backup/cashpilot.db /data/cashpilot.db &&
  cp /backup/.fernet_key  /data/.fernet_key  &&
  # Optional: absent whenever CASHPILOT_SECRET_KEY is set.
  { [ -f /backup/.secret_key ] && cp /backup/.secret_key /data/.secret_key || true; } &&
  chmod 600 /data/.fernet_key &&
  chown -R 1000:1000 /data'

docker compose up -d
docker logs -f cashpilot-ui
```

### What the logs should say

Two lines tell you the restore worked.

The schema line reports the version and any migration that ran — expect a
migration if the backup came from an older release, and none if it did not:

```
Schema at version 10; no migration needed this boot.
Schema now at version 10 (was 0). Migrations applied this boot: earnings.source
```

And there should be **no** decryption error. If the key did not come across you
will see this, once per affected credential:

```
Failed to decrypt a stored credential: the credential-encryption key
(CASHPILOT_ENCRYPTION_KEY / /data/.fernet_key) does not match the key this
value was encrypted with.
```

That message means exactly what it says: the database was restored and the key
was not. Put the original `.fernet_key` back. **The credentials cannot be
recovered any other way.**

### Restoring the key by environment variable instead

If you kept the key as a secret rather than a file, `CASHPILOT_ENCRYPTION_KEY`
is adopted **only when no key file exists** — which covers both a fresh install
and a restore onto an empty volume:

```yaml
environment:
  - CASHPILOT_ENCRYPTION_KEY=<the base64 key from your backup>
```

The file always wins where it exists. That ordering is deliberate: a running
install must never have its key silently replaced by a stale environment
variable.

---

## Things CashPilot refuses to do, and why

Three refusals you may run into. All three are the software declining to destroy
something.

**It will not overwrite an unreadable `.fernet_key`.** If the file exists but is
corrupt or the wrong length, startup fails rather than generating a replacement —
because generating one would destroy the only artifact that could still decrypt
your credentials. Restore the file, or move it aside and re-enter the
credentials, which is a real choice you are allowed to make.

**It will not start if the key cannot be persisted.** A read-only or
unwritable `/data` means every credential entered during that run becomes
undecryptable the moment the container restarts. Failing at startup is kinder
than failing silently, hours later.

**A failed decrypt is logged as an ERROR, not a warning.** This is unattended
software. The downstream symptom is a provider authentication failure that
points nowhere near the real cause, so it is logged loudly, at the point where
the cause is still visible.

---

## Upgrades

The images pin `major.minor` in the shipped compose files, so `docker compose
pull` picks up patch fixes and never crosses a minor boundary without an edit.

Before a minor or major upgrade: **take the backup above.** Migrations are
forward-only — there is no down migration — so the way back is a restore. The
schema line at startup tells you whether anything actually changed.
