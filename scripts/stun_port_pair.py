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

Exit status: 0 when every port kept its number, 1 when one was rewritten,
2 when no STUN server answered. A rewritten port is reported as a pairing
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
    """The source port the STUN server saw for packets from ``sock``."""
    for _ in range(tries):
        txid = os.urandom(12)
        sock.sendto(struct.pack("!HHI", 0x0001, 0, MAGIC) + txid, server)
        try:
            while True:
                data, _ = sock.recvfrom(2048)
                port = _mapped_port(data, txid)
                if port is not None:
                    return port
        except TimeoutError:
            continue
    return None


def _server() -> tuple[str, int] | None:
    for host, port in SERVERS:
        try:
            return (socket.gethostbyname(host), port)
        except OSError:
            continue
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--start", type=int, default=34100, help="first port to test (default 34100)")
    parser.add_argument("--pairs", type=int, default=4, help="neighbouring pairs to test (default 4)")
    args = parser.parse_args()
    server = _server()
    if server is None:
        print("No STUN server could be resolved: check this namespace's DNS.")
        return 2
    first = args.start & ~1
    rewritten = answered = 0
    socks = []
    try:
        for n in range(args.pairs):
            even = first + 2 * n
            # The odd port first, then its even partner while the first is still
            # open: a router that reserves pairs gives the second one away.
            for port in (even + 1, even):
                sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                sock.settimeout(2)
                socks.append(sock)
                try:
                    sock.bind(("0.0.0.0", port))
                except OSError as exc:
                    print(f"{port}: could not bind ({exc.strerror}), skipped")
                    continue
                seen = probe(sock, server)
                if seen is None:
                    print(f"{port}: no answer")
                    continue
                answered += 1
                kept = seen == port
                rewritten += not kept
                print(f"{port} -> {seen}  {'kept' if kept else 'REWRITTEN'}")
    finally:
        for sock in socks:
            sock.close()
    if not answered:
        print(f"No answer from {server[0]}:{server[1]}: outbound UDP may be blocked.")
        return 2
    if rewritten == answered:
        print(
            f"\nAll {answered} ports left with a different number. Something in the path rewrites "
            "every UDP source port: a symmetric NAT, carrier-grade NAT, a VPN, or Docker Desktop's "
            "own NAT (run this on a Linux host with Docker Engine, not Docker Desktop). Port "
            "forwarding cannot work through it either."
        )
        return 1
    if rewritten:
        print(
            f"\n{rewritten} of {answered} ports left with a different number while others kept "
            "theirs. The router rewrites some UDP source ports (some fibre boxes reserve ports in "
            "pairs), and a Mysterium node behind it fails its sessions."
        )
        return 1
    print(f"\nAll {answered} ports kept their number.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
