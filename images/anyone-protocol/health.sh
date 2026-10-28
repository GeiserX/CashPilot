#!/bin/sh
# Docker health check: the anon process is alive and listening on the ORPort
# set in anonrc. It cannot prove the port is reachable from the internet, which
# the relay needs before it publishes itself; notices.log says that.
port=$(awk 'tolower($1) == "orport" { print $2; exit }' /etc/anon/anonrc 2>/dev/null)
port=${port##*:}
case "$port" in '' | *[!0-9]*) exit 1 ;; esac
hex=$(printf '%04X' "$port")
# State 0A is LISTEN. Field 2 is local address:port in hex.
awk -v p=":$hex" '$4 == "0A" && substr($2, length($2) - 4) == p { found = 1 } END { exit !found }' \
	/proc/net/tcp /proc/net/tcp6 2>/dev/null
