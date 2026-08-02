"""Encrypted export of irreplaceable service state (CashPilot-qqo).

Users overwhelmingly do not back up node identities and wallets, because nothing
tells them those files exist. When a disk dies the held payout balance, the relay
stake, or the wallet is simply gone — and no other feature in this project
survives that.

It is also the most dangerous thing here, because it hands the worker a new
capability: reading key material out of a container volume. The worker already
holds the Docker socket, so the question is not whether it *could* but whether
the design ever gives anyone a reason to.

The constraints below are not tunable knobs. Each one closes a specific way this
feature turns into an exfiltration channel.

**The installation must not be able to decrypt its own exports.** No server-held
wrapping key, no fallback to the Fernet key that protects credentials. If
CashPilot could open the bundle, then anyone who compromises CashPilot inherits
every node identity it ever exported — turning a backup feature into the single
highest-value target in the system. So the user supplies the target: either an
X25519 recipient public key, where no secret ever enters CashPilot at all, or a
passphrase which is used and discarded.

**No destination but the response to the authenticated caller.** No upload, no
sync, no webhook. The moment such a path exists in the code, a compromised UI
can switch it on; the absence of the code is the control.

**No scheduled export.** A timer needs a stored secret, which is precisely the
server-held key the first rule forbids. Alert on "no verified backup" instead.

**AEAD, not encryption alone.** ChaCha20-Poly1305 so tampering is detected
rather than decrypted into garbage, with the header authenticated as associated
data so nobody can swap the metadata that says which service a bundle belongs to.

And the part users get wrong: **losing the passphrase means the backup is gone.**
There is no recovery, by construction. Anything that could recover it would
violate the first rule.
"""

from __future__ import annotations

import hashlib
import json
import secrets
from typing import Any

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

MAGIC = b"CASHPILOT-BACKUP"
VERSION = 1

MODE_PASSPHRASE = "passphrase"
MODE_RECIPIENT = "recipient"

# scrypt parameters. Deliberately expensive: the threat is an offline attack on a
# stolen bundle, where the only defence is the cost of each guess.
_SCRYPT_N = 2**15
_SCRYPT_R = 8
_SCRYPT_P = 1
_SALT_BYTES = 16
_NONCE_BYTES = 12
_KEY_BYTES = 32

_HKDF_INFO = b"cashpilot-backup-v1"

# A passphrase short enough to brute-force offline is not protection, and this
# is the one secret with no server-side rate limit in front of it.
MIN_PASSPHRASE_LENGTH = 12


class BackupError(Exception):
    """Raised when a bundle cannot be produced or opened."""


def generate_recipient_keypair() -> tuple[str, str]:
    """A fresh X25519 keypair as (private_key_hex, public_key_hex).

    Offered so a user without an age setup can still use recipient mode. The
    PRIVATE half is returned once, to the caller, and never stored — a copy kept
    anywhere in this installation would recreate exactly the "CashPilot can
    decrypt its own backups" property this design exists to prevent.
    """
    private = X25519PrivateKey.generate()
    return (
        private.private_bytes_raw().hex(),
        private.public_key().public_bytes_raw().hex(),
    )


def _derive_from_passphrase(passphrase: str, salt: bytes) -> bytes:
    kdf = Scrypt(salt=salt, length=_KEY_BYTES, n=_SCRYPT_N, r=_SCRYPT_R, p=_SCRYPT_P)
    return kdf.derive(passphrase.encode("utf-8"))


def _derive_shared(shared: bytes, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=_KEY_BYTES, salt=salt, info=_HKDF_INFO).derive(shared)


def seal(
    payload: bytes,
    *,
    passphrase: str | None = None,
    recipient_public_key: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bytes:
    """Encrypt ``payload`` into a self-describing bundle.

    Exactly one of ``passphrase`` or ``recipient_public_key`` must be given.
    Recipient mode is preferred: no secret enters CashPilot at all, so a
    compromised installation cannot open bundles it produced earlier even with
    full memory access at the time.
    """
    if bool(passphrase) == bool(recipient_public_key):
        raise BackupError("Provide exactly one of a passphrase or a recipient public key.")

    salt = secrets.token_bytes(_SALT_BYTES)
    nonce = secrets.token_bytes(_NONCE_BYTES)
    header: dict[str, Any] = {
        "magic": MAGIC.decode(),
        "version": VERSION,
        "salt": salt.hex(),
        "nonce": nonce.hex(),
        "metadata": metadata or {},
        # Lets a restore prove it got the same bytes back without the plaintext
        # ever being written anywhere.
        "sha256": hashlib.sha256(payload).hexdigest(),
    }

    if passphrase:
        if len(passphrase) < MIN_PASSPHRASE_LENGTH:
            raise BackupError(
                f"Passphrase must be at least {MIN_PASSPHRASE_LENGTH} characters. "
                "This is the only thing standing between a stolen bundle and a node identity."
            )
        header["mode"] = MODE_PASSPHRASE
        key = _derive_from_passphrase(passphrase, salt)
    else:
        header["mode"] = MODE_RECIPIENT
        try:
            recipient = X25519PublicKey.from_public_bytes(bytes.fromhex(str(recipient_public_key)))
        except (ValueError, TypeError) as exc:
            raise BackupError("Recipient public key must be 32 bytes of hex (an X25519 public key).") from exc
        ephemeral = X25519PrivateKey.generate()
        header["ephemeral_public_key"] = ephemeral.public_key().public_bytes_raw().hex()
        key = _derive_shared(ephemeral.exchange(recipient), salt)

    header_bytes = json.dumps(header, sort_keys=True, separators=(",", ":")).encode("utf-8")
    # The header is authenticated, not encrypted: swapping the metadata that
    # says which service a bundle belongs to must invalidate it.
    ciphertext = ChaCha20Poly1305(key).encrypt(nonce, payload, header_bytes)
    return len(header_bytes).to_bytes(4, "big") + header_bytes + ciphertext


def read_header(bundle: bytes) -> dict[str, Any]:
    """The unencrypted, authenticated header. Never contains key material."""
    if len(bundle) < 4:
        raise BackupError("Not a CashPilot backup bundle.")
    length = int.from_bytes(bundle[:4], "big")
    if length <= 0 or len(bundle) < 4 + length:
        raise BackupError("Not a CashPilot backup bundle.")
    try:
        header = json.loads(bundle[4 : 4 + length].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BackupError("Not a CashPilot backup bundle.") from exc
    if header.get("magic") != MAGIC.decode():
        raise BackupError("Not a CashPilot backup bundle.")
    if header.get("version") != VERSION:
        raise BackupError(f"Unsupported bundle version {header.get('version')!r}.")
    return header


def open_bundle(
    bundle: bytes,
    *,
    passphrase: str | None = None,
    recipient_private_key: str | None = None,
) -> bytes:
    """Decrypt a bundle, or raise BackupError.

    The failure message never distinguishes a wrong passphrase from a corrupted
    bundle in a way that would help an attacker, and never echoes any input.
    """
    header = read_header(bundle)
    length = int.from_bytes(bundle[:4], "big")
    header_bytes = bundle[4 : 4 + length]
    ciphertext = bundle[4 + length :]

    try:
        salt = bytes.fromhex(header["salt"])
        nonce = bytes.fromhex(header["nonce"])
    except (KeyError, ValueError) as exc:
        raise BackupError("Bundle header is malformed.") from exc

    mode = header.get("mode")
    if mode == MODE_PASSPHRASE:
        if not passphrase:
            raise BackupError("This bundle needs the passphrase it was created with.")
        key = _derive_from_passphrase(passphrase, salt)
    elif mode == MODE_RECIPIENT:
        if not recipient_private_key:
            raise BackupError("This bundle needs the private key matching the recipient it was created for.")
        try:
            private = X25519PrivateKey.from_private_bytes(bytes.fromhex(recipient_private_key))
            ephemeral = X25519PublicKey.from_public_bytes(bytes.fromhex(header["ephemeral_public_key"]))
        except (KeyError, ValueError, TypeError) as exc:
            raise BackupError("Bundle header is malformed, or the private key is not valid X25519.") from exc
        key = _derive_shared(private.exchange(ephemeral), salt)
    else:
        raise BackupError(f"Unknown bundle mode {mode!r}.")

    try:
        payload = ChaCha20Poly1305(key).decrypt(nonce, ciphertext, header_bytes)
    except InvalidTag as exc:
        raise BackupError(
            "Could not decrypt this bundle. Either the passphrase or key is wrong, or the file has "
            "been altered. There is no recovery path — that is the point of the design."
        ) from exc

    expected = header.get("sha256")
    if expected and hashlib.sha256(payload).hexdigest() != expected:
        raise BackupError("Bundle decrypted but its contents do not match the recorded checksum.")
    return payload


def verify(
    bundle: bytes,
    live_payload: bytes,
    *,
    passphrase: str | None = None,
    recipient_private_key: str | None = None,
) -> dict[str, Any]:
    """Does this bundle still match what is on disk right now?

    "I have a backup file" and "I have a backup that works" are different
    claims, and believing the first when only the second matters is how people
    discover a dead node and an unusable file on the same afternoon.

    Compares digests, never plaintext, and writes nothing.
    """
    try:
        restored = open_bundle(bundle, passphrase=passphrase, recipient_private_key=recipient_private_key)
    except BackupError as exc:
        return {"ok": False, "matches": False, "reason": str(exc)}

    live_digest = hashlib.sha256(live_payload).hexdigest()
    backup_digest = hashlib.sha256(restored).hexdigest()
    matches = secrets.compare_digest(live_digest, backup_digest)
    return {
        "ok": True,
        "matches": matches,
        "backup_sha256": backup_digest,
        "live_sha256": live_digest,
        "reason": (
            "This backup matches the state currently on disk."
            if matches
            else "This backup opens correctly but no longer matches the live volume — it is out of date."
        ),
    }


def looks_like_bundle(data: bytes) -> bool:
    """Cheap check used before spending scrypt work on obvious junk."""
    try:
        read_header(data)
    except BackupError:
        return False
    return True
