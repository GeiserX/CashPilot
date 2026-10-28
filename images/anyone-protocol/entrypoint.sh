#!/bin/sh
# CashPilot's Anyone Protocol relay: check the two things that stop a relay
# running as anond from starting, say how to fix them, then exec anon as
# PID 1 so `docker stop` (SIGTERM) shuts it down cleanly.
#
# Every anonrc written for the vendor image says `User anond`, which tells anon
# to switch to that user. Already running as anond, with no capabilities, anon
# fails to set its groups and then crashes (free(): invalid size, 0.4.10.2).
# `--User ""` on the command line overrides that line, and keeps overriding it
# after a SIGHUP reload, so an existing anonrc works unedited.
#
# It never chowns or chmods anything: it has no capability to, and needs none.
set -eu

CONF=/etc/anon/anonrc
DATA=/var/lib/anon

log() { echo "[cashpilot-anyone] $*" >&2; }
die() {
	log "ERROR: $*"
	exit 1
}

if [ "${1:-}" = anon ]; then
	[ -r "$CONF" ] || die "no readable $CONF. Write your anonrc into the volume mounted at /etc/anon first (it needs AgreeToTerms 1), owned by uid 100, gid 101: https://github.com/GeiserX/CashPilot/blob/main/docs/guides/anyone-protocol.md"
	[ -w "$DATA" ] || die "$DATA is not writable by anond (uid 100, gid 101); it is owned by $(stat -c %u:%g "$DATA"). Run once on the host: chown -R 100:101 <the directory or volume mounted at $DATA>"
	log "$(anon --version | head -n1), running as $(id -un) ($(id -u):$(id -g))"
	exec "$@" --User ""
fi

exec "$@"
