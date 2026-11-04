#!/usr/bin/env bash
# Proves a proxied copy fails closed (docs/proxies.md, "How the guarantee is tested").
#
# Runs against a real Docker daemon, so run it only on a disposable Docker host. It starts a
# pinned gost as the proxy, then for each proxy type a tunnel sidecar plus a
# curl container standing in for the earner, joined to the sidecar's network
# namespace exactly as the worker joins them. For each one it checks:
#
#   a. the earner reaches the internet through the proxy;
#   b. with the proxy stopped, the earner reaches nothing: not 1.1.1.1, not the
#      bridge gateway, not a LAN address, and a capture on the namespace's only
#      real interface sees no packet except to the proxy;
#   c. with tun2proxy frozen (SIGSTOP), the same;
#   d. with tun2proxy killed, the sidecar exits and the earner is left with
#      loopback only;
#   e. a DNS canary name, looked up through Docker's resolver and straight at
#      8.8.8.8, never shows up on the box's own uplink.
#
# Every leak check first runs once against a deliberately opened namespace
# (the sidecar's firewall table deleted and a default route put back) and must
# see the leak there, so a check that cannot fail is caught.
#
# Usage: TUNNEL_IMAGE=cashpilot-tunnel:test LAN_PROBE=192.168.10.1 scripts/proxy_leak_test.sh
set -euo pipefail

TUNNEL_IMAGE=${TUNNEL_IMAGE:?set TUNNEL_IMAGE to the tunnel image to test}
LAN_PROBE=${LAN_PROBE:-192.168.1.1}
GOST=gogost/gost:3.3.3@sha256:f266f957c6e4f8d433ed23202a5745fa4969d08f3f0ef034fb9357345e16ad67
CURL=curlimages/curl:8.17.0@sha256:935d9100e9ba842cdb060de42472c7ca90cfe9a7c96e4dacb55e79e560b3ff40
ALPINE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
NET=cpmp-leaktest
P=cpmp-lt

FAILS=0
pass() { echo "PASS  $*"; }
fail() {
    echo "FAIL  $*"
    FAILS=$((FAILS + 1))
}

cleanup() {
    docker ps -aq --filter "name=^${P}-" | xargs -r docker rm -fv >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
}
trap 'jobs -p | xargs -r kill 2>/dev/null; cleanup' EXIT
cleanup

docker network create --driver bridge "$NET" >/dev/null
GW=$(docker network inspect "$NET" -f '{{(index .IPAM.Config 0).Gateway}}')

# A capture tool for the checks, never part of what ships.
docker build -q -t "$P-tcpdump-img" - >/dev/null <<EOF
FROM $ALPINE
RUN apk add --no-cache tcpdump
EOF

start_gost() {
    docker rm -f "$P-gost" >/dev/null 2>&1 || true
    docker run -d --name "$P-gost" --network "$NET" "$GOST" \
        -L "socks5://u1:p%40ss@:1080" -L "http://u1:p%40ss@:8080" -L "socks5://:1081" -L "http://:8081" >/dev/null
    sleep 1
}

# host_dns_mentions <seconds> <name> -> how many DNS packets on the box's own
# network stack (every interface of the Docker host) carry <name>. Other DNS
# traffic on the box is ignored, so only the canary counts.
host_dns_mentions() {
    local secs=$1 name=$2
    docker run --rm --network=host --cap-drop ALL --cap-add NET_RAW --cap-add NET_ADMIN "$P-tcpdump-img" \
        timeout "$secs" tcpdump -n -i any -l -A "udp port 53 or tcp port 53" 2>/dev/null | grep -c "${name%%.*}" || true
}

start_pair() { # kind auth port  (auth is "user:pass@", percent-encoded, or "-" for none)
    local kind=$1 auth=$2 port=$3 d
    [ "$auth" = - ] && auth=""
    docker rm -fv "$P-earner" "$P-tun" >/dev/null 2>&1 || true
    docker create --name "$P-tun" --network "$NET" --init --cap-drop ALL --cap-add NET_ADMIN \
        --device /dev/net/tun --security-opt no-new-privileges:true --read-only --tmpfs /run:size=1m \
        -v /run/cashpilot-secret --sysctl net.ipv6.conf.all.disable_ipv6=1 \
        --sysctl net.ipv6.conf.default.disable_ipv6=1 --sysctl net.ipv4.conf.all.route_localnet=1 \
        "$TUNNEL_IMAGE" >/dev/null
    d=$(mktemp -d)
    printf %s "$kind" >"$d/kind"
    printf %s "$GOST_IP" >"$d/proxy_ip"
    printf %s "$port" >"$d/proxy_port"
    printf %s "$kind" >"$d/proxy_scheme"
    printf %s "$auth" >"$d/proxy_auth"
    chmod 0400 "$d"/*
    # Owned by root, as the worker writes them: the sidecar's root has no
    # CAP_DAC_OVERRIDE and cannot read a 0400 file it does not own.
    { tar --owner=0 --group=0 -C "$d" -cf - . 2>/dev/null || tar --uid 0 --gid 0 -C "$d" -cf - .; } |
        docker cp - "$P-tun:/run/cashpilot-secret/"
    rm -rf "$d"
    docker start "$P-tun" >/dev/null
    for _ in $(seq 1 45); do
        docker exec "$P-tun" test -f /run/ready 2>/dev/null && break
        sleep 1
    done
    docker run -d --name "$P-earner" --network "container:$P-tun" --cap-drop ALL \
        --security-opt no-new-privileges:true --entrypoint sleep "$CURL" infinity >/dev/null
}

earner() { docker exec "$P-earner" "$@"; }

# Can the earner reach anything that is not the proxy? 0 = it reached something.
earner_escapes() {
    earner curl -s -o /dev/null -m 4 http://1.1.1.1 && return 0
    earner curl -s -o /dev/null -m 4 "http://$LAN_PROBE" && return 0
    return 1
}

# Count packets that LEAVE the namespace's only real interface (-Q out) for
# anything but the proxy, while the earner tries every way out it has. Inbound
# packets (the gateway's ICMP redirects, other containers' IPv6 router
# solicitations) are not leaks and are not counted.
stray_packets_eth0() {
    local port=$1
    (sleep 2; earner curl -s -m 4 http://1.1.1.1 >/dev/null 2>&1; earner curl -s -m 4 "http://$LAN_PROBE" >/dev/null 2>&1
     earner curl -s -m 4 "http://$GW" >/dev/null 2>&1; earner nslookup example.com 8.8.8.8 >/dev/null 2>&1) &
    docker run --rm --network "container:$P-tun" --cap-drop ALL --cap-add NET_RAW --cap-add NET_ADMIN "$P-tcpdump-img" \
        timeout 14 tcpdump -n -i eth0 -Q out -l "not arp and not (host $GOST_IP and tcp port $port)" 2>/dev/null >"$STRAY_LOG" || true
    # Packet lines only: docker run can add an empty line when timeout ends it.
    grep -c . "$STRAY_LOG" || true
}
STRAY_LOG=$(mktemp)

open_namespace() { # the positive control: undo the sidecar's protection
    docker exec "$P-tun" sh -c "nft delete table inet cashpilot; ip route replace default via $GW dev eth0"
}

start_gost
GOST_IP=$(docker inspect "$P-gost" -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}")

for variant in "socks5 u1:p%40ss@ 1080" \
               "http u1:p%40ss@ 8080" \
               "socks5 - 1081" \
               "http - 8081"; do
    set -- $variant
    kind=$1 url=$2 port=$3
    label="$kind:$port"
    start_gost
    start_pair "$kind" "$url" "$port"

    # a. through the proxy
    if exit_ip=$(earner curl -fsS -m 10 https://api.ipify.org) && [ -n "$exit_ip" ]; then
        pass "$label a: earner reaches the internet through the proxy (exit $exit_ip)"
    else
        fail "$label a: earner could not reach the internet through the proxy"
        docker logs "$P-tun" 2>&1 | tail -5
    fi

    # a2. the tunnel log names no destination the earner reached
    n=$(docker logs "$P-tun" 2>&1 | grep -c -e Beginning -e ipify || true)
    [ "$n" = 0 ] && pass "$label a2: the tunnel log names no session or destination" || fail "$label a2: the tunnel log has $n session lines"

    # b. proxy dead
    docker stop -t 1 "$P-gost" >/dev/null
    if earner_escapes; then fail "$label b: earner reached something with the proxy stopped"; else pass "$label b: earner reaches nothing with the proxy stopped"; fi
    n=$(stray_packets_eth0 "$port")
    [ "$n" = 0 ] && pass "$label b: 0 packets left eth0 except to the proxy" || { fail "$label b: $n packets left eth0 to something other than the proxy"; cat "$STRAY_LOG"; }
    start_gost

    # c. tun2proxy frozen
    start_pair "$kind" "$url" "$port"
    docker exec "$P-tun" sh -c 'kill -STOP $(for p in /proc/[0-9]*; do [ "$(cat $p/comm 2>/dev/null)" = tun2proxy-bin ] && basename $p; done)'
    if earner_escapes; then fail "$label c: earner reached something with tun2proxy frozen"; else pass "$label c: earner reaches nothing with tun2proxy frozen"; fi
    n=$(stray_packets_eth0 "$port")
    [ "$n" = 0 ] && pass "$label c: 0 packets left eth0 except to the proxy" || { fail "$label c: $n stray packets with tun2proxy frozen"; cat "$STRAY_LOG"; }

    # d. tun2proxy killed: the sidecar exits and takes the namespace with it
    start_pair "$kind" "$url" "$port"
    docker exec "$P-tun" sh -c 'kill -KILL $(for p in /proc/[0-9]*; do [ "$(cat $p/comm 2>/dev/null)" = tun2proxy-bin ] && basename $p; done)' || true
    sleep 2
    ifaces=$(earner sh -c 'ls /sys/class/net' 2>/dev/null | tr '\n' ' ' || true)
    state=$(docker inspect "$P-tun" -f '{{.State.Status}}')
    if [ "$state" != running ] && ! earner curl -s -o /dev/null -m 4 http://1.1.1.1; then
        pass "$label d: tun2proxy killed, sidecar $state, earner interfaces: ${ifaces:-none}"
    else
        fail "$label d: sidecar $state after tun2proxy was killed, earner interfaces: $ifaces"
    fi
done

# e. DNS canary, on the last variant's settings (plain HTTP CONNECT, the case
# with no UDP at all). The canary must not appear anywhere on the box's own
# network stack. Only lookups are made: tun2proxy answers them inside the
# tunnel (virtual DNS) and hands the name to the proxy when a connection is
# opened, so the proxy resolving a name is the intended path. Here the proxy
# runs on this same box, so a connection would put its lookup on the capture.
start_gost
start_pair http - 8081
canary="leak-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n').example.com"
( host_dns_mentions 16 "$canary" >/tmp/cpmp-host-dns.$$ ) &
cap=$!
sleep 3
earner nslookup "$canary" >/dev/null 2>&1 || true
earner nslookup "$canary" 8.8.8.8 >/dev/null 2>&1 || true
wait $cap
n=$(cat /tmp/cpmp-host-dns.$$)
rm -f /tmp/cpmp-host-dns.$$
[ "$n" = 0 ] && pass "e: the canary name appears in 0 DNS packets on the box's own stack" || fail "e: the canary name appears in $n DNS packets on the box's own stack"

# Positive controls: the same checks against a namespace opened on purpose.
open_namespace
if earner_escapes; then pass "control: the escape check sees an opened namespace"; else fail "control: the escape check missed an opened namespace"; fi
n=$(stray_packets_eth0 8081)
[ "$n" != 0 ] && pass "control: the capture sees $n stray packets from an opened namespace" || fail "control: the capture saw nothing from an opened namespace"
( host_dns_mentions 12 "ctl-$canary" >/tmp/cpmp-host-dns.$$ ) &
cap=$!
sleep 3
earner nslookup "ctl-$canary" 8.8.8.8 >/dev/null 2>&1 || true
wait $cap
n=$(cat /tmp/cpmp-host-dns.$$)
rm -f /tmp/cpmp-host-dns.$$
[ "$n" != 0 ] && pass "control: the host capture sees the control canary in $n DNS packets from an opened namespace" || fail "control: the host capture missed the control canary from an opened namespace"

# No secret in what Docker records for the sidecar.
start_pair socks5 u1:p%40ss@ 1080
if docker inspect "$P-tun" | grep -q 'p%40ss\|p@ss'; then fail "docker inspect of the sidecar shows the proxy password"; else pass "docker inspect of the sidecar has no proxy password"; fi

echo
if [ "$FAILS" -eq 0 ]; then echo "ALL PASSED"; else echo "$FAILS FAILED"; exit 1; fi
