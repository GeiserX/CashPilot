"""Tests for the credential-encryption key lifecycle (CashPilot-1ii).

The behaviour under test is deliberately about failure modes: a key that does
not survive a restart silently destroys every stored credential, and the symptom
the user sees is a provider auth failure that points nowhere near the cause.

Each test reloads ``app.database`` under a patched environment, because the key
is resolved once at import time. The module is always reloaded back to its
original state afterwards so the rest of the suite is unaffected.
"""

from __future__ import annotations

import importlib
import os
from pathlib import Path

import pytest
from cryptography.fernet import Fernet

from app import database as _database

_MANAGED_VARS = (
    "CASHPILOT_DATA_DIR",
    "CASHPILOT_ENCRYPTION_KEY",
    "CASHPILOT_ALLOW_EPHEMERAL_KEY",
)


def _reload(env: dict[str, str]):
    """Reload app.database with exactly the given CashPilot env vars set.

    The variables stay set after this returns, because
    ``verify_encryption_key_persisted`` reads the opt-out at call time, not at
    import time. ``_restore_environment`` puts them back afterwards.
    """
    for name in _MANAGED_VARS:
        os.environ.pop(name, None)
    os.environ.update(env)
    return importlib.reload(_database)


@pytest.fixture(autouse=True)
def _restore_environment():
    """Restore env and module so the rest of the suite is unaffected."""
    saved = {name: os.environ.get(name) for name in _MANAGED_VARS}
    yield
    for name, value in saved.items():
        if value is None:
            os.environ.pop(name, None)
        else:
            os.environ[name] = value
    importlib.reload(_database)


def test_generates_and_persists_a_key_when_none_exists(tmp_path: Path):
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})

    key_file = tmp_path / ".fernet_key"
    assert key_file.is_file(), "a fresh install must persist its generated key"
    assert not db._fernet_key_is_ephemeral
    db.verify_encryption_key_persisted()  # must not raise

    # And the key is actually usable.
    assert db.decrypt_value(db.encrypt_value("hunter2")) == "hunter2"


def test_supplied_key_is_adopted_and_restores_existing_values(tmp_path: Path):
    """The restore path: wiped volume + CASHPILOT_ENCRYPTION_KEY brings data back."""
    key = Fernet.generate_key().decode()

    # Encrypt something under that key, as a previous deployment would have.
    ciphertext = "enc:" + Fernet(key.encode()).encrypt(b"my-api-token").decode()

    # Fresh volume (no .fernet_key), key supplied by environment.
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_ENCRYPTION_KEY": key})

    assert db.decrypt_value(ciphertext) == "my-api-token", (
        "a supplied key must decrypt values encrypted by the previous deployment"
    )
    # It is persisted, so the next restart does not depend on the env var.
    assert (tmp_path / ".fernet_key").read_text().strip() == key
    db.verify_encryption_key_persisted()


def test_existing_key_file_wins_over_the_environment(tmp_path: Path, caplog):
    """File-first: setting the env var on a live instance must not orphan data."""
    file_key = Fernet.generate_key().decode()
    (tmp_path / ".fernet_key").write_text(file_key)

    # Something already encrypted under the on-disk key.
    ciphertext = "enc:" + Fernet(file_key.encode()).encrypt(b"already-stored").decode()

    other_key = Fernet.generate_key().decode()
    with caplog.at_level("WARNING"):
        db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_ENCRYPTION_KEY": other_key})

    assert db.decrypt_value(ciphertext) == "already-stored", (
        "the stored key must win, or setting the env var destroys existing credentials"
    )
    assert (tmp_path / ".fernet_key").read_text().strip() == file_key
    # The divergence must not be silent.
    assert any("differs from the key already stored" in r.message for r in caplog.records)


def test_startup_refuses_when_the_key_cannot_be_persisted(tmp_path: Path):
    """A key that dies with the process must stop the app, not warn and continue."""
    # Put the data dir *below a regular file* so mkdir fails with NotADirectoryError.
    # This is deliberate: a chmod-based test would not fail when running as root.
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    unwritable = blocker / "data"

    db = _reload({"CASHPILOT_DATA_DIR": str(unwritable)})

    assert db._fernet_key_is_ephemeral
    with pytest.raises(RuntimeError, match="Cannot persist the credential-encryption key"):
        db.verify_encryption_key_persisted()


def test_ephemeral_key_allowed_only_when_explicitly_opted_in(tmp_path: Path):
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")
    unwritable = blocker / "data"

    db = _reload(
        {
            "CASHPILOT_DATA_DIR": str(unwritable),
            "CASHPILOT_ALLOW_EPHEMERAL_KEY": "true",
        }
    )

    assert db._fernet_key_is_ephemeral
    db.verify_encryption_key_persisted()  # opted in, so it must not raise


def test_import_still_succeeds_when_the_data_dir_is_unusable(tmp_path: Path):
    """Importing must stay side-effect free: the test suite imports with /data."""
    blocker = tmp_path / "not-a-directory"
    blocker.write_text("x")

    # The reload itself is the assertion - it must not raise.
    db = _reload({"CASHPILOT_DATA_DIR": str(blocker / "data")})
    assert db.encrypt_value("still-works").startswith("enc:")


def test_malformed_supplied_key_is_refused_rather_than_replaced(tmp_path: Path):
    """Silently generating a replacement would be the same bug in a new costume."""
    db = _reload(
        {
            "CASHPILOT_DATA_DIR": str(tmp_path),
            "CASHPILOT_ENCRYPTION_KEY": "obviously-not-a-fernet-key",
        }
    )

    assert db._fernet_key_error
    with pytest.raises(RuntimeError, match="not a valid Fernet key|unusable"):
        db.verify_encryption_key_persisted()


def test_decrypt_reports_key_mismatch_without_blaming_the_credential(tmp_path: Path, caplog):
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})

    foreign = "enc:" + Fernet(Fernet.generate_key()).encrypt(b"x").decode()
    with caplog.at_level("ERROR"):
        assert db.decrypt_value(foreign) == ""

    message = " ".join(r.message for r in caplog.records)
    assert "CASHPILOT_ENCRYPTION_KEY" in message
    assert "NOT a bad credential" in message


def test_corrupt_key_file_is_never_overwritten(tmp_path: Path):
    """Overwriting a corrupt key destroys the only thing that could decrypt data.

    Regression guard: an earlier revision fell through to 'generate a new key',
    which silently replaced the file that existing credentials depended on.
    """
    key_file = tmp_path / ".fernet_key"
    key_file.write_text("this-is-not-a-fernet-key")

    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})

    assert key_file.read_text() == "this-is-not-a-fernet-key", "a corrupt key file must be preserved, not replaced"
    assert db._fernet_key_error
    with pytest.raises(RuntimeError, match="Refusing to overwrite it"):
        db.verify_encryption_key_persisted()


def test_empty_key_file_is_replaced_because_nothing_was_stored_under_it(tmp_path: Path):
    """An empty file never held a key, so minting one loses nothing."""
    key_file = tmp_path / ".fernet_key"
    key_file.write_text("   \n")

    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})

    db.verify_encryption_key_persisted()  # must not raise
    assert key_file.read_text().strip(), "a usable key should have been written"
    assert db.decrypt_value(db.encrypt_value("v")) == "v"


def test_key_file_is_created_private(tmp_path: Path):
    _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    mode = (tmp_path / ".fernet_key").stat().st_mode & 0o777
    assert mode == 0o600, f"key file must not be group/world readable, got {mode:o}"
