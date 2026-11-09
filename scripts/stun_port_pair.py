#!/usr/bin/env python3
"""Does the router in front of this machine keep UDP source ports, or rewrite some?

A Mysterium node advertises the UDP ports it listens on and expects buyers'
packets to reach it, and its answers to leave, on those same ports. Some
routers keep a port's number only for some ports: a few fibre boxes reserve
ports in pairs (P and P XOR 1), so once one of a pair is in use the other
leaves with a random number. The node's own reachability check still passes,
because inbound traffic works; the sessions fail.

This sends a STUN binding request from pairs of neighbouring source ports and
prints the port the internet saw for each. Every port should come back with
its own number. Run it in the node's network namespace (docs/guides/mysterium.md,
"Routers that rewrite UDP source ports"), on a Linux host with Docker Engine
(Docker Desktop's own NAT rewrites every port), with no other dependency than
Python 3. From the root of a CashPilot checkout:

    docker run --rm --network container:cashpilot-mysterium \\
      -v "$PWD/scripts/stun_port_pair.py:/t.py:ro" python:3.15.2-alpine python /t.py

or fetch the script to /tmp first, as the guide shows.

Exit status: 0 when every pair was tested and every port kept its number,
1 when one was rewritten, 2 when no STUN server answered, 3 when no port was
rewritten but some pair could not be tested in full (a port that did not bind
or got no answer), so the pairing was not checked: run it again with another
--start, and 4 when --start and --pairs do not give real ports (1 to 65535). A
rewritten port is reported as a pairing
router when some ports kept their number, and as a NAT that rewrites every
port when none did. Read-only: it sends a few UDP packets to a public STUN
server and changes nothing.
"""

from __future__ import annotations

import argparse
import os
import socket
import struct
import sys
from typing import NoReturn

MAGIC = 0x2112A442
SERVERS = [("stun.l.google.com", 19302), ("stun.cloudflare.com", 3478)]


def _mapped_port(data: bytes, txid: bytes) -> int | None:
    """The port in a STUN binding success response, or None."""
    if len(data) < 20:
        return None
    kind, length, cookie = struct.unpack("!HHI", data[:8])
    if kind != 0x0101 or cookie != MAGIC or data[8:20] != txid:
        return None
    pos, end = 20, min(len(data), 20 + length)
    plain = None
    while pos + 4 <= end:
        attr, size = struct.unpack("!HH", data[pos : pos + 4])
        value = data[pos + 4 : pos + 4 + size]
        if attr == 0x0020 and len(value) >= 4:  # XOR-MAPPED-ADDRESS
            return struct.unpack("!H", value[2:4])[0] ^ (MAGIC >> 16)
        if attr == 0x0001 and len(value) >= 4:  # MAPPED-ADDRESS
            plain = struct.unpack("!H", value[2:4])[0]
        pos += 4 + size + (-size % 4)
    return plain


def probe(sock: socket.socket, server: tuple[str, int], tries: int = 3) -> int | None:
    """The source port the STUN server saw for packets from ``sock``; None for no answer.

    A network error (no route, the packet refused) is no answer too, never a
    traceback, which would exit 1 and read as a rewritten port.
    """
    for _ in range(tries):
        txid = os.urandom(12)
        try:
            sock.sendto(struct.pack("!HHI", 0x0001, 0, MAGIC) + txid, server)
            while True:
                data, _ = sock.recvfrom(2048)
                port = _mapped_port(data, txid)
                if port is not None:
                    return port
        except TimeoutError:
            continue
        except OSError:
            return None
    return None


def _servers() -> list[tuple[str, int]]:
    """Every STUN server in SERVERS that resolves, in order."""
    found = []
    for host, port in SERVERS:
        try:
            found.append((socket.gethostbyname(host), port))
        except OSError:
            continue
    return found


def run(server: tuple[str, int], start: int, pairs: int) -> tuple[int, int, int]:
    """Test ``pairs`` neighbouring pairs from ``start`` against one server.

    Returns (ports answered, ports rewritten, pairs with both ports answered).
    """
    first = start & ~1
    rewritten = answered = complete = 0
    socks = []
    try:
        for n in range(pairs):
            even = first + 2 * n
            both = True
            # The odd port first, then its even partner while the first is still
            # open: a router that reserves pairs gives the second one away.
            for port in (even + 1, even):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(2)
                socks.append(sock)
                try:
                    # A client socket on a chosen source port, so the test knows
                    # which port it sent from; it only sends to the STUN server.
                    sock.bind(("0.0.0.0", port))
                except OSError as exc:
                    print(f"{port}: could not bind ({exc.strerror}), skipped")
                    both = False
                    continue
                seen = probe(sock, server)
                if seen is None:
                    print(f"{port}: no answer")
                    both = False
                    continue
                answered += 1
                kept = seen == port
                rewritten += not kept
                print(f"{port} -> {seen}  {'kept' if kept else 'REWRITTEN'}")
            complete += both
    finally:
        for sock in socks:
            sock.close()
    return answered, rewritten, complete


class _Parser(argparse.ArgumentParser):
    """argparse with its own exit status for bad arguments, 4: its usual 2 means no STUN answer here."""

    def error(self, message: str) -> NoReturn:
        """Print the usage and the problem, then exit 4."""
        self.print_usage(sys.stderr)
        self.exit(4, f"{self.prog}: error: {message}\n")


def main() -> int:
    """Run the test against the first STUN server that answers; the exit status is the verdict."""
    parser = _Parser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", type=int, default=34100, help="first port to test (default 34100)")
    parser.add_argument("--pairs", type=int, default=4, help="neighbouring pairs to test (default 4)")
    args = parser.parse_args()
    first = args.start & ~1
    if args.pairs < 1 or first < 1 or first + 2 * args.pairs - 1 > 65535:
        parser.error("--start and --pairs must give ports from 1 to 65535 (pairs start on an even port)")
    servers = _servers()
    if not servers:
        print("No STUN server could be resolved: check this namespace's DNS.")
        return 2
    answered = rewritten = complete = 0
    for server in servers:
        answered, rewritten, complete = run(server, args.start, args.pairs)
        if answered:
            break
        print(f"No answer from {server[0]}:{server[1]}.")
    if not answered:
        print("No STUN server answered: outbound UDP may be blocked.")
        return 2
    if rewritten == answered:
        print(
            f"\nAll {answered} ports left with a different number. Something in the path rewrites "
            "every UDP source port: a symmetric NAT, carrier-grade NAT, a VPN, or Docker Desktop's "
            "own NAT (run this on a Linux host with Docker Engine, not Docker Desktop). This "
            "only measures ports with no forward: whether a forward of UDP_PORTS reaches the "
            "node is a separate check (the node's own port check, and none works behind "
            "carrier-grade NAT or a VPN)."
        )
        return 1
    if rewritten:
        print(
            f"\n{rewritten} of {answered} ports left with a different number while others kept "
            "theirs. The router rewrites some UDP source ports (some fibre boxes reserve ports in "
            "pairs), and a Mysterium node behind it fails its sessions. Run it again: a pairing "
            "router rewrites some port every time, while a rare clash in this machine's own NAT "
            "does not repeat (the guide shows how to check the host)."
        )
        return 1
    if complete < args.pairs:
        print(
            f"\nEvery port that answered kept its number, but only {complete} of {args.pairs} pairs "
            "were tested in full, so the pairing was not checked. Run it again with another --start."
        )
        return 3
    print(f"\nAll {answered} ports kept their number.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
