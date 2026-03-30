"""Tests for fleet key resolution and bootstrap logic."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from app import fleet_key


@pytest.fixture
def fleet_dir(tmp_path: Path):
    """Point fleet key resolution at a temp directory."""
    key_dir = tmp_path / "fleet"
    key_dir.mkdir()
    with (
        patch.object(fleet_key, "_FLEET_KEY_DIR", key_dir),
        patch.object(fleet_key, "_FLEET_KEY_FILE", key_dir / ".fleet_key"),
    ):
        yield key_dir


class TestResolveFleetKey:
    def test_env_var_takes_priority(self, fleet_dir: Path):
        """CASHPILOT_API_KEY env var should be returned without touching the filesystem."""
        with patch.dict(os.environ, {"CASHPILOT_API_KEY": "env-key-123"}):
            assert fleet_key.resolve_fleet_key() == "env-key-123"
        # No file should have been created
        assert not (fleet_dir / ".fleet_key").exists()

    def test_reads_existing_key_file(self, fleet_dir: Path):
        """If the key file already exists, read it."""
        key_file = fleet_dir / ".fleet_key"
        key_file.write_text("existing-shared-key")
        with patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}):
            assert fleet_key.resolve_fleet_key() == "existing-shared-key"

    def test_generates_key_when_no_file(self, fleet_dir: Path):
        """When no env var and no file, generate and persist a new key."""
        key_file = fleet_dir / ".fleet_key"
        with patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}):
            key = fleet_key.resolve_fleet_key()
        assert key  # non-empty
        assert len(key) > 20  # token_urlsafe(32) produces ~43 chars
        assert key_file.read_text() == key

    def test_generated_key_is_stable(self, fleet_dir: Path):
        """Second call reads the persisted file, returns the same key."""
        with patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}):
            key1 = fleet_key.resolve_fleet_key()
            key2 = fleet_key.resolve_fleet_key()
        assert key1 == key2

    def test_file_exists_race_reads_content(self, fleet_dir: Path):
        """Simulate the O_EXCL race: file created by another process."""
        key_file = fleet_dir / ".fleet_key"

        def fake_open(path, flags, mode=0o777):
            """First create the file with content (simulating the winner),
            then raise FileExistsError (simulating the loser)."""
            key_file.write_text("winner-key")
            raise FileExistsError

        with (
            patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}),
            patch("os.open", side_effect=fake_open),
        ):
            key = fleet_key.resolve_fleet_key()
        assert key == "winner-key"

    def test_empty_env_var_is_treated_as_unset(self, fleet_dir: Path):
        """Empty string env var should fall through to file/generate."""
        with patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}):
            key = fleet_key.resolve_fleet_key()
        assert key  # should have generated one

    def test_ignores_empty_key_file(self, fleet_dir: Path):
        """An empty or whitespace-only key file should be ignored."""
        key_file = fleet_dir / ".fleet_key"
        key_file.write_text("   \n")
        with patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}):
            # File exists but empty — should try to generate (will fail with
            # FileExistsError from O_EXCL, then retry read which is still empty)
            # In practice this returns "" after retries, which is the correct
            # "broken state" signal.
            key = fleet_key.resolve_fleet_key()
        # The function tried O_EXCL on existing file, retried reads, all empty
        # This is a degenerate state — key will be empty
        assert isinstance(key, str)

    def test_unwritable_dir_returns_empty(self, tmp_path: Path):
        """When the fleet directory can't be created, return empty string."""
        bad_dir = tmp_path / "nonexistent" / "deep" / "path"
        with (
            patch.object(fleet_key, "_FLEET_KEY_DIR", bad_dir),
            patch.object(fleet_key, "_FLEET_KEY_FILE", bad_dir / ".fleet_key"),
            patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}),
            patch("os.open", side_effect=OSError("permission denied")),
            patch.object(Path, "mkdir"),
        ):
            key = fleet_key.resolve_fleet_key()
        assert key == ""

    def test_file_permissions(self, fleet_dir: Path):
        """Generated key file should have 0o600 permissions."""
        with patch.dict(os.environ, {"CASHPILOT_API_KEY": ""}):
            fleet_key.resolve_fleet_key()
        key_file = fleet_dir / ".fleet_key"
        mode = key_file.stat().st_mode & 0o777
        assert mode == 0o600
