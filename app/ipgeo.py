"""Which network (ASN) an address belongs to, and the country it is registered in.

Local only. The UI downloads iptoasn.com's ip2asn-combined table (public
domain, PDDL v1.0, about 11 MB) into its own SQLite file beside the main
database, and every lookup reads that file. No address is ever sent to a third
party, from the server or from the browser.

The country is where the network is REGISTERED, not where the address is: a
global provider registered in the US reads US everywhere. The Activity page
labels it that way.

Keys are 32 hex digits of the IPv6 form, IPv4 as ::ffff:a.b.c.d, so one ordered
text column covers both families and a range lookup is one index probe.
"""

from __future__ import annotations

import contextlib
import gzip
import ipaddress
import logging
import os
import sqlite3
import threading
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

from app import database

logger = logging.getLogger(__name__)

DEFAULT_URL = "https://iptoasn.com/data/ip2asn-combined.tsv.gz"
#: Refresh when the table is older than this, and only while a worker is opted in.
MAX_AGE_SECONDS = 7 * 86400
DOWNLOAD_TIMEOUT = 120
#: A real table has hundreds of thousands of ranges; far fewer means a bad file.
MIN_ROWS = 1000
#: Caps, so a bad upstream (or a gzip bomb) cannot fill /data, the volume that
#: holds the main database. The real file is about 11 MB and 600k ranges.
MAX_DOWNLOAD_BYTES = 64 * 1024 * 1024
MAX_ROWS = 3_000_000
#: The same for the decompressed stream: a small gzip can expand without
#: bound. The real table is about 40 MB unpacked, its lines under 200 bytes,
#: and every line parses.
MAX_TABLE_BYTES = 512 * 1024 * 1024
MAX_LINE_BYTES = 4096
MAX_BAD_LINES = 1000

_lock = threading.Lock()


class DownloadBusy(RuntimeError):
    """A download is already running."""


def source_url() -> str:
    """Where the table comes from; empty disables the download."""
    return os.getenv("CASHPILOT_ACTIVITY_ASN_URL", DEFAULT_URL).strip()


def db_path() -> Path:
    return database.DB_DIR / "ipgeo.sqlite"


def key(ip: str) -> str | None:
    """The 32-hex key of an address (IPv4 mapped into IPv6), or None."""
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    if isinstance(addr, ipaddress.IPv4Address):
        addr = ipaddress.IPv6Address("::ffff:" + str(addr))
    return addr.packed.hex()


def _bounded_lines(f: Any) -> Any:
    """Lines of a binary stream, refusing an over-long line or too many bytes in all."""
    total = 0
    while line := f.readline(MAX_LINE_BYTES + 1):
        if len(line) > MAX_LINE_BYTES:
            raise ValueError("a line is longer than any in the real table")
        total += len(line)
        if total > MAX_TABLE_BYTES:
            raise ValueError("the table unpacks to more than the real one")
        yield line


def _rows(lines: Any) -> Any:
    bad = 0
    for raw in lines:
        line = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else raw
        parts = line.rstrip("\n").split("\t")
        start = end = None
        asn = -1
        if len(parts) >= 5:
            start, end = key(parts[0]), key(parts[1])
            with contextlib.suppress(ValueError):
                asn = int(parts[2])
        if start is None or end is None or asn < 0:
            bad += 1
            if bad > MAX_BAD_LINES:
                raise ValueError("too many lines that are not table rows")
            continue
        if asn == 0:
            continue  # AS 0: not routed, nothing to name
        cc = parts[3].strip().upper()
        # The table writes "None" or "Unknown" where no country is registered.
        cc = cc if len(cc) == 2 and cc.isalpha() else ""
        yield start, end, asn, cc, parts[4].strip()[:64]


def build(lines: Any, target: Path | None = None) -> int:
    """Write the table from TSV lines to a temp file, then move it into place.

    Returns the number of ranges. Raises ValueError on a file that is too small
    to be the real table, leaving the existing one untouched.
    """
    target = target or db_path()
    tmp = target.with_suffix(".sqlite.tmp")
    with contextlib.suppress(FileNotFoundError):
        tmp.unlink()
    conn = sqlite3.connect(str(tmp))
    try:
        conn.execute(
            "CREATE TABLE ranges (start TEXT PRIMARY KEY, end TEXT NOT NULL, asn INTEGER, cc TEXT, name TEXT) WITHOUT ROWID"
        )
        conn.execute("CREATE TABLE meta (k TEXT PRIMARY KEY, v TEXT)")
        n = 0
        batch = []
        for row in _rows(lines):
            if n + len(batch) >= MAX_ROWS:
                raise ValueError("the table has more ranges than the real one")
            batch.append(row)
            if len(batch) >= 5000:
                conn.executemany("INSERT OR REPLACE INTO ranges VALUES (?, ?, ?, ?, ?)", batch)
                n += len(batch)
                batch = []
        if batch:
            conn.executemany("INSERT OR REPLACE INTO ranges VALUES (?, ?, ?, ?, ?)", batch)
            n += len(batch)
        if n < MIN_ROWS:
            raise ValueError("the table is too small to be the real one")
        conn.execute("INSERT INTO meta VALUES ('rows', ?), ('built_at', ?)", (str(n), datetime.now(UTC).isoformat()))
        conn.commit()
    except BaseException:
        conn.close()
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise
    conn.close()
    os.replace(tmp, target)
    return n


def download() -> int:
    """Fetch and build the table. Blocking: call it in a thread. One at a time."""
    url = source_url()
    if not url:
        raise RuntimeError("disabled")
    if not _lock.acquire(blocking=False):
        raise DownloadBusy("a download is already running")
    try:
        return _download(url)
    finally:
        _lock.release()


def _download(url: str) -> int:
    target = db_path()
    target.parent.mkdir(parents=True, exist_ok=True)
    gz = target.with_suffix(".tsv.gz.tmp")
    try:
        with httpx.stream("GET", url, timeout=DOWNLOAD_TIMEOUT, follow_redirects=True) as resp:
            resp.raise_for_status()
            # Redirects are followed, but never from https down to plain http.
            final = str(getattr(resp.url, "scheme", "")).lower()
            if url.lower().startswith("https://") and final != "https":
                raise ValueError("the download was redirected off https")
            size = 0
            with gz.open("wb") as f:
                for chunk in resp.iter_bytes():
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ValueError("the download is larger than the real table")
                    f.write(chunk)
        with gzip.open(gz, "rb") as f:
            return build(_bounded_lines(f))
    finally:
        with contextlib.suppress(FileNotFoundError):
            gz.unlink()


def status() -> dict[str, Any]:
    """Whether the table is present, how old it is and how many ranges it holds."""
    path = db_path()
    out: dict[str, Any] = {"present": False, "age_seconds": None, "rows": None, "download_enabled": bool(source_url())}
    if not path.is_file():
        return out
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            rows = conn.execute("SELECT v FROM meta WHERE k = 'rows'").fetchone()
        finally:
            conn.close()
    except sqlite3.Error:
        return out
    out.update(present=True, age_seconds=int(time.time() - path.stat().st_mtime), rows=int(rows[0]) if rows else None)
    return out


def needs_refresh() -> bool:
    if not source_url():
        return False
    path = db_path()
    return not path.is_file() or time.time() - path.stat().st_mtime > MAX_AGE_SECONDS


def lookup(ips: list[str]) -> dict[str, tuple[str, str]]:
    """{ip: (network label, country)} for the addresses the table knows.

    A missing or unreadable table gives an empty dict, which the page shows as
    "network tables not downloaded", never as a wrong answer.
    """
    path = db_path()
    found: dict[str, tuple[str, str]] = {}
    if not ips or not path.is_file():
        return found
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error:
        return found
    try:
        for ip in set(ips):
            k = key(ip)
            if k is None:
                continue
            row = conn.execute(
                "SELECT end, asn, cc, name FROM ranges WHERE start <= ? ORDER BY start DESC LIMIT 1", (k,)
            ).fetchone()
            if row and k <= row[0]:
                found[ip] = (f"AS{row[1]} {row[3]}".strip()[:80], row[2] or "")
    except sqlite3.Error:
        return {}
    finally:
        conn.close()
    return found
