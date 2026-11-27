"""The backup block in docs/backup-restore.md must leave every file private.

``cashpilot.db`` holds the encrypted credentials, the password hashes and the
earnings, and ``.fernet_key`` decrypts the credentials. The block used to
``chmod 600`` only the keys, so with the usual umask 022 the database came out
644 and the directory 755. This runs the block as written, with a stand-in for
``docker`` that writes world-readable files, and checks the result.
"""

from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "docs" / "backup-restore.md"

FAKE_DOCKER = """
docker() {
  if [ "$1" = exec ]; then printf 'db'; else printf 'key' > "$3"; chmod 644 "$3"; fi
}
"""


def _backup_block() -> str:
    text = PAGE.read_text(encoding="utf-8")
    backup = text[text.index("## Backup") :]
    return re.search(r"```bash\n(.*?)```", backup, re.S).group(1)


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_the_backup_block_leaves_the_set_private(tmp_path):
    block = _backup_block()
    assert 'OUT="cashpilot-backup-' in block, "found the wrong block"
    script = "umask 022\n" + FAKE_DOCKER + block + '\necho "umask=$(umask)"\n'
    result = subprocess.run(["bash", "-c", script], cwd=tmp_path, capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert "umask=0022" in result.stdout, "the block changed the caller's umask"
    (out,) = [p for p in tmp_path.iterdir() if p.name.startswith("cashpilot-backup-")]
    assert stat.S_IMODE(out.stat().st_mode) == 0o700
    files = sorted(os.listdir(out))
    assert files == [".fernet_key", ".secret_key", "cashpilot.db"]
    for name in files:
        mode = stat.S_IMODE((out / name).stat().st_mode)
        assert mode == 0o600, f"{name} is {oct(mode)}"
