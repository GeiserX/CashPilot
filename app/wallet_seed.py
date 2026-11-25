"""A service's wallet seed, kept in a file in the service's own data volume and nowhere else.

Sia's hostd needs a BIP-39 seed phrase, and the phrase IS the wallet: whoever
reads it can spend the node's Siacoin and its locked collateral. It used to be
an ordinary secret env var. CashPilot then held it, Fernet-encrypted, in a
database whose key file sits next to it, and Docker held it in plain text in
the container's settings (``docker inspect``, ``config.v2.json``,
``/proc/<pid>/environ``).

Now the catalog marks the variable with ``seed_file`` (services/_schema.yml)
and the phrase lives only in that file, inside the volume the service already
keeps its wallet in, on the machine that runs it:

* **New wallet.** The worker runs the service's own image, offline, with the
  catalog's ``generate`` command, writes the phrase into the file and returns
  it once, so the owner can write it down. The UI never stores it.
* **Existing wallet.** The owner pastes the phrase; it goes to that worker,
  into the file, and nowhere else.
* **Keep.** A redeploy finds the file and leaves it alone.
* **Migration.** A deploy that still carries the phrase as the variable (an
  older UI, or a record from before this) has it written into the file when
  the file has none, and the variable never reaches the container.

The file is written and read through a helper container that is created and
never started, as a restore writes a volume (orchestrator._create_restore_helper):
the socket proxy lets the worker write into a container only under
RESTORE_WRITE_DIR, so the volume is mounted there.

Nothing here logs a phrase, puts one in an exception message, or keeps one in
memory past the call that handles it.
"""

from __future__ import annotations

import contextlib
import hashlib
import io
import re
import tarfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

#: The heartbeat feature of a worker that keeps the seed in the file. The UI
#: sends a seed-file service to no other worker for a new wallet.
FEATURE = "wallet_seed_file"

#: What a deploy asks of the wallet: make one when there is none, write this
#: one, write the one CashPilot recorded before the file existed (a file that
#: holds another wins, as it already does in hostd), or keep the one the node has.
MODES = ("generate", "import", "migrate", "keep")

#: Where the helper mounts the volume. Under the one folder the socket proxy
#: lets the worker write into (orchestrator.RESTORE_WRITE_DIR).
WRITE_DIR = "/run/cashpilot-secret"
MOUNT_NAME = "wallet"

#: Label of the helper containers, so a leftover one is recognisable.
LABEL_HELPER = "cashpilot.wallet-helper"

#: Seconds the generator may run. It only prints two lines.
GENERATE_TIMEOUT = 60

_WORDLIST_FILE = Path(__file__).with_name("bip39_english.txt")


class WalletSeedError(Exception):
    """A wallet step that must not go ahead. The message never holds a phrase.

    ``code`` is the worker's error code, ``status`` the HTTP status it answers with.
    """

    def __init__(self, message: str, code: str, status: int = 409) -> None:
        super().__init__(message)
        self.code = code
        self.status = status


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------


def seed_var(svc: dict[str, Any] | None) -> dict[str, Any] | None:
    """The env entry of ``svc`` whose value lives in a file (``seed_file``), or None."""
    for var in ((svc or {}).get("docker") or {}).get("env") or []:
        if isinstance(var, dict) and isinstance(var.get("seed_file"), dict) and var.get("key"):
            return var
    return None


def seed_key(svc: dict[str, Any] | None) -> str | None:
    """The name of that env var (HOSTD_WALLET_SEED), or None."""
    var = seed_var(svc)
    return str(var["key"]) if var else None


def validate_spec(var: dict[str, Any], volume_targets: set[str]) -> list[str]:
    """What is wrong with one ``seed_file`` block; [] when nothing is."""
    spec = var.get("seed_file") or {}
    errors: list[str] = []
    if not var.get("secret"):
        errors.append("seed_file is only for a secret variable")
    path = spec.get("path")
    if not isinstance(path, str) or not path.startswith("/") or path.endswith("/"):
        errors.append("seed_file.path must be an absolute file path")
    elif str(Path(path).parent) not in volume_targets:
        errors.append("seed_file.path must sit directly in a folder docker.volumes mounts")
    if not isinstance(spec.get("key"), str) or not spec.get("key"):
        errors.append("seed_file.key must name the YAML key that holds the phrase")
    if spec.get("words") != 12:
        errors.append("seed_file.words must be 12 (the only BIP-39 length checked here)")
    generate = spec.get("generate")
    if not (isinstance(generate, list) and generate and all(isinstance(a, str) for a in generate)):
        errors.append("seed_file.generate must be a command (a list of strings)")
    for name in ("phrase_pattern", "address_pattern"):
        try:
            if re.compile(str(spec.get(name) or "")).groups != 1:
                errors.append(f"seed_file.{name} must have exactly one group")
        except re.error:
            errors.append(f"seed_file.{name} must be a valid regular expression")
    return errors


# ---------------------------------------------------------------------------
# Phrases
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def _wordlist() -> dict[str, int]:
    words = _WORDLIST_FILE.read_text().split()
    if len(words) != 2048:
        raise RuntimeError(f"{_WORDLIST_FILE.name} holds {len(words)} words, not the 2048 of BIP-39")
    return {word: index for index, word in enumerate(words)}


def normalize(phrase: Any) -> str:
    """The phrase as hostd reads it: lowercase words, one space apart."""
    return " ".join(str(phrase or "").lower().split())


def phrase_problem(phrase: str, words: int = 12) -> str | None:
    """Why ``phrase`` is not a valid BIP-39 phrase of ``words`` words, or None.

    The same rule hostd applies at start (coreutils wallet.SeedFromPhrase): the
    words of the English list, and the checksum in the last word. Checked before
    anything is written, so a typo is refused here instead of leaving a node
    that cannot start. The answer never repeats a word.
    """
    found = normalize(phrase).split()
    if len(found) != words:
        return f"A seed phrase has {words} words; this one has {len(found)}."
    wordlist = _wordlist()
    unknown = [n for n, word in enumerate(found, 1) if word not in wordlist]
    if unknown:
        many = len(unknown) > 1
        return (
            ("Words " if many else "Word ")
            + ", ".join(map(str, unknown))
            + (" are not BIP-39 words." if many else " is not a BIP-39 word.")
            + " Check the spelling."
        )
    bits = 0
    for word in found:
        bits = (bits << 11) | wordlist[word]
    checksum_bits = words * 11 // 33
    entropy = (bits >> checksum_bits).to_bytes(words * 11 * 32 // 33 // 8, "big")
    if hashlib.sha256(entropy).digest()[0] >> (8 - checksum_bits) != bits & ((1 << checksum_bits) - 1):
        return "The words are all valid, but the phrase does not check out. One of them is probably wrong."
    return None


# ---------------------------------------------------------------------------
# Worker side: the file in the volume
# ---------------------------------------------------------------------------


def _mount_source(volumes: dict[str, Any] | None, folder: str) -> str | None:
    """The host path or volume name ``volumes`` mounts at ``folder``."""
    for source, mount in (volumes or {}).items():
        if isinstance(mount, dict) and str(mount.get("bind") or "").rstrip("/") == folder:
            return str(source)
    return None


def _helper(client: Any, image: str, name: str, source: str) -> Any:
    """A created, never started container mounting ``source`` under WRITE_DIR: no network, no capabilities."""
    from docker.types import Mount

    _remove_named(client, name)
    kind = "bind" if source.startswith("/") else "volume"
    return client.containers.create(
        image=image,
        name=name,
        command=["true"],
        network_mode="none",
        mounts=[Mount(f"{WRITE_DIR}/{MOUNT_NAME}", source, type=kind)],
        labels={LABEL_HELPER: "file"},
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
    )


def _remove_named(client: Any, name: str) -> None:
    """Remove a helper a worker that died midway left under ``name``."""
    from docker.errors import NotFound

    with contextlib.suppress(NotFound):
        client.containers.get(name).remove(force=True)


def _read_file(container: Any, path: str) -> bytes | None:
    """One file out of ``container``, or None when there is none."""
    from docker.errors import NotFound

    try:
        stream, _stat = container.get_archive(path)
    except NotFound:
        return None
    data = b"".join(stream)
    with tarfile.open(fileobj=io.BytesIO(data)) as tar:
        for member in tar:
            if member.isfile():
                handle = tar.extractfile(member)
                return handle.read() if handle is not None else b""
    return None


def _parse(raw: bytes | None, key: str) -> tuple[dict[str, Any], str]:
    """The file's YAML mapping and the phrase under ``key`` ("" when absent)."""
    if raw is None or not raw.strip():
        return {}, ""
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError:
        raise WalletSeedError(
            "The node's config file is not valid YAML, so CashPilot did not change it. Fix or remove it, "
            "then deploy again. Nothing was deployed.",
            "wallet_file_invalid",
        ) from None
    if not isinstance(data, dict):
        raise WalletSeedError(
            "The node's config file is not a YAML mapping, so CashPilot did not change it. Nothing was deployed.",
            "wallet_file_invalid",
        )
    return data, normalize(data.get(key))


def _tar(name: str, content: bytes) -> bytes:
    """A tar holding ``name`` with ``content``, owned by root, readable by its owner only."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        info = tarfile.TarInfo(name)
        info.size = len(content)
        info.mode = 0o600
        info.mtime = int(time.time())
        tar.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _generate(client: Any, image: str, name: str, spec: dict[str, Any]) -> tuple[str, str | None]:
    """A new phrase and its address, from the image's own generator, run offline."""
    from docker.types import LogConfig

    _remove_named(client, name)
    container = client.containers.create(
        image=image,
        name=name,
        command=list(spec["generate"]),
        network_mode="none",
        cap_drop=["ALL"],
        security_opt=["no-new-privileges:true"],
        labels={LABEL_HELPER: "generate"},
        # The phrase is printed. json-file is local and goes with the container,
        # which is removed below; a daemon that ships logs off the box (journald,
        # syslog, a log service) must never receive it.
        log_config=LogConfig(type=LogConfig.types.JSON),
    )
    try:
        container.start()
        result = container.wait(timeout=GENERATE_TIMEOUT)
        output = container.logs(stdout=True, stderr=False).decode(errors="replace")
    finally:
        container.remove(force=True)
    if (result or {}).get("StatusCode") != 0:
        raise WalletSeedError("The node's image could not create a wallet. Nothing was deployed.", "wallet_generate")
    phrase_match = re.search(spec["phrase_pattern"], output)
    address_match = re.search(spec["address_pattern"], output)
    phrase = normalize(phrase_match.group(1)) if phrase_match else ""
    if not phrase or phrase_problem(phrase, int(spec.get("words") or 12)):
        raise WalletSeedError(
            "The node's image did not print a wallet CashPilot could read. Nothing was deployed.", "wallet_generate"
        )
    return phrase, address_match.group(1) if address_match else None


def prepare(
    client: Any,
    svc: dict[str, Any] | None,
    container_name: str,
    image: str,
    env: dict[str, str],
    volumes: dict[str, Any] | None,
    wanted: dict[str, Any] | None,
) -> dict[str, Any]:
    """Put the wallet in its file before the container is created; take the variable out of ``env``.

    ``env`` is changed in place: the seed variable is removed whatever happens,
    so it never reaches the container. ``wanted`` is the deploy's ``wallet_seed``
    (mode and, for import, the phrase), or None from a caller that predates it:
    then a phrase in ``env`` is migrated, and otherwise the file must exist.

    Returns ``{"created", "address", "phrase"}``; ``phrase`` only for a wallet
    made on this deploy, to be shown once. {} for a service with no seed file.
    Raises WalletSeedError before anything is written when the deploy cannot go
    ahead.
    """
    var = seed_var(svc)
    if var is None:
        return {}
    spec = var["seed_file"]
    key = str(var["key"])
    words = int(spec.get("words") or 12)
    legacy = normalize(env.pop(key, ""))
    wanted = wanted or {}
    mode = wanted.get("mode") or ("migrate" if legacy else "keep")
    if mode not in MODES:
        raise WalletSeedError("Unknown wallet choice. Nothing was deployed.", "wallet_mode", 400)
    phrase = normalize(wanted.get("phrase")) or legacy if mode in ("import", "migrate") else ""
    if mode in ("import", "migrate"):
        if not phrase:
            raise WalletSeedError(
                "Paste the seed phrase of the wallet to use. Nothing was deployed.", "wallet_phrase", 400
            )
        if problem := phrase_problem(phrase, words):
            raise WalletSeedError(f"{problem} Nothing was deployed.", "wallet_phrase", 400)

    path = Path(spec["path"])
    folder = str(path.parent)
    source = _mount_source(volumes, folder)
    if source is None:
        raise WalletSeedError(
            f"This deploy mounts nothing at {folder}, where the node keeps its wallet. Nothing was deployed.",
            "wallet_volume",
            400,
        )
    helper = _helper(client, image, f"{container_name}.wallet", source)
    try:
        inside = f"{WRITE_DIR}/{MOUNT_NAME}/{path.name}"
        data, current = _parse(_read_file(helper, inside), str(spec["key"]))
        if current:
            if mode == "import" and phrase != current:
                raise WalletSeedError(
                    "This node already has another wallet, and CashPilot does not replace one. Reveal its seed "
                    "phrase from the dashboard first; to change wallets, remove the service with its data. "
                    "Nothing was deployed.",
                    "wallet_exists",
                )
            # A migrated phrase that differs from the file's never ran: hostd
            # reads the file first. The file stays as it is.
            return {"created": False, "address": None, "phrase": None}
        address = None
        if mode == "keep":
            raise WalletSeedError(
                "This node has no wallet file yet. Deploy it again and choose a new wallet, or paste the seed "
                "phrase of the one you have. Nothing was deployed.",
                "wallet_missing",
            )
        if mode == "generate":
            phrase, address = _generate(client, image, f"{container_name}.wallet-new", spec)
        data[str(spec["key"])] = phrase
        content = yaml.safe_dump(data, default_flow_style=False, sort_keys=False, width=10**6).encode()
        if not helper.put_archive(WRITE_DIR, _tar(f"{MOUNT_NAME}/{path.name}", content)):
            raise WalletSeedError("Docker did not write the wallet file. Nothing was deployed.", "wallet_write", 500)
        return {"created": True, "address": address, "phrase": phrase if mode == "generate" else None}
    finally:
        helper.remove(force=True)


def reveal(container: Any, svc: dict[str, Any] | None) -> str:
    """The phrase in the file of the deployed ``container`` (running or not)."""
    var = seed_var(svc)
    if var is None:
        raise WalletSeedError("This service keeps no wallet seed.", "wallet_none", 404)
    spec = var["seed_file"]
    _data, phrase = _parse(_read_file(container, str(spec["path"])), str(spec["key"]))
    if not phrase:
        raise WalletSeedError("This node has no wallet file.", "wallet_missing", 404)
    return phrase
