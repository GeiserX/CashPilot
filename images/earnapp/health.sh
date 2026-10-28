#!/usr/bin/env bash
# Docker health check. It proves that `earnapp start` ran and left the status
# "enabled", and that an `earnapp run` process is alive right now. It cannot
# prove the device registered or is online: EarnApp's log is encrypted and the
# status file says "enabled" even when registration failed.
grep -qx enabled /etc/earnapp/status || exit 1
for d in /proc/[0-9]*; do
	tr '\0' ' ' <"$d/cmdline" 2>/dev/null | grep -q '^/usr/bin/earnapp run' && exit 0
done
exit 1
