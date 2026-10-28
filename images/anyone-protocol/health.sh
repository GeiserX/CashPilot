#!/bin/sh
# Docker health check: the anon process is alive and listening on an ORPort
# set in anonrc. ORPort lines marked NoListen only advertise a port (the usual
# port-forward setup) and are skipped: anon never binds them. It cannot prove
# the port is reachable from the internet, which the relay needs before it
# publishes itself; notices.log says that.
ports=$(awk 'tolower($1) == "orport" && tolower($0) !~ /nolisten/ { print $2 }' /etc/anon/anonrc 2>/dev/null)
for port in $ports; do
	port=${port##*:}
	case "$port" in '' | *[!0-9]*) continue ;; esac
	hex=$(printf '%04X' "$port")
	# State 0A is LISTEN. Field 2 is local address:port in hex.
	awk -v p=":$hex" '$4 == "0A" && substr($2, length($2) - 4) == p { found = 1 } END { exit !found }' \
		/proc/net/tcp /proc/net/tcp6 2>/dev/null && exit 0
done
exit 1
