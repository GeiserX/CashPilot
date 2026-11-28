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
    "CASHPILOT_ENCRYPTION_KEY_FILE",
    "CASHPILOT_ALLOW_EPHEMERAL_KEY",
    "CASHPILOT_ACCEPT_UNREADABLE_CREDENTIALS",
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
    # Never copied into the data folder: a copy of the folder must not be
    # enough to decrypt. The variable is read again on every start.
    assert not (tmp_path / ".fernet_key").exists()
    assert db.encryption_key_status()["source"] == "env"
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


def test_malformed_env_key_is_ignored_when_a_valid_file_key_exists(tmp_path: Path, caplog):
    """Regression: a stale malformed env value must not block startup.

    The file wins, so a malformed CASHPILOT_ENCRYPTION_KEY is exactly as moot as
    a valid-but-different one - which only warns. An earlier revision set the
    error flag before the file-precedence check and refused to start forever.
    """
    file_key = Fernet.generate_key().decode()
    (tmp_path / ".fernet_key").write_text(file_key)
    ciphertext = "enc:" + Fernet(file_key.encode()).encrypt(b"kept").decode()

    with caplog.at_level("WARNING"):
        db = _reload(
            {
                "CASHPILOT_DATA_DIR": str(tmp_path),
                "CASHPILOT_ENCRYPTION_KEY": "not-a-key",
            }
        )

    db.verify_encryption_key_persisted()  # must not raise
    assert db.decrypt_value(ciphertext) == "kept"
    assert any("Ignoring it" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# CASHPILOT_ENCRYPTION_KEY_FILE: the key in a file outside the data folder
# ---------------------------------------------------------------------------


def _secret(tmp_path: Path, key: str, name: str = "secret") -> Path:
    path = tmp_path / name
    path.write_text(key + "\n")
    return path


def test_key_file_wins_over_the_data_folder_and_the_variable(tmp_path: Path, caplog):
    data = tmp_path / "data"
    data.mkdir()
    outside = Fernet.generate_key().decode()
    (data / ".fernet_key").write_text(Fernet.generate_key().decode())
    with caplog.at_level("WARNING"):
        db = _reload(
            {
                "CASHPILOT_DATA_DIR": str(data),
                "CASHPILOT_ENCRYPTION_KEY_FILE": str(_secret(tmp_path, outside)),
                "CASHPILOT_ENCRYPTION_KEY": Fernet.generate_key().decode(),
            }
        )
    db.verify_encryption_key_persisted()
    ciphertext = "enc:" + Fernet(outside.encode()).encrypt(b"from-outside").decode()
    assert db.decrypt_value(ciphertext) == "from-outside"
    assert db.encryption_key_status()["source"] == "file"
    assert any("The file wins" in r.message for r in caplog.records)


def test_key_file_is_never_copied_into_the_data_folder(tmp_path: Path):
    data = tmp_path / "data"
    key = Fernet.generate_key().decode()
    db = _reload({"CASHPILOT_DATA_DIR": str(data), "CASHPILOT_ENCRYPTION_KEY_FILE": str(_secret(tmp_path, key))})
    db.verify_encryption_key_persisted()
    assert not (data / ".fernet_key").exists()
    status = db.encryption_key_status()
    assert status == {
        "source": "file",
        "file": str(tmp_path / "secret"),
        "data_file": str(data / ".fernet_key"),
        "data_copy": "none",
        "env_same": False,
        "outside": True,
        "removable": False,
    }


@pytest.mark.parametrize(
    ("content", "reason"),
    [(None, "could not be read"), ("", "the file is empty"), ("not-a-key", "does not hold a valid Fernet key")],
)
def test_a_broken_key_file_stops_the_start_and_never_falls_back(tmp_path: Path, content, reason):
    data = tmp_path / "data"
    data.mkdir()
    (data / ".fernet_key").write_text(Fernet.generate_key().decode())
    secret = tmp_path / "secret"
    if content is not None:
        secret.write_text(content)
    db = _reload({"CASHPILOT_DATA_DIR": str(data), "CASHPILOT_ENCRYPTION_KEY_FILE": str(secret)})
    with pytest.raises(RuntimeError, match=reason):
        db.verify_encryption_key_persisted()


def test_no_key_file_is_created_when_the_named_one_is_missing(tmp_path: Path):
    data = tmp_path / "data"
    db = _reload({"CASHPILOT_DATA_DIR": str(data), "CASHPILOT_ENCRYPTION_KEY_FILE": str(tmp_path / "gone")})
    with pytest.raises(RuntimeError):
        db.verify_encryption_key_persisted()
    assert not (data / ".fernet_key").exists()


# ---------------------------------------------------------------------------
# The key must read the credentials already stored
# ---------------------------------------------------------------------------


def _database_with(data: Path, *keys: str) -> None:
    """A cashpilot.db holding one credential encrypted under each key, as the app stores them."""
    import sqlite3

    data.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(data / "cashpilot.db")
    conn.execute("CREATE TABLE config (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute("CREATE TABLE workers (client_id TEXT, api_key_enc TEXT)")
    conn.execute("INSERT INTO config VALUES ('honeygain_email', 'me@example.com')")
    for n, key in enumerate(keys):
        token = "enc:" + Fernet(key.encode()).encrypt(b"secret").decode()
        conn.execute("INSERT INTO workers VALUES (?, ?)", (f"w{n}", token))
    conn.commit()
    conn.close()


def test_the_right_key_starts(tmp_path: Path):
    key = Fernet.generate_key().decode()
    _database_with(tmp_path, key)
    (tmp_path / ".fernet_key").write_text(key)
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    db.verify_encryption_key_matches()


def test_a_wrong_key_file_in_the_data_folder_is_refused(tmp_path: Path):
    _database_with(tmp_path, Fernet.generate_key().decode())
    (tmp_path / ".fernet_key").write_text(Fernet.generate_key().decode())
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    with pytest.raises(RuntimeError, match="decrypts none of the 1 stored credentials"):
        db.verify_encryption_key_matches()


def test_a_wrong_secret_file_is_refused(tmp_path: Path):
    data = tmp_path / "data"
    _database_with(data, Fernet.generate_key().decode())
    db = _reload(
        {
            "CASHPILOT_DATA_DIR": str(data),
            "CASHPILOT_ENCRYPTION_KEY_FILE": str(_secret(tmp_path, Fernet.generate_key().decode())),
        }
    )
    with pytest.raises(RuntimeError, match="CASHPILOT_ENCRYPTION_KEY_FILE"):
        db.verify_encryption_key_matches()


def test_a_wrong_variable_is_refused(tmp_path: Path):
    _database_with(tmp_path, Fernet.generate_key().decode())
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_ENCRYPTION_KEY": Fernet.generate_key().decode()})
    with pytest.raises(RuntimeError, match="comes from CASHPILOT_ENCRYPTION_KEY,"):
        db.verify_encryption_key_matches()


def test_a_restore_without_its_key_is_refused_and_the_new_key_is_not_kept(tmp_path: Path):
    """The restore trap: the database came back, the key did not. A new key used to be minted and kept."""
    _database_with(tmp_path, Fernet.generate_key().decode())
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    assert (tmp_path / ".fernet_key").exists()  # minted at import, as before
    with pytest.raises(RuntimeError, match="no key was found") as caught:
        db.verify_encryption_key_matches()
    assert "The new key was not kept" in str(caught.value)
    assert not (tmp_path / ".fernet_key").exists()


def test_one_value_that_decrypts_is_enough(tmp_path: Path):
    """Old values next to re-entered ones: the owner chose to start over on a new key."""
    key = Fernet.generate_key().decode()
    _database_with(tmp_path, Fernet.generate_key().decode(), key)
    (tmp_path / ".fernet_key").write_text(key)
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    db.verify_encryption_key_matches()


def test_the_one_value_that_decrypts_is_found_past_any_sample(tmp_path: Path):
    """Many values from an old key before the one re-entered: the check reads them all, never a sample."""
    key = Fernet.generate_key().decode()
    _database_with(tmp_path, *[Fernet.generate_key().decode()] * 50, key)
    (tmp_path / ".fernet_key").write_text(key)
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    db.verify_encryption_key_matches()


def test_a_database_with_no_credentials_starts_on_any_key(tmp_path: Path):
    _database_with(tmp_path)
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    db.verify_encryption_key_matches()
    assert (tmp_path / ".fernet_key").exists()


def test_a_fresh_install_starts(tmp_path: Path):
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    db.verify_encryption_key_matches()


def test_the_owner_can_start_anyway_on_purpose(tmp_path: Path, caplog):
    _database_with(tmp_path, Fernet.generate_key().decode())
    with caplog.at_level("WARNING"):
        db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_ACCEPT_UNREADABLE_CREDENTIALS": "true"})
        db.verify_encryption_key_matches()
    assert (tmp_path / ".fernet_key").exists()
    assert any("Starting anyway" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# The data folder's copy, once the key comes from outside
# ---------------------------------------------------------------------------


def test_a_copy_left_in_the_data_folder_can_be_removed(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    key = Fernet.generate_key().decode()
    (data / ".fernet_key").write_text(key)
    db = _reload({"CASHPILOT_DATA_DIR": str(data), "CASHPILOT_ENCRYPTION_KEY_FILE": str(_secret(tmp_path, key))})
    status = db.encryption_key_status()
    assert status["data_copy"] == "same" and status["removable"] and not status["outside"]
    db.remove_data_folder_key()
    assert not (data / ".fernet_key").exists()
    assert db.encryption_key_status()["outside"]


def test_a_different_key_in_the_data_folder_is_never_removed(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    (data / ".fernet_key").write_text(Fernet.generate_key().decode())
    key = Fernet.generate_key().decode()
    db = _reload({"CASHPILOT_DATA_DIR": str(data), "CASHPILOT_ENCRYPTION_KEY_FILE": str(_secret(tmp_path, key))})
    assert db.encryption_key_status()["data_copy"] == "different"
    with pytest.raises(ValueError):
        db.remove_data_folder_key()
    assert (data / ".fernet_key").exists()


def test_the_only_copy_is_never_removed(tmp_path: Path):
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path)})
    assert db.encryption_key_status()["source"] == "data"
    with pytest.raises(ValueError):
        db.remove_data_folder_key()
    assert (tmp_path / ".fernet_key").exists()


def test_a_variable_with_the_same_key_lets_the_data_folder_copy_go(tmp_path: Path):
    """The variable loses to the file while the file exists; with the same key, the file can go."""
    key = Fernet.generate_key().decode()
    (tmp_path / ".fernet_key").write_text(key)
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_ENCRYPTION_KEY": key})
    status = db.encryption_key_status()
    assert status["source"] == "data" and status["env_same"] and status["removable"]
    db.remove_data_folder_key()
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_ENCRYPTION_KEY": key})
    assert db.encryption_key_status()["source"] == "env" and db.encryption_key_status()["outside"]
    assert not (tmp_path / ".fernet_key").exists()


def test_a_key_file_gone_since_the_start_keeps_the_data_folder_copy(tmp_path: Path):
    """The secret was unmounted after the start: the data folder's copy is the only one left."""
    data = tmp_path / "data"
    data.mkdir()
    key = Fernet.generate_key().decode()
    (data / ".fernet_key").write_text(key)
    secret = _secret(tmp_path, key)
    db = _reload({"CASHPILOT_DATA_DIR": str(data), "CASHPILOT_ENCRYPTION_KEY_FILE": str(secret)})
    assert db.encryption_key_status()["removable"]  # the positive control
    secret.unlink()
    assert not db.encryption_key_status()["removable"]
    with pytest.raises(ValueError):
        db.remove_data_folder_key()
    assert (data / ".fernet_key").exists()
    secret.write_text(Fernet.generate_key().decode())
    assert not db.encryption_key_status()["removable"]


def test_a_key_file_inside_the_data_folder_is_not_outside_it(tmp_path: Path):
    """CASHPILOT_ENCRYPTION_KEY_FILE naming the data folder's own file: removing the copy would remove the key."""
    key = Fernet.generate_key().decode()
    (tmp_path / ".fernet_key").write_text(key)
    db = _reload({"CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_ENCRYPTION_KEY_FILE": str(tmp_path / ".fernet_key")})
    status = db.encryption_key_status()
    assert status["source"] == "file" and not status["removable"] and not status["outside"]
    with pytest.raises(ValueError):
        db.remove_data_folder_key()
    assert (tmp_path / ".fernet_key").exists()
    db = _reload(
        {"CASHPILOT_DATA_DIR": str(tmp_path), "CASHPILOT_ENCRYPTION_KEY_FILE": str(_secret(tmp_path, key, "in-data"))}
    )
    assert not db.encryption_key_status()["outside"]


def test_a_key_file_that_is_not_text_keeps_the_data_folder_copy(tmp_path: Path):
    data = tmp_path / "data"
    data.mkdir()
    key = Fernet.generate_key().decode()
    (data / ".fernet_key").write_text(key)
    secret = _secret(tmp_path, key)
    db = _reload({"CASHPILOT_DATA_DIR": str(data), "CASHPILOT_ENCRYPTION_KEY_FILE": str(secret)})
    assert db.encryption_key_status()["removable"]  # the positive control
    secret.write_bytes(b"\xff\xfe not a key")
    assert not db.encryption_key_status()["removable"]
