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

# The container's memory limit in MB, from cgroup v2 or v1; fails when there is
# none ("max" on v2, a near-2^63 sentinel on v1).
limit_mb() {
	v=$(cat /sys/fs/cgroup/memory.max 2>/dev/null || cat /sys/fs/cgroup/memory/memory.limit_in_bytes 2>/dev/null) || return 1
	case $v in '' | *[!0-9]*) return 1 ;; esac
	[ "${#v}" -lt 16 ] || return 1
	echo $((v / 1048576))
}

if [ "${1:-}" = anon ]; then
	[ -r "$CONF" ] || die "no readable $CONF. Write your anonrc into the volume mounted at /etc/anon first (it needs AgreeToTerms 1), owned by uid 100, gid 101: https://github.com/GeiserX/CashPilot/blob/main/docs/guides/anyone-protocol.md"
	[ -w "$DATA" ] || die "$DATA is not writable by anond (uid 100, gid 101); it is owned by $(stat -c %u:%g "$DATA"). Run once on the host: chown -R 100:101 <the directory or volume mounted at $DATA>"
	log "$(anon --version | head -n1), running as $(id -un) ($(id -u):$(id -g))"
	# anon sizes its cell queues from the host's RAM (3/4 of it), not from the
	# container's memory limit, so a busy relay on a big host grows its queues
	# past the limit and the kernel kills it. Unless anonrc sets MaxMemInQueues
	# itself, cap the queues at half the limit (anon's floor is 256 MB), which
	# leaves the other half for everything else anon holds.
	if ! grep -qiE '^[[:space:]]*MaxMemInQueues[[:space:]]' "$CONF" && mb=$(limit_mb); then
		queues=$((mb / 2))
		[ "$queues" -ge 256 ] || queues=256
		log "container memory limit ${mb} MB: MaxMemInQueues ${queues} MB (set it in anonrc to choose your own)"
		set -- "$@" --MaxMemInQueues "$queues MB"
	fi
	exec "$@" --User ""
fi

exec "$@"
