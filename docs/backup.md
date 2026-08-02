# Backing up what cannot be replaced

Some services keep state on your machine that **exists nowhere else**: a node
identity, a relay key, a wallet generated inside the container on first run.
Lose the disk and you lose the held payout balance and the node's accumulated
reputation with it. Redeploying gives you a *new* node, starting from zero.

Most people never back these up, because nothing tells them the files exist.

CashPilot knows which mounts matter — the catalog marks them `critical_volumes`,
the same list the delete guard refuses on — so it can export exactly those.

## The one thing to understand first

!!! danger "Lose the passphrase and the backup is gone"

    There is **no recovery**. Not by CashPilot, not by resetting anything, not
    by asking anyone. This is deliberate: a backup CashPilot could recover is a
    backup that anyone who compromises CashPilot can also recover.

    Write the passphrase down somewhere that is not the machine being backed up.

## How it works

**Encryption happens on the worker**, on the machine that holds the data. The UI
only ever handles ciphertext, so plaintext key material never crosses the fleet
network and never sits in the dashboard's memory.

**You choose the target**, and CashPilot cannot decrypt either kind:

- **A recipient public key** (preferred). An X25519 public key — CashPilot never
  sees the private half, so it *cannot* open the bundle even in principle. Use
  your own, or have CashPilot generate a pair and keep the private key yourself.
- **A passphrase**, which is used to derive a key and then discarded with the
  request. Minimum 12 characters, because the realistic attack on a stolen
  bundle is offline guessing, and length is the only defence.

**The container is paused while its state is read.** A keystore or SQLite file
copied mid-write produces a backup that opens perfectly and restores a broken
node — a failure that only shows up when you finally need it. Pause rather than
stop, so a node does not lose uptime score for a backup.

**The bundle is returned in the response and nowhere else.** There is no upload,
no cloud sync, no webhook — not disabled, *absent*. Once such a path exists in
the code, anyone who compromises the UI can switch it on.

**There is no scheduled backup**, for the same reason: a timer needs a stored
secret, which is exactly the server-held key that would break the first rule.

## Is my backup actually any good?

"I have a backup file" and "I have a backup that works" are different claims,
and people discover the difference on the worst possible day.

The verify endpoint decrypts the bundle **in memory on the worker** and compares
its digest against the state currently on disk. Nothing is written, and no
plaintext is produced. It answers three ways:

| Answer | Meaning |
|---|---|
| matches | This bundle restores exactly what is running now. |
| does not match | It opens fine but is **out of date** — the node has moved on. |
| cannot open | Wrong passphrase or key, or the file has been altered. |

Verify after taking a backup, and again after you move it anywhere.

## What is not covered

- **Restore is not yet implemented.** Writing into a volume is the destructive
  half of this feature and is deliberately a separate change.
- Services with no `critical_volumes` entry are refused rather than backed up.
  If a service's state is re-downloadable, a backup teaches a false habit; if it
  is genuinely irreplaceable and missing from the catalog, that is a catalog bug
  worth reporting.
- Credentials in CashPilot's own database are a different thing, protected by a
  different key. This feature is only about state inside service containers.
