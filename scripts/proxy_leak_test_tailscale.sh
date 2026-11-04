#!/usr/bin/env bash
# Proves a Tailscale proxied copy fails closed, without touching a real tailnet
# (docs/proxies.md, "Tailscale exit nodes").
#
# A pinned headscale is the control server, a tailscale container is the exit
# node (approved through headscale's own CLI), and the tunnel sidecar plus a
# curl container stand in for a proxied copy. Never run on a production box.
#
#   a. the earner reaches the internet, and a capture on the namespace's real
#      interface sees none of that traffic in the clear: it went through the
#      exit node, inside WireGuard;
#   b. with the exit node stopped, the earner reaches nothing and the capture
#      sees no packet to the targets it tried;
#   c. with the exit node deleted from the control server (its route gone from
#      the netmap: the case where userspace mode dials from the box itself),
#      the same;
#   d. with no exit node set at all, the firewall alone holds;
#   control: the same checks against a namespace opened on purpose must see
#      the leak.
#
# Usage: TUNNEL_IMAGE=cashpilot-tunnel:test LAN_PROBE=192.168.10.1 scripts/proxy_leak_test_tailscale.sh
set -euo pipefail

TUNNEL_IMAGE=${TUNNEL_IMAGE:?set TUNNEL_IMAGE to the tunnel image to test}
LAN_PROBE=${LAN_PROBE:-192.168.1.1}
HEADSCALE=headscale/headscale:0.29.7@sha256:11f81665e842809db9fe3006a38c56a66e968baa5abd4bac498e86445572b970
TAILSCALE=tailscale/tailscale:v1.104.4@sha256:ed6480b33c6eb67c9cbd203ed42b9fb57e361986725b6856def71b7a3d9e276c
CURL=curlimages/curl:8.17.0@sha256:935d9100e9ba842cdb060de42472c7ca90cfe9a7c96e4dacb55e79e560b3ff40
ALPINE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
NET=cpmp-tstest
P=cpmp-ts
WORK=$(mktemp -d)

FAILS=0
pass() { echo "PASS  $*"; }
fail() {
    echo "FAIL  $*"
    FAILS=$((FAILS + 1))
}
cleanup() {
    docker ps -aq --filter "name=^${P}-" | xargs -r docker rm -fv >/dev/null 2>&1 || true
    docker network rm "$NET" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap 'jobs -p | xargs -r kill 2>/dev/null; cleanup' EXIT
cleanup
WORK=$(mktemp -d)

docker network create --driver bridge --subnet 10.233.7.0/24 "$NET" >/dev/null
HS_IP=10.233.7.10
docker build -q -t "$P-tcpdump-img" - >/dev/null <<EOF
FROM $ALPINE
RUN apk add --no-cache tcpdump
EOF

# --- control server ---
mkdir -p "$WORK/hs"
cat >"$WORK/hs/config.yaml" <<EOF
server_url: http://$HS_IP:8080
listen_addr: 0.0.0.0:8080
metrics_listen_addr: 127.0.0.1:9090
grpc_listen_addr: 127.0.0.1:50443
noise:
  private_key_path: /var/lib/headscale/noise_private.key
prefixes:
  v4: 100.64.0.0/10
  v6: fd7a:115c:a1e0::/48
derp:
  server:
    enabled: false
  urls:
    - https://controlplane.tailscale.com/derpmap/default
  auto_update_enabled: false
disable_check_updates: true
database:
  type: sqlite
  sqlite:
    path: /var/lib/headscale/db.sqlite
dns:
  magic_dns: false
  override_local_dns: false
  nameservers:
    global: []
unix_socket: /var/run/headscale/headscale.sock
unix_socket_permission: "0770"
policy:
  mode: file
  path: ""
EOF
# Copied in rather than bind-mounted: a VM-backed Docker (colima, Docker
# Desktop) may not share the host's temp directory.
docker create --name "$P-hs" --network "$NET" --ip "$HS_IP" "$HEADSCALE" serve >/dev/null
docker cp "$WORK/hs/." "$P-hs:/etc/headscale"
docker start "$P-hs" >/dev/null
for _ in $(seq 1 20); do
    docker exec "$P-hs" headscale users list >/dev/null 2>&1 && break
    sleep 1
done
docker exec "$P-hs" headscale users list >/dev/null 2>&1 || { docker logs "$P-hs" 2>&1 | tail -5; exit 1; }
hs() { docker exec "$P-hs" headscale "$@"; }
hs users create cashpilot >/dev/null
USER_ID=$(hs users list -o json | sed -n 's/.*"id": *\([0-9]*\).*/\1/p' | head -1)
KEY=$(hs preauthkeys create --user "$USER_ID" --reusable --ephemeral --expiration 1h | tail -1 | tr -d '\r ')

# --- exit node ---
start_exit() {
    docker rm -f "$P-exit" >/dev/null 2>&1 || true
    docker run -d --name "$P-exit" --network "$NET" --cap-add NET_ADMIN --cap-add NET_RAW --device /dev/net/tun \
        --sysctl net.ipv4.ip_forward=1 -e TS_AUTHKEY="$KEY" -e TS_HOSTNAME=cpmp-exit -e TS_USERSPACE=false \
        -e TS_EXTRA_ARGS="--login-server=http://$HS_IP:8080 --advertise-exit-node" -e TS_STATE_DIR=/tmp "$TAILSCALE" >/dev/null
    for _ in $(seq 1 30); do
        EXIT_IP=$(docker exec "$P-exit" tailscale ip -4 2>/dev/null || true)
        [ -n "$EXIT_IP" ] && break
        sleep 1
    done
    EXIT_ID=$(hs nodes list -o json | tr -d '\n ' | sed -n 's/.*"id":\([0-9]*\),[^}]*"name":"cpmp-exit".*/\1/p')
    [ -n "$EXIT_ID" ] || EXIT_ID=$(hs nodes list | awk '/cpmp-exit/ {print $1; exit}')
    hs nodes approve-routes --identifier "$EXIT_ID" --routes 0.0.0.0/0,::/0 >/dev/null
}
start_exit
echo "exit node $EXIT_IP (headscale id $EXIT_ID)"

# --- the proxied copy ---
docker create --name "$P-tun" --network "$NET" --init --cap-drop ALL --cap-add NET_ADMIN \
    --device /dev/net/tun --security-opt no-new-privileges:true --read-only --tmpfs /run:size=8m \
    -v /run/cashpilot-secret --sysctl net.ipv6.conf.all.disable_ipv6=1 \
    --sysctl net.ipv6.conf.default.disable_ipv6=1 --sysctl net.ipv4.conf.all.route_localnet=1 \
    "$TUNNEL_IMAGE" >/dev/null
d="$WORK/secret"
mkdir -p "$d"
printf tailscale >"$d/kind"
printf %s "$KEY" >"$d/auth_key"
printf %s "$EXIT_IP" >"$d/exit_node"
printf cashpilot-leaktest >"$d/hostname"
printf %s "http://$HS_IP:8080" >"$d/login_server"
chmod 0400 "$d"/*
{ tar --owner=0 --group=0 -C "$d" -cf - . 2>/dev/null || tar --uid 0 --gid 0 -C "$d" -cf - .; } |
    docker cp - "$P-tun:/run/cashpilot-secret/"
docker start "$P-tun" >/dev/null
for _ in $(seq 1 60); do
    docker exec "$P-tun" test -f /run/ready 2>/dev/null && break
    sleep 1
done
if docker exec "$P-tun" test -f /run/ready; then
    pass "tunnel ready through the exit node: $(docker exec "$P-tun" cat /run/ready)"
else
    fail "tunnel never became ready"
    docker logs "$P-tun" 2>&1 | tail -15
fi
docker run -d --name "$P-earner" --network "container:$P-tun" --cap-drop ALL \
    --security-opt no-new-privileges:true --entrypoint sleep "$CURL" infinity >/dev/null
earner() { docker exec "$P-earner" "$@"; }

# Packets on the namespace's real interface to the targets the earner tries.
clear_packets() {
    (sleep 2; earner curl -s -m 5 http://1.1.1.1 >/dev/null 2>&1; earner curl -s -m 5 "http://$LAN_PROBE" >/dev/null 2>&1) &
    docker run --rm --network "container:$P-tun" --cap-drop ALL --cap-add NET_RAW --cap-add NET_ADMIN "$P-tcpdump-img" \
        timeout 14 tcpdump -n -i eth0 -Q out -l "host 1.1.1.1 or host $LAN_PROBE or tcp port 80" 2>/dev/null | grep -c . || true
}
reaches() { earner curl -s -o /dev/null -m 6 http://1.1.1.1; }

# a.
if reaches; then pass "a: earner reaches 1.1.1.1"; else fail "a: earner cannot reach 1.1.1.1 through the exit node"; fi
n=$(clear_packets)
[ "$n" = 0 ] && pass "a: none of it left eth0 in the clear (it went through the exit node)" || fail "a: $n packets left eth0 in the clear"

# b. exit node stopped
docker stop -t 1 "$P-exit" >/dev/null
sleep 3
if reaches; then fail "b: earner still reaches 1.1.1.1 with the exit node stopped"; else pass "b: earner reaches nothing with the exit node stopped"; fi
n=$(clear_packets)
[ "$n" = 0 ] && pass "b: 0 packets to the earner's targets left eth0" || fail "b: $n packets left eth0 with the exit node stopped"

# c. exit node deleted from the control server: its route leaves the netmap
docker start "$P-exit" >/dev/null
sleep 5
hs nodes delete --identifier "$EXIT_ID" --force >/dev/null 2>&1 || true
docker stop -t 1 "$P-exit" >/dev/null
sleep 8
docker exec "$P-tun" tailscale --socket=/run/ts/ts.sock status 2>&1 | head -3 | sed 's/^/      /'
if reaches; then fail "c: earner reaches 1.1.1.1 with the exit node gone from the netmap"; else pass "c: earner reaches nothing with the exit node gone from the netmap"; fi
n=$(clear_packets)
[ "$n" = 0 ] && pass "c: 0 packets to the earner's targets left eth0" || fail "c: $n packets left eth0 with the exit node gone"

# d. no exit node set at all (tailscaled routes to the real interface): only
#    the firewall stands between the earner and the box's own connection.
docker exec "$P-tun" tailscale --socket=/run/ts/ts.sock set --exit-node= >/dev/null
sleep 2
if reaches; then fail "d: earner reaches 1.1.1.1 with no exit node set"; else pass "d: the firewall alone holds with no exit node set"; fi
n=$(clear_packets)
[ "$n" = 0 ] && pass "d: 0 packets to the earner's targets left eth0" || fail "d: $n packets left eth0 with no exit node set"

# control: delete the firewall too, and the same checks must see the leak.
docker exec "$P-tun" nft delete table inet cashpilot
if reaches; then pass "control: an opened namespace reaches 1.1.1.1 directly"; else fail "control: the opened namespace did not reach 1.1.1.1"; fi
n=$(clear_packets)
[ "$n" != 0 ] && pass "control: the capture sees $n packets from an opened namespace" || fail "control: the capture saw nothing from an opened namespace"

if docker inspect "$P-tun" | grep -qF "$KEY"; then fail "docker inspect of the tunnel shows the auth key"; else pass "docker inspect of the tunnel has no auth key"; fi

echo
if [ "$FAILS" -eq 0 ]; then echo "ALL PASSED"; else echo "$FAILS FAILED"; exit 1; fi
