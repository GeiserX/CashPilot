"""CashPilot-ffsf: the one loss that cannot be undone was documented as an aside.

Backing up *node identities* has its own page. Restoring CashPilot's OWN `/data`
did not: `.fernet_key` was mentioned in three files, always in passing, never as
a procedure.

Losing that key makes every stored credential permanently undecryptable. The code
says so in three places and refuses to overwrite it for exactly that reason. It is
the single most destructive thing an operator can do to this application, and the
docs treated it as a footnote.

These tests pin the facts the page has to keep telling the truth about, because a
restore page that has drifted from the code is worse than none: it is followed.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "backup-restore.md"
MKDOCS = ROOT / "mkdocs.yml"
DATABASE = ROOT / "app" / "database.py"
AUTH = ROOT / "app" / "auth.py"


def page() -> str:
    return PAGE.read_text(encoding="utf-8")


class TestThePageExistsAndIsReachable:
    def test_it_exists(self):
        assert PAGE.is_file()

    def test_it_is_in_the_nav(self):
        """An orphaned page is reachable only by URL — the exact defect the docs
        restructure fixed. Adding another one here would be poor form."""
        assert "backup-restore.md" in MKDOCS.read_text(encoding="utf-8")

    def test_the_node_identity_page_points_at_it(self):
        """Someone looking for "backup" finds backup.md first. It is about a
        different thing, and the more destructive loss is on this page."""
        assert "backup-restore.md" in (ROOT / "docs" / "backup.md").read_text(encoding="utf-8")


class TestItNamesTheFilesThatActuallyExist:
    """Paths are quoted from the code, so a rename must break this."""

    def test_the_database_path_matches_the_code(self):
        assert 'DB_PATH = DB_DIR / "cashpilot.db"' in DATABASE.read_text(encoding="utf-8")
        assert "cashpilot.db" in page()

    def test_the_encryption_key_path_matches_the_code(self):
        assert '_FERNET_KEY_FILE = DB_DIR / ".fernet_key"' in DATABASE.read_text(encoding="utf-8")
        assert ".fernet_key" in page()

    def test_the_session_key_path_matches_the_code(self):
        assert 'key_file = data_dir / ".secret_key"' in AUTH.read_text(encoding="utf-8")
        assert ".secret_key" in page()

    @pytest.mark.parametrize("volume", ["cashpilot_data", "cashpilot_worker_data", "cashpilot_fleet"])
    def test_the_volumes_it_names_are_the_shipped_ones(self, volume):
        assert volume in (ROOT / "docker-compose.yml").read_text(encoding="utf-8")
        assert volume in page()


class TestItTellsTheTruthAboutTheConsequences:
    def test_it_says_the_credentials_are_unrecoverable(self):
        """The whole reason the page exists. Softening this to "may be affected"
        would make it advice nobody acts on."""
        text = page().lower()
        assert "permanently undecryptable" in text or "permanently unreadable" in text

    def test_it_distinguishes_the_two_keys(self):
        """They differ by one word in the env var name and one does nothing
        important. Restoring the wrong one gets you a working login and
        unreadable credentials."""
        text = page()
        assert "CASHPILOT_SECRET_KEY" in text
        assert "CASHPILOT_ENCRYPTION_KEY" in text

    def test_it_warns_the_backup_is_as_sensitive_as_the_server(self):
        """.fernet_key plus the database IS every provider credential, in a
        directory. A backup guide that does not say so invites a git commit."""
        assert "as sensitive as the server" in page()

    def test_the_secret_key_is_documented_as_optional(self):
        """MEASURED, not assumed: a live install had only .fernet_key in /data,
        because .secret_key is written only when CASHPILOT_SECRET_KEY is unset.
        The first draft's `docker cp` of it would have failed there."""
        assert "may not exist" in page()
        auth = AUTH.read_text(encoding="utf-8")
        # The code path that makes it optional: an env key short-circuits before
        # the file is ever written.
        assert 'env_key = os.getenv("CASHPILOT_SECRET_KEY", "")' in auth
        assert "return env_key" in auth


class TestTheQuotedLogLinesAreReal:
    """The page tells the reader what to look for in `docker logs`. If those
    strings drift, the reader is hunting for something that never appears."""

    def test_the_decrypt_error_is_quoted_accurately(self):
        assert "Failed to decrypt a stored credential" in DATABASE.read_text(encoding="utf-8")
        assert "Failed to decrypt a stored credential" in page()

    def test_the_schema_lines_are_quoted_accurately(self):
        db = DATABASE.read_text(encoding="utf-8")
        assert "Schema now at version %d (was %d)" in db
        assert "Schema at version %d; no migration needed this boot." in db
        text = page()
        assert "Schema now at version" in text
        assert "no migration needed this boot" in text


class TestTheCommandsAreShapedidempotently:
    def test_the_restore_does_not_hard_require_the_optional_key(self):
        """The live install has no .secret_key, so an unconditional `cp` of it
        aborts the whole restore under `&&`."""
        restore = page()[page().index("## Restore") :]
        assert "/backup/.secret_key" in restore
        assert "[ -f /backup/.secret_key ]" in restore, "the optional key is copied unconditionally"

    def test_the_backup_tolerates_a_missing_secret_key(self):
        backup = page()[page().index("## Backup") : page().index("## Restore")]
        line = next(ln for ln in backup.splitlines() if ".secret_key" in ln and "docker cp" in ln)
        assert "2>/dev/null" in line, line

    def test_it_verifies_the_backup_rather_than_assuming_it(self):
        """An untested backup is a hope."""
        assert "integrity_check" in page()
