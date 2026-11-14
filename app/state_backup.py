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
        try:
            # A well-formed 32-byte key can still be a low-order point, for
            # which the shared secret is all zeros and OpenSSL refuses the
            # exchange with a bare ValueError. That is a 400 — the caller gave
            # us an unusable key — not the 500 an escaping exception produces.
            key = _derive_shared(ephemeral.exchange(recipient), salt)
        except ValueError as exc:
            raise BackupError(
                "Recipient public key is not a usable X25519 point, so no shared key can be derived."
            ) from exc

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
        try:
            # The ephemeral key here comes out of the BUNDLE, so it is
            # attacker-controlled on a restore: a crafted bundle carrying a
            # low-order point would otherwise crash the verify endpoint with an
            # unhandled 500 instead of being rejected as the bad input it is.
            key = _derive_shared(private.exchange(ephemeral), salt)
        except ValueError as exc:
            raise BackupError(
                "Bundle's ephemeral public key is not a usable X25519 point, so it cannot be opened."
            ) from exc
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


#: The most file data a restore unpacks. The worker never exports more than
#: ``orchestrator.MAX_BACKUP_BYTES`` (64 MB) and CashPilot-Desktop never more than
#: its ``MaxStateBytes`` (256 MB), tar headers included, so every bundle either app
#: made fits. Sparse entries are refused, so file data can never exceed the
#: decrypted payload already in memory. This file runs on its own (copy it, or run
#: it from the image), so it keeps its own copy of the number; a test holds it at
#: or above the worker's.
MAX_ARCHIVE_BYTES = 256 * 1024 * 1024

#: The most entries a restore accepts. An identity, a keystore or a wallet folder
#: holds tens of files, a Tor-style relay folder a few hundred. Past this it is a
#: data folder, which the size cap already sends to a disk-level backup. Each entry
#: is held in memory twice, so the count is capped as well as the bytes.
MAX_ARCHIVE_ENTRIES = 20_000

#: The only PAX records a restore accepts. tarfile turns each of these into a
#: TarInfo field (name, link, size, owner, times), and the entry is rebuilt from
#: those fields. Anything else is refused: ``SCHILY.xattr.*`` (file capabilities,
#: SELinux labels), ACLs, ``GNU.sparse.*``, vendor records. Docker applies every
#: ``SCHILY.xattr.*`` record it extracts, so passing one through would hand a
#: bundle's author a file capability on the restored volume.
_PAX_FIELDS = frozenset(
    {"path", "linkpath", "size", "uid", "gid", "uname", "gname", "mtime", "atime", "ctime", "hdrcharset"}
)


#: A modification time further than this from 1970 (about 317 years) is refused,
#: and so is ``inf`` or ``nan``, which a PAX ``mtime`` record can carry.
_MAX_MTIME = 10**10


def _clean(name: str) -> str:
    return "/".join(p for p in name.split("/") if p not in ("", "."))


def _unsafe_member(member: Any, links: set[str], files: set[str], seen: set[str]) -> str | None:
    """Which rule refuses ``member``, or None when it may be restored.

    The restore extracts these archives as root into a volume, and in recipient
    mode anyone holding the public key can build a bundle that opens cleanly. So
    every entry is checked on its own, by the rules of tarfile's ``data_filter``
    and stricter: names are refused rather than rewritten, a symlink target may
    not use ``..`` at all (a chain of links can climb out even when each target
    looks inside on paper), and a hard link must point at a file that came earlier
    in the same folder. ``links``, ``files`` and ``seen`` hold the cleaned names
    of the links, regular files and all entries read so far.
    """
    name = member.name
    bad = next((c for c in name + member.linkname if ord(c) < 0x20 or ord(c) == 0x7F), None)
    if bad is not None:
        # A NUL survives in tarfile's name but ends the name in the ustar field
        # it is written back to, so the checks below would judge another name.
        return f"{name!r} has the control character {bad!r} in its name or link target"
    if member.mtime != member.mtime or abs(member.mtime) >= _MAX_MTIME:  # nan, inf, out of range
        return f"{name!r} has an invalid modification time"
    if member.issparse() or any(k.startswith("GNU.sparse.") for k in member.pax_headers):
        return f"{name!r} is a sparse file (refused: a few bytes in the file unpack to gigabytes)"
    extra = sorted(set(member.pax_headers) - _PAX_FIELDS)
    if extra:
        return (
            f"{name!r} carries the extended record {extra[0][:80]!r} (refused: only names, sizes, owners, "
            "modes and times are restored, never extended attributes such as file capabilities)"
        )
    if not (member.isfile() or member.isdir() or member.issym() or member.islnk()):
        return f"{name!r} is a device, pipe or other special entry, not a file, folder or link"
    if name.startswith(("/", "\\")):
        return f"{name!r} is an absolute path"
    parts = [p for p in name.split("/") if p not in ("", ".")]
    if not parts or ".." in parts:
        return f"{name!r} leaves its folder"
    for depth in range(1, len(parts)):
        if "/".join(parts[:depth]) in links:
            return f"{name!r} is written through a link"
    if "/".join(parts) in seen:
        return f"{name!r} appears twice (each path may appear once)"
    if member.issym() or member.islnk():
        target = member.linkname
        tparts = target.split("/")
        if not target or target.startswith(("/", "\\")) or ".." in tparts:
            return f"{name!r} links to {target!r}, outside its folder"
        if member.islnk():
            clean = _clean(target)
            if clean not in files or clean.split("/", 1)[0] != parts[0]:
                return f"{name!r} hard-links to {target!r}, which is not a file earlier in the same folder"
    return None


def split_archives(payload: bytes) -> dict[str, bytes]:
    """The decrypted payload as one tar archive per backed-up mount.

    The worker stores each critical mount as Docker's own archive of it, one
    after another. Each archive's members sit under the mount's last path
    component (``/var/lib/mysterium-node`` -> ``mysterium-node/...``), so they
    are regrouped by that name.

    Every entry is rebuilt from a short list of fields: name, type, permission
    bits, owner ids, modification time, size and link target. Owners, modes and
    times are what ``docker cp`` and ``tar -x`` need to put the files back as the
    service expects them; nothing else from the input reaches the output.

    One refused entry fails the whole restore, and the error names the rule (see
    ``_unsafe_member``): an absolute name, ``..``, a link pointing out, a path
    through a link, a path given twice, a device or pipe, a sparse file, or any
    extended record such as a file capability. Setuid, setgid and sticky bits are
    dropped. More than ``MAX_ARCHIVE_BYTES`` of file data or
    ``MAX_ARCHIVE_ENTRIES`` entries is refused before the data is read.
    """
    import io
    import tarfile

    groups: dict[str, list[tuple[tarfile.TarInfo, bytes | None]]] = {}
    links: set[str] = set()
    files: set[str] = set()
    seen: set[str] = set()
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:", ignore_zeros=True) as src:
            for count, member in enumerate(src, start=1):
                if count > MAX_ARCHIVE_ENTRIES:
                    raise BackupError(
                        f"The backup holds more than {MAX_ARCHIVE_ENTRIES} entries and was not restored "
                        "(entry cap). That is a data folder, not an identity: back it up at the disk level."
                    )
                if src.pax_headers:
                    raise BackupError(
                        "The backup holds an unsafe entry and was not restored: the archive carries a PAX "
                        "global header (refused: it would apply its records to every entry after it)."
                    )
                if member.name.startswith("./"):
                    member.name = member.name[2:]
                why = _unsafe_member(member, links, files, seen)
                if why:
                    raise BackupError(f"The backup holds an unsafe entry and was not restored: {why}.")
                name = _clean(member.name)
                seen.add(name)
                data = None
                clean = tarfile.TarInfo(name)
                clean.mode = member.mode & 0o777
                clean.uid, clean.gid = member.uid, member.gid
                clean.mtime = int(member.mtime)
                if member.isfile():
                    total += member.size
                    if total > MAX_ARCHIVE_BYTES:
                        raise BackupError(
                            f"The backup unpacks to more than {MAX_ARCHIVE_BYTES // (1024 * 1024)} MB and was "
                            "not restored (size cap). No export is that large."
                        )
                    data = src.extractfile(member).read()  # type: ignore[union-attr]
                    clean.type, clean.size = tarfile.REGTYPE, len(data)
                    files.add(name)
                elif member.isdir():
                    clean.type = tarfile.DIRTYPE
                elif member.issym():
                    clean.type, clean.linkname = tarfile.SYMTYPE, member.linkname
                    links.add(name)
                else:
                    clean.type, clean.linkname = tarfile.LNKTYPE, _clean(member.linkname)
                    links.add(name)
                groups.setdefault(name.split("/", 1)[0], []).append((clean, data))
    except tarfile.TarError as exc:
        raise BackupError(f"The backup's archive is damaged: {exc}") from exc

    out: dict[str, bytes] = {}
    for top, members in groups.items():
        buf = io.BytesIO()
        with tarfile.open(fileobj=buf, mode="w", format=tarfile.PAX_FORMAT) as dst:
            for member, data in members:
                dst.addfile(member, io.BytesIO(data) if data is not None else None)
        out[top] = buf.getvalue()
    return out


def restore_volumes(docker_conf: dict[str, Any]) -> dict[str, str] | None:
    """critical target -> named volume, when a restore from the dashboard may fill this service.

    Only a service whose every ``critical_volumes`` target sits on a named
    volume the catalog YAML names literally: the worker creates that volume new
    for the restore and checks it did. A target on a host folder (``${VAR}``, a
    path) is refused, because the worker cannot see or empty a host folder;
    Storj and Sia keep terabytes there anyway. None when nothing qualifies.
    """
    critical = [
        str(e["target"]).rstrip("/") or "/"
        for e in docker_conf.get("critical_volumes") or []
        if isinstance(e, dict) and e.get("target")
    ]
    if not critical:
        return None
    sources: dict[str, str] = {}
    for mapping in docker_conf.get("volumes") or []:
        parts = str(mapping).split(":")
        if len(parts) >= 2:
            sources[parts[1].rstrip("/") or "/"] = parts[0]
    found: dict[str, str] = {}
    for target in critical:
        source = sources.get(target, "")
        # A literal volume name ([A-Za-z0-9][A-Za-z0-9_.-]*), never ${VAR} or a path.
        if not (source[:1].isalnum() and source.isascii() and all(c.isalnum() or c in "_.-" for c in source)):
            return None
        found[target] = source
    return found


def _below_top(name: str) -> str:
    """``name`` without its first path component: the path inside the backed-up folder."""
    return _clean(name).partition("/")[2]


def relative_archive(archive: bytes) -> bytes:
    """One archive from :func:`split_archives`, renamed to sit inside its folder.

    split_archives keeps Docker's layout, each entry under the folder's own name
    (``mysterium-node/keystore/...``). A restore writes into the folder itself,
    so the first component goes, and with it the folder's own entry: Docker does
    not apply it to a folder that exists, and the folder is the volume's root.
    Hard links are renamed the same way. Only names change.

    Each entry is a new TarInfo with the fields split_archives keeps. Renaming
    the one read in is not enough: a name over 100 bytes or not ASCII arrives
    as a PAX ``path`` record, which tarfile writes back in preference to the
    new name, so the entry would land one folder too deep. A real Mysterium
    keystore file is one.
    """
    import io
    import tarfile

    out = io.BytesIO()
    with (
        tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as src,
        tarfile.open(fileobj=out, mode="w", format=tarfile.PAX_FORMAT) as dst,
    ):
        for member in src:
            name = _below_top(member.name)
            if not name:
                continue
            data = src.extractfile(member).read() if member.isfile() else None  # type: ignore[union-attr]
            clean = tarfile.TarInfo(name)
            clean.type, clean.mode, clean.uid, clean.gid = member.type, member.mode, member.uid, member.gid
            clean.mtime, clean.size = member.mtime, member.size
            clean.linkname = _below_top(member.linkname) if member.islnk() else member.linkname
            dst.addfile(clean, io.BytesIO(data) if data is not None else None)
    return out.getvalue()


def tree_manifest(archive: bytes, *, max_bytes: int = MAX_ARCHIVE_BYTES) -> dict[str, tuple[Any, ...]]:
    """What a folder holds, as ``path -> (type, mode, uid, gid, content)``, from Docker's archive of it.

    ``path`` is below the folder (the folder's own entry is left out), ``content``
    is a file's SHA-256 or a link's target. Modification times are not compared:
    they say nothing about whether the restore is the backup. Used twice by a
    restore, on what it meant to write and on what Docker reads back, so a file
    missing, changed, added or owned by someone else shows as a difference.
    More than ``max_bytes`` of file data is refused rather than read.
    """
    import io
    import tarfile

    found: dict[str, tuple[Any, ...]] = {}
    total = 0
    try:
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as src:
            for member in src:
                path = _below_top(member.name)
                if not path:
                    continue
                if member.isfile():
                    total += member.size
                    if total > max_bytes:
                        raise BackupError("The restored folder holds more than a backup can, so it was not compared.")
                    data = src.extractfile(member).read()  # type: ignore[union-attr]
                    entry: tuple[Any, ...] = ("file", hashlib.sha256(data).hexdigest())
                elif member.isdir():
                    entry = ("dir", "")
                elif member.issym():
                    entry = ("symlink", member.linkname)
                elif member.islnk():
                    entry = ("hardlink", _below_top(member.linkname))
                else:
                    entry = ("other", "")
                found[path] = (entry[0], member.mode & 0o777, member.uid, member.gid, entry[1])
    except tarfile.TarError as exc:
        raise BackupError(f"The restored folder could not be read back: {exc}") from exc
    return found


def manifest_differences(expected: dict[str, tuple[Any, ...]], found: dict[str, tuple[Any, ...]]) -> list[str]:
    """How ``found`` differs from ``expected``, one line per path; [] when it is the backup.

    A folder the image already had at that path (Docker copies the image's
    folders into a new volume when the container is created) may stay when the
    backup does not name it: it is empty or its files are listed on their own.
    Every file, link and owner must match exactly.
    """
    lines: list[str] = []
    for path in sorted(set(expected) | set(found)):
        want, got = expected.get(path), found.get(path)
        if want == got:
            continue
        if want is None and got is not None and got[0] == "dir":
            continue
        if want is None:
            lines.append(f"{path}: not in the backup")
        elif got is None:
            lines.append(f"{path}: missing")
        elif want[0] != got[0]:
            lines.append(f"{path}: a {got[0]}, not a {want[0]}")
        elif want[4] != got[4]:
            lines.append(f"{path}: different content")
        else:
            lines.append(f"{path}: owner or permissions differ")
    return lines


def _cli(argv: list[str] | None = None) -> int:
    """``python -m app.state_backup`` -- open a bundle on your own machine.

    Secrets are read from the terminal (or stdin when piped), never from the
    command line, where they would land in shell history and the process list.
    Needs only Python and the ``cryptography`` package, so it runs without
    CashPilot: copy this one file, or run it from the CashPilot image with
    ``--network none``.
    """
    import argparse
    import getpass
    import os
    import sys

    parser = argparse.ArgumentParser(prog="python -m app.state_backup", description=_cli.__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("keygen", help="make an X25519 key pair; keep the private key, give CashPilot the public one")
    dec = sub.add_parser("decrypt", help="open a .cpbackup file into one tar per backed-up folder")
    dec.add_argument("bundle", help="the .cpbackup file")
    dec.add_argument("--out", required=True, help="folder to write the tar files into (created if missing)")
    args = parser.parse_args(argv)

    if args.command == "keygen":
        private, public = generate_recipient_keypair()
        print(f"private key (keep this, offline; it opens your backups): {private}")
        print(f"public key (paste this into CashPilot): {public}")
        return 0

    with open(args.bundle, "rb") as fh:
        bundle = fh.read()
    try:
        header = read_header(bundle)
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    prompt = "Passphrase: " if header.get("mode") == MODE_PASSPHRASE else "Private key (hex): "
    secret = getpass.getpass(prompt) if sys.stdin.isatty() else sys.stdin.readline().rstrip("\n")
    try:
        if header.get("mode") == MODE_PASSPHRASE:
            payload = open_bundle(bundle, passphrase=secret)
        else:
            payload = open_bundle(bundle, recipient_private_key=secret.strip())
        archives = split_archives(payload)
    except BackupError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    finally:
        del secret

    meta = header.get("metadata") or {}
    os.makedirs(args.out, exist_ok=True)
    targets = {str(t).rstrip("/").rsplit("/", 1)[-1]: str(t) for t in meta.get("targets") or []}
    print(f"{meta.get('slug', '?')} from {meta.get('worker', '?')}, checksum verified.")
    paths = {name: os.path.join(args.out, f"{name}.tar") for name in archives}
    taken = sorted(p for p in paths.values() if os.path.lexists(p))
    if taken:
        print(f"error: {', '.join(taken)} already exists. Use an empty --out folder.", file=sys.stderr)
        return 1
    for name, data in sorted(archives.items()):
        try:
            with open(paths[name], "xb") as fh:
                fh.write(data)
        except FileExistsError:
            print(f"error: {paths[name]} already exists. Use an empty --out folder.", file=sys.stderr)
            return 1
        print(f"  {paths[name]}  ->  restores {targets.get(name, '/' + name)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli())
