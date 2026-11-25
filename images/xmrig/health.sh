#!/bin/sh
# Docker health check: healthy while XMRig's local HTTP API answers and its
# pool connection has been up for at least a second. A miner that cannot reach
# its pool (DNS blocked, wrong port, pool down) reports "pool": "" and uptime 0,
# so it shows unhealthy instead of idling silently. Needs --http-port=18088 on
# the command (the API binds 127.0.0.1 by default). It does not prove shares
# are accepted; the pool's dashboard shows that.
summary=$(wget -qO- -T 5 http://127.0.0.1:18088/2/summary) || exit 1
# /2/summary is indented JSON, one key per line; read "uptime" inside the
# "connection" object, not the miner's own uptime above it.
printf '%s\n' "$summary" | awk '
	/"connection":/ { inside = 1; next }
	inside && /"uptime":/ { gsub(/[^0-9]/, ""); up = $0 + 0; exit }
	END { exit !(up > 0) }
'
