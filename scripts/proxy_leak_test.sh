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
#      8.8.8.8, never shows up as a plain UDP lookup on the box's own stack;
#   f. a public name that resolves to a private address (a nip.io name for a
#      server on the proxy's own network) does not reach that server: the
#      name is resolved inside the tunnel and the private address is dropped;
#   g. an address in 100.64.0.0/10 that is local to the namespace (a tailnet
#      node's own address, where tailscaled's PeerAPI listens) is not reachable
#      over loopback.
#
# Every leak check first runs once against a deliberately opened namespace
# (the sidecar's firewall table deleted and a default route put back) and must
# see the leak there, so a check that cannot fail is caught.
#
# Usage: TUNNEL_IMAGE=cashpilot-tunnel:test LAN_PROBE=<a LAN address> scripts/proxy_leak_test.sh
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

# host_dns_mentions <seconds> <name> -> how many plain UDP DNS packets on the
# box's own network stack (every interface of the Docker host) carry <name>.
# Other DNS traffic on the box is ignored, so only the canary counts.
host_dns_mentions() {
    local secs=$1 name=$2
    docker run --rm --network=host --cap-drop ALL --cap-add NET_RAW --cap-add NET_ADMIN "$P-tcpdump-img" \
        timeout "$secs" tcpdump -n -i any -l -A "udp port 53" 2>/dev/null | grep -c "${name%%.*}" || true
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
# with no UDP at all). tun2proxy sends every lookup through the proxy as DNS
# over TCP (--dns over-tcp), so the canary must never appear as a plain UDP
# lookup on the box's own network stack, which is the way a lookup that left
# from the box itself would go. The proxy runs on this same box, so its own
# TCP lookup on the earner's behalf is on the box too; that one is the
# intended path, and the capture leaves TCP out.
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

# f. A name the proxy could resolve to its own LAN. The target is a plain HTTP
# server on the proxy's network, named through nip.io (a public name that
# resolves to the address written in it). Resolved by the proxy, as tun2proxy's
# virtual DNS did, the name reaches the server; resolved inside the tunnel, the
# earner gets the private address and the tunnel drops it.
docker run -d --name "$P-lan" --network "$NET" "$ALPINE" \
    sh -c 'while true; do printf "HTTP/1.0 200 OK\r\n\r\ncpmp-lan-secret" | nc -l -p 80; done' >/dev/null
LAN_IP=$(docker inspect "$P-lan" -f "{{(index .NetworkSettings.Networks \"$NET\").IPAddress}}")
LAN_NAME="$(printf %s "$LAN_IP" | tr . -).nip.io"
reaches_lan_name() { earner curl -s -m 6 "http://$LAN_NAME/" 2>/dev/null | grep -q cpmp-lan-secret; }
for variant in "socks5 - 1081" "http - 8081"; do
    set -- $variant
    start_gost
    start_pair "$1" "$2" "$3"
    if reaches_lan_name; then
        fail "$1:$3 f: $LAN_NAME reached the proxy's own network"
    else
        pass "$1:$3 f: $LAN_NAME (a name for $LAN_IP) does not reach the proxy's own network"
    fi
done
# Its control: the same earner, with the tunnel's address rules gone but its
# route still into the tunnel, reaches the server through the proxy.
docker exec "$P-tun" sh -c 'nft flush chain inet cashpilot out && nft add rule inet cashpilot out accept'
if reaches_lan_name; then pass "control: the name check sees $LAN_NAME through the proxy once the tunnel allows it"; else fail "control: the name check could not reach $LAN_NAME even with the tunnel open"; fi

# g. A tailnet address local to the namespace. On a Tailscale tunnel the node's
# own 100.x address is local, so the earner's connection to it goes over
# loopback, past the rules on tailscale0. Simulated here on a SOCKS tunnel:
# an address in 100.64.0.0/10 on lo, a listener on it in the namespace.
start_gost
start_pair socks5 - 1081
docker exec "$P-tun" ip addr add 100.101.0.1/32 dev lo
docker run -d --name "$P-peer" --network "container:$P-tun" --cap-drop ALL "$ALPINE" \
    sh -c 'while true; do printf "HTTP/1.0 200 OK\r\n\r\ncpmp-peerapi" | nc -l -s 100.101.0.1 -p 9999; done' >/dev/null
sleep 1
reaches_peer() { earner curl -s -m 4 http://100.101.0.1:9999/ 2>/dev/null | grep -q cpmp-peerapi; }
if reaches_peer; then fail "g: the earner reached 100.101.0.1 on loopback"; else pass "g: the earner cannot reach a 100.64.0.0/10 address on loopback"; fi
docker exec "$P-tun" sh -c 'nft -a list chain inet cashpilot out | sed -n "s/.*100.64.0.0\/10 drop # handle \([0-9]*\)/\1/p" | xargs -I{} nft delete rule inet cashpilot out handle {}'
if reaches_peer; then pass "control: the loopback check reaches 100.101.0.1 once its rule is gone"; else fail "control: the loopback check could not reach 100.101.0.1 even without its rule"; fi
docker rm -f "$P-peer" >/dev/null

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
