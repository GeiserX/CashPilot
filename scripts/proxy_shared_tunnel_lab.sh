#!/usr/bin/env bash
# Proves that copies sharing one tunnel still fail closed, and measures what the
# shared tunnel saves (docs/proxies.md, "One tunnel per proxy").
#
# Like scripts/proxy_leak_test_tailscale.sh it runs a pinned headscale as the
# control server and a tailscale container as the exit node, never a real
# tailnet. Run it only on a disposable Docker host: it removes every container
# labelled cashpilot.managed=true on that host.
#
# Part 1, the namespace: one tunnel, two earners in it.
#   a.  both earners reach the internet, and none of it leaves the tunnel's
#       real interface in the clear;
#   s.  stopping earner A does not interrupt earner B (a request every half
#       second from B, while A stops and starts);
#   t.  neither earner reaches another tailnet node;
#   n.  a random DNS name looked up by an earner never appears on the box;
#   r.  while the tunnel restarts, neither earner has an interface to send on;
#       restarted (what the heartbeat does), both reach the internet again;
#   b.  exit node stopped, k. tailscaled frozen, then killed, d. no exit node
#       set: neither earner reaches 1.1.1.1 or a LAN address, and the capture
#       sees no packet to them.
#   Negative controls, each must turn its check red:
#   c1. the tunnel's firewall deleted and a default route back;
#   c2. a copy created on the bridge instead of inside the tunnel;
#   c3. a tunnel image whose output policy is accept instead of drop.
#
# Part 2, the worker's own code (scripts/proxy_shared_tunnel_lab.py), for the
# tree under test and, when BASE_SRC names a checkout of the base branch, for
# that one too: deploy N=1 and N=7 copies, count the tunnels, measure the
# cgroup memory of tunnels and earners, check every copy reaches the internet
# and, with the exit node stopped, none does. With this tree there must be one
# tunnel per proxy; with the base branch the same check fails (7 tunnels).
#
# Part 3, migration: copies deployed by BASE_SRC (one tunnel each) are moved by
# this tree's migrate_legacy into one tunnel, and still reach the internet.
#
# Part 4, what must never cost a copy (needs DOCKERD_RESTART, a command that
# restarts the Docker daemon the lab talks to):
#   r.  a daemon restart with 3 copies, one stopped by its owner: the tunnel
#       comes back ready by itself, the heartbeat starts the other two, the
#       stopped one stays stopped, and a start of it works. With PREV_SRC (a
#       tree whose tunnel's settings volume is a bind with no source) the same
#       check must fail: that is the control that shows it can;
#   e.  an edited proxy (a second auth key) while 3 copies run: the tunnel and
#       every copy keep their container ids, a file written inside a copy is
#       still there, and every copy reaches the internet again;
#   m.  the worker killed the moment a copy's clone would take its name during
#       a tunnel replacement: no copy is lost, and the next heartbeat leaves one
#       tunnel with all 3 copies under their names, reaching the internet.
#
# Usage: TUNNEL_IMAGE=drumsergio/cashpilot-tunnel:<v> LAN_PROBE=<a LAN address> \
#        [BASE_SRC=<checkout of the base branch>] [SRC=<tree under test>] [PARTS="1 2 3 4"] \
#        [DOCKERD_RESTART="<command>"] [PREV_SRC=<tree for the part 4 control>] \
#        scripts/proxy_shared_tunnel_lab.sh
set -euo pipefail

TUNNEL_IMAGE=${TUNNEL_IMAGE:?set TUNNEL_IMAGE to the tunnel image to test}
LAN_PROBE=${LAN_PROBE:-192.168.1.1}
HERE=$(cd "$(dirname "$0")/.." && pwd)
SRC=${SRC:-$HERE}
BASE_SRC=${BASE_SRC:-}
PARTS=${PARTS:-1 2 3 4}
DOCKERD_RESTART=${DOCKERD_RESTART:-}
PREV_SRC=${PREV_SRC:-}
PYTHON=${PYTHON:-python3}
HEADSCALE=headscale/headscale:0.29.7@sha256:11f81665e842809db9fe3006a38c56a66e968baa5abd4bac498e86445572b970
TAILSCALE=tailscale/tailscale:v1.104.4@sha256:ed6480b33c6eb67c9cbd203ed42b9fb57e361986725b6856def71b7a3d9e276c
CURL=curlimages/curl:8.17.0@sha256:935d9100e9ba842cdb060de42472c7ca90cfe9a7c96e4dacb55e79e560b3ff40
ALPINE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
NET=cpst-net
P=cpst
WORK=$(mktemp -d)

FAILS=0
pass() { echo "PASS  $*"; }
fail() {
    echo "FAIL  $*"
    FAILS=$((FAILS + 1))
}
wipe_copies() { docker ps -aq --filter label=cashpilot.managed=true | xargs -r docker rm -fv >/dev/null 2>&1 || true; }
cleanup() {
    docker ps -aq --filter "name=^${P}-" | xargs -r docker rm -fv >/dev/null 2>&1 || true
    wipe_copies
    docker network rm "$NET" >/dev/null 2>&1 || true
    rm -rf "$WORK"
}
trap 'jobs -p | xargs -r kill 2>/dev/null; cleanup' EXIT
cleanup
WORK=$(mktemp -d)

docker network create --driver bridge --subnet 10.233.9.0/24 "$NET" >/dev/null
HS_IP=10.233.9.10
docker build -q -t "$P-tcpdump-img" - >/dev/null <<EOF
FROM $ALPINE
RUN apk add --no-cache tcpdump
EOF
docker pull -q "$TUNNEL_IMAGE" >/dev/null
docker pull -q "$CURL" >/dev/null

# --- control server (as in proxy_leak_test_tailscale.sh) ---
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
docker create --name "$P-hs" --network "$NET" --ip "$HS_IP" "$HEADSCALE" serve >/dev/null
docker cp "$WORK/hs/." "$P-hs:/etc/headscale"
docker start "$P-hs" >/dev/null
for _ in $(seq 1 20); do
    docker exec "$P-hs" headscale users list >/dev/null 2>&1 && break
    sleep 1
done
hs() { docker exec "$P-hs" headscale "$@"; }
hs users create cashpilot >/dev/null
USER_ID=$(hs users list -o json | sed -n 's/.*"id": *\([0-9]*\).*/\1/p' | head -1)
KEY=$(hs preauthkeys create --user "$USER_ID" --reusable --ephemeral --expiration 2h | tail -1 | tr -d '\r ')

start_exit() {
    docker rm -f "$P-exit" >/dev/null 2>&1 || true
    docker run -d --name "$P-exit" --network "$NET" --cap-add NET_ADMIN --cap-add NET_RAW --device /dev/net/tun \
        --sysctl net.ipv4.ip_forward=1 -e TS_AUTHKEY="$KEY" -e TS_HOSTNAME=cpst-exit -e TS_USERSPACE=false \
        -e TS_EXTRA_ARGS="--login-server=http://$HS_IP:8080 --advertise-exit-node" -e TS_STATE_DIR=/tmp "$TAILSCALE" >/dev/null
    for _ in $(seq 1 30); do
        EXIT_IP=$(docker exec "$P-exit" tailscale ip -4 2>/dev/null || true)
        [ -n "$EXIT_IP" ] && break
        sleep 1
    done
    EXIT_ID=$(hs nodes list -o json | tr -d '\n ' | sed -n 's/.*"id":\([0-9]*\),[^}]*"name":"cpst-exit".*/\1/p')
    [ -n "$EXIT_ID" ] || EXIT_ID=$(hs nodes list | awk '/cpst-exit/ {print $1; exit}')
    hs nodes approve-routes --identifier "$EXIT_ID" --routes 0.0.0.0/0,::/0 >/dev/null
    docker exec -d "$P-exit" sh -c 'while true; do printf "HTTP/1.0 200 OK\r\n\r\nhi" | nc -l -p 8000; done'
}
start_exit
echo "exit node $EXIT_IP (headscale id $EXIT_ID)"

# A tunnel container exactly as the worker creates one (app/proxy_tunnel.py sidecar_kwargs).
new_tunnel() { # name image [exit_node]
    local name=$1 image=$2 exit=${3-$EXIT_IP} d
    docker rm -fv "$name" >/dev/null 2>&1 || true
    docker create --name "$name" --network "$NET" --init --cap-drop ALL --cap-add NET_ADMIN \
        --device /dev/net/tun --security-opt no-new-privileges:true --read-only --tmpfs /run:size=8m \
        -v /run/cashpilot-secret --sysctl net.ipv6.conf.all.disable_ipv6=1 \
        --sysctl net.ipv6.conf.default.disable_ipv6=1 --sysctl net.ipv4.conf.all.route_localnet=1 \
        "$image" >/dev/null
    d="$WORK/secret-$name"
    rm -rf "$d"
    mkdir -p "$d"
    printf tailscale >"$d/kind"
    printf %s "$KEY" >"$d/auth_key"
    printf %s "$exit" >"$d/exit_node"
    printf %s "cashpilot-$name" >"$d/hostname"
    printf %s "http://$HS_IP:8080" >"$d/login_server"
    chmod 0400 "$d"/*
    { tar --owner=0 --group=0 -C "$d" -cf - . 2>/dev/null || tar --uid 0 --gid 0 -C "$d" -cf - .; } |
        docker cp - "$name:/run/cashpilot-secret/"
    docker start "$name" >/dev/null
}
wait_ready() { # name [seconds]
    for _ in $(seq 1 "${2:-60}"); do
        docker exec "$1" test -f /run/ready 2>/dev/null && return 0
        sleep 1
    done
    return 1
}
new_earner() { # name tunnel
    docker rm -fv "$1" >/dev/null 2>&1 || true
    docker run -d --name "$1" --network "container:$2" --cap-drop ALL \
        --security-opt no-new-privileges:true --entrypoint sleep "$CURL" infinity >/dev/null
}
reaches() { docker exec "$1" curl -s -o /dev/null -m 6 http://1.1.1.1; }
escapes() { # earner: reaches 1.1.1.1 or the LAN probe?
    docker exec "$1" curl -s -o /dev/null -m 4 http://1.1.1.1 && return 0
    docker exec "$1" curl -s -o /dev/null -m 4 "http://$LAN_PROBE" && return 0
    return 1
}
# Packets that leave the tunnel's real interface toward what the earners try.
clear_packets() { # tunnel earner...
    local tun=$1
    shift
    (sleep 2; for e in "$@"; do docker exec "$e" curl -s -m 4 http://1.1.1.1 >/dev/null 2>&1
        docker exec "$e" curl -s -m 4 "http://$LAN_PROBE" >/dev/null 2>&1; done) &
    local out rc
    out=$(docker run --rm --network "container:$tun" --cap-drop ALL --cap-add NET_RAW --cap-add NET_ADMIN "$P-tcpdump-img" \
        timeout $((8 + 9 * $#)) tcpdump -n -i eth0 -Q out -l "host 1.1.1.1 or host $LAN_PROBE or tcp port 80" \
        2>"$WORK/tcpdump.err")
    rc=$?
    wait
    # A working capture ends at the timeout: 124, or 0 when tcpdump exits
    # cleanly on timeout's SIGTERM. Anything else (no image, no interface, no
    # permission) means no capture ran, and a count of 0 would pass the check.
    if [ "$rc" -ne 0 ] && [ "$rc" -ne 124 ]; then
        echo "no-capture(exit $rc: $(tail -1 "$WORK/tcpdump.err"))"
        return
    fi
    printf '%s' "$out" | grep -c . || true
}
# How many packets on the tunnel's real interface carry a DNS name the earners look up.
dns_mentions() { # tunnel name earner...
    local tun=$1 name=$2
    shift 2
    (sleep 2; for e in "$@"; do docker exec "$e" nslookup "$name" >/dev/null 2>&1
        docker exec "$e" nslookup "$name" 8.8.8.8 >/dev/null 2>&1; done) &
    local out rc
    out=$(docker run --rm --network "container:$tun" --cap-drop ALL --cap-add NET_RAW --cap-add NET_ADMIN "$P-tcpdump-img" \
        timeout $((6 + 12 * $#)) tcpdump -n -i eth0 -l -A "udp port 53 or tcp port 53" 2>"$WORK/tcpdump.err")
    rc=$?
    wait
    if [ "$rc" -ne 0 ] && [ "$rc" -ne 124 ]; then # as in clear_packets: no capture is never a count of 0
        echo "no-capture(exit $rc: $(tail -1 "$WORK/tcpdump.err"))"
        return
    fi
    printf '%s' "$out" | grep -c "${name%%.*}" || true
}
# The fail-closed verdict for a set of earners: no escape, no packet. 0 = closed.
# Returns 0 closed, 1 a leak seen, 2 the capture itself failed (so a negative
# control can tell "the checks saw the leak" from "the checks did not run").
closed() { # label tunnel earner...
    local label=$1 tun=$2 e n bad=0
    shift 2
    for e in "$@"; do
        if escapes "$e"; then echo "      $label: $e escaped"; bad=1; fi
    done
    n=$(clear_packets "$tun" "$@")
    if ! [[ "$n" =~ ^[0-9]+$ ]]; then
        echo "      $label: capture failed: $n"
        return 2
    fi
    if [ "$n" != 0 ]; then echo "      $label: $n packets left eth0"; bad=1; fi
    return $bad
}
# What the worker requires of every copy: it lives in its tunnel's namespace.
joined() { # earner tunnel
    [ "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$1")" = "container:$(docker inspect -f '{{.Id}}' "$2")" ]
}

if [[ " $PARTS " == *" 1 "* ]]; then
    echo "== part 1: two earners in one tunnel"
    TUN=$P-tun
    new_tunnel "$TUN" "$TUNNEL_IMAGE"
    if wait_ready "$TUN"; then pass "tunnel ready: $(docker exec "$TUN" cat /run/ready)"; else fail "tunnel never became ready"; docker logs "$TUN" 2>&1 | tail -10; fi
    new_earner "$P-a" "$TUN"
    new_earner "$P-b" "$TUN"
    joined "$P-a" "$TUN" && joined "$P-b" "$TUN" && pass "both earners live in the tunnel's namespace" || fail "an earner is not in the tunnel"

    # a.
    reaches "$P-a" && reaches "$P-b" && pass "a: both earners reach 1.1.1.1 through the exit node" || fail "a: an earner cannot reach 1.1.1.1"
    n=$(clear_packets "$TUN" "$P-a" "$P-b")
    [ "$n" = 0 ] && pass "a: none of it left eth0 in the clear" || fail "a: $n packets left eth0 in the clear"

    # s. B keeps going while A stops and starts
    ( ok=0 bad=0; for _ in $(seq 1 16); do if docker exec "$P-b" curl -s -o /dev/null -m 3 http://1.1.1.1; then ok=$((ok + 1)); else bad=$((bad + 1)); fi; sleep 0.5; done
      echo "$ok $bad" >"$WORK/s" ) &
    sp=$!
    sleep 1
    docker stop -t 1 "$P-a" >/dev/null
    sleep 3
    docker start "$P-a" >/dev/null
    wait $sp
    read -r ok bad <"$WORK/s"
    [ "$bad" = 0 ] && [ "$ok" -gt 0 ] && pass "s: B made $ok requests and lost none while A stopped and started" || fail "s: B lost $bad of $((ok + bad)) requests while A stopped"

    # t.
    if docker exec "$P-a" curl -s -o /dev/null -m 5 "http://$EXIT_IP:8000" || docker exec "$P-b" curl -s -o /dev/null -m 5 "http://$EXIT_IP:8000"; then
        fail "t: an earner reached a tailnet node at $EXIT_IP:8000"
    else
        pass "t: neither earner reaches a tailnet node at $EXIT_IP:8000"
    fi

    # n. DNS canary, captured on the tunnel's real interface. (On this one test
    #    host the exit node's own lookups would show on a host-wide capture.)
    canary="leak-$(head -c 6 /dev/urandom | od -An -tx1 | tr -d ' \n').example.com"
    n=$(dns_mentions "$TUN" "$canary" "$P-a" "$P-b")
    [ "$n" = 0 ] && pass "n: the canary name appears in 0 DNS packets on the tunnel's real interface" || fail "n: the canary appears in $n DNS packets on eth0"

    # r. restart of the shared tunnel
    docker restart -t 2 "$TUN" >/dev/null &
    rp=$!
    sleep 1
    gap_ifaces=$(docker exec "$P-a" sh -c 'ls /sys/class/net' 2>/dev/null | tr '\n' ' ' || true)
    if reaches "$P-a" || reaches "$P-b"; then gap="reached"; else gap="nothing"; fi
    wait $rp
    if wait_ready "$TUN"; then
        # The heartbeat restarts an earner whose tunnel started after it.
        docker restart -t 1 "$P-a" "$P-b" >/dev/null
        sleep 2
        if [ "$gap" = nothing ] && reaches "$P-a" && reaches "$P-b"; then
            pass "r: during the restart the earners reached nothing (interfaces: ${gap_ifaces:-none}); after it both reach 1.1.1.1"
        else
            fail "r: during the restart the earners reached $gap (interfaces: $gap_ifaces), or did not come back"
        fi
    else
        fail "r: the restarted tunnel did not come back"
    fi

    # b. exit node stopped
    docker stop -t 1 "$P-exit" >/dev/null
    sleep 3
    closed b "$TUN" "$P-a" "$P-b" && pass "b: exit node stopped: neither earner escapes, 0 packets left eth0" || fail "b: a leak with the exit node stopped"
    docker start "$P-exit" >/dev/null
    sleep 6
    docker exec -d "$P-exit" sh -c 'while true; do printf "HTTP/1.0 200 OK\r\n\r\nhi" | nc -l -p 8000; done'

    # k. tailscaled frozen, then killed
    new_tunnel "$TUN" "$TUNNEL_IMAGE"
    wait_ready "$TUN" || fail "k: tunnel did not become ready"
    new_earner "$P-a" "$TUN"
    new_earner "$P-b" "$TUN"
    reaches "$P-a" || fail "k: earner a cannot reach 1.1.1.1 before the test"
    tsd='$(for p in /proc/[0-9]*; do [ "$(cat $p/comm 2>/dev/null)" = tailscaled ] && basename $p; done)'
    docker exec "$TUN" sh -c "kill -STOP $tsd"
    closed k-stop "$TUN" "$P-a" "$P-b" && pass "k: tailscaled frozen: neither earner escapes, 0 packets left eth0" || fail "k: a leak with tailscaled frozen"
    docker exec "$TUN" sh -c "kill -KILL $tsd" || true
    sleep 2
    state=$(docker inspect -f '{{.State.Status}}' "$TUN")
    ifaces=$(docker exec "$P-a" sh -c 'ls /sys/class/net' 2>/dev/null | tr '\n' ' ' || true)
    if [ "$state" != running ] && ! escapes "$P-a" && ! escapes "$P-b"; then
        pass "k: tailscaled killed: tunnel $state, both earners left with: ${ifaces:-none}"
    else
        fail "k: tunnel $state after tailscaled was killed, earner interfaces: $ifaces"
    fi

    # d. no exit node set
    new_tunnel "$TUN" "$TUNNEL_IMAGE"
    wait_ready "$TUN" || fail "d: tunnel did not become ready"
    new_earner "$P-a" "$TUN"
    new_earner "$P-b" "$TUN"
    docker exec "$TUN" tailscale --socket=/run/ts/ts.sock set --exit-node= >/dev/null
    sleep 2
    closed d "$TUN" "$P-a" "$P-b" && pass "d: no exit node set: the firewall alone holds for both earners" || fail "d: a leak with no exit node set"

    # c1. the firewall deleted (no exit node is set, so the default route is
    #     the box's own): the same checks must see the leak.
    docker exec "$TUN" nft delete table inet cashpilot
    rc=0
    closed c1 "$TUN" "$P-a" "$P-b" >/dev/null || rc=$?
    case $rc in
        1) pass "c1: the checks see the leak of an opened namespace" ;;
        0) fail "c1: the checks missed an opened namespace" ;;
        *) fail "c1: the capture failed, so the control proves nothing" ;;
    esac
    n=$(dns_mentions "$TUN" "ctl-$canary" "$P-a")
    [[ "$n" =~ ^[1-9][0-9]*$ ]] && pass "c1: the DNS capture sees the canary in $n packets from an opened namespace" || fail "c1: the DNS capture missed an opened namespace"

    # c2. a copy that misses its tunnel (created on the bridge): joined() and escapes() must catch it.
    new_tunnel "$TUN" "$TUNNEL_IMAGE"
    wait_ready "$TUN" || true
    docker rm -fv "$P-stray" >/dev/null 2>&1 || true
    docker run -d --name "$P-stray" --network "$NET" --cap-drop ALL --security-opt no-new-privileges:true \
        --entrypoint sleep "$CURL" infinity >/dev/null
    docker stop -t 1 "$P-exit" >/dev/null
    sleep 2
    if joined "$P-stray" "$TUN"; then fail "c2: joined() took a bridge container for a member"; else pass "c2: joined() refuses a copy outside the tunnel"; fi
    if escapes "$P-stray"; then pass "c2: escapes() sees a copy outside the tunnel leave from the box"; else fail "c2: escapes() missed a copy outside the tunnel"; fi
    docker rm -fv "$P-stray" >/dev/null
    docker start "$P-exit" >/dev/null
    sleep 6

    # c3. a tunnel image with "policy accept": case d must leak.
    docker build -q -t "$P-mutant" - >/dev/null <<EOF
FROM $TUNNEL_IMAGE
RUN sed -i 's/type filter hook output priority 0; policy drop;/type filter hook output priority 0; policy accept;/' /usr/local/bin/cp-tunnel && grep -q 'output priority 0; policy accept' /usr/local/bin/cp-tunnel
EOF
    new_tunnel "$P-mut" "$P-mutant"
    wait_ready "$P-mut" || true
    new_earner "$P-ma" "$P-mut"
    docker exec "$P-mut" tailscale --socket=/run/ts/ts.sock set --exit-node= >/dev/null 2>&1 || true
    sleep 2
    rc=0
    closed c3 "$P-mut" "$P-ma" >/dev/null || rc=$?
    case $rc in
        1) pass "c3: a policy-accept tunnel fails case d, so d can fail" ;;
        0) fail "c3: a policy-accept tunnel passed case d" ;;
        *) fail "c3: the capture failed, so the control proves nothing" ;;
    esac
    docker rm -fv "$P-a" "$P-b" "$P-ma" "$P-mut" "$TUN" >/dev/null 2>&1 || true
fi

# --- parts 2 and 3: the worker's own code ---
export LAB_AUTH_KEY=$KEY LAB_EXIT_NODE=$EXIT_IP LAB_LOGIN_SERVER=http://$HS_IP:8080 LAB_PROXY_ID=3
export LAB_EARNER_IMAGE=$CURL CASHPILOT_TUNNEL_IMAGE=$TUNNEL_IMAGE CASHPILOT_CONTAINER_NETWORK=$NET
export CASHPILOT_DATA_DIR=$WORK/data
mkdir -p "$CASHPILOT_DATA_DIR"
drive() { # src args...
    local src=$1
    shift
    CASHPILOT_SRC=$src $PYTHON "$HERE/scripts/proxy_shared_tunnel_lab.py" "$@"
}
mib() { awk -v b="$1" 'BEGIN { printf "%.1f", b / 1048576 }'; }
# Sum of cgroup memory.current, in bytes, of the containers matching a label filter.
cgroup_sum() { # filter...
    cgroup_sum_ids "$(docker ps -q --no-trunc "$@" | tr '\n' ' ')"
}
cgroup_sum_ids() { # "id id ..."; the cgroupfs and the systemd driver's paths
    local ids=$1
    [ -n "${ids// /}" ] || { echo 0; return; }
    docker run --rm -v /sys/fs/cgroup:/cg:ro "$ALPINE" sh -c \
        "t=0; for i in $ids; do f=/cg/docker/\$i/memory.current; [ -f \$f ] || f=/cg/system.slice/docker-\$i.scope/memory.current; t=\$((t + \$(cat \$f))); done; echo \$t"
}
measure() { # label n
    local label=$1 n=$2 tunnels tmem emem
    sleep 25 # past the tunnels' startup peak
    tunnels=$(docker ps -q --filter label=cashpilot.role=tunnel --filter label=cashpilot.proxy=3 | wc -l | tr -d ' ')
    tmem=$(cgroup_sum --filter label=cashpilot.role=tunnel --filter label=cashpilot.proxy=3)
    emem=$(docker ps -q --no-trunc --filter label=cashpilot.proxy=3 | while read -r id; do
        [ "$(docker inspect -f '{{index .Config.Labels "cashpilot.role"}}' "$id")" = tunnel ] || echo "$id"; done | tr '\n' ' ')
    emem=$(cgroup_sum_ids "$emem")
    echo "RAM   $label N=$n: tunnels=$tunnels tunnel_mem=$(mib "$tmem") MiB earner_mem=$(mib "$emem") MiB per_copy_tunnel=$(mib $((tmem / n))) MiB"
    printf '%s %s %s %s %s\n' "$label" "$n" "$tunnels" "$tmem" "$emem" >>"$WORK/ram"
    LAST_TUNNELS=$tunnels
}
earners_reach() { # how many proxied earners reach 1.1.1.1
    local ok=0 id
    for id in $(docker ps -q --filter label=cashpilot.proxy=3 --filter label=cashpilot.service); do
        [ "$(docker inspect -f '{{index .Config.Labels "cashpilot.role"}}' "$id")" = tunnel ] && continue
        docker exec "$id" curl -s -o /dev/null -m 6 http://1.1.1.1 && ok=$((ok + 1))
    done
    echo $ok
}
part2() { # label src
    local label=$1 src=$2 n
    for n in 1 7; do
        wipe_copies
        rm -f "$CASHPILOT_DATA_DIR/.proxied_held"
        drive "$src" deploy "$n" >"$WORK/deploy.log" 2>&1 || { fail "$label N=$n: deploy failed"; tail -5 "$WORK/deploy.log"; continue; }
        measure "$label" "$n"
        r=$(earners_reach)
        [ "$r" = "$n" ] && pass "$label N=$n: all $n copies reach 1.1.1.1 through the exit node" || fail "$label N=$n: only $r of $n copies reach 1.1.1.1"
        if [ "$label" = tree ]; then
            [ "$LAST_TUNNELS" = 1 ] && pass "tree N=$n: one tunnel for the proxy" || fail "tree N=$n: $LAST_TUNNELS tunnels for one proxy"
        fi
    done
    # With the exit node stopped none of the 7 reaches anything.
    docker stop -t 1 "$P-exit" >/dev/null
    sleep 3
    r=$(earners_reach)
    [ "$r" = 0 ] && pass "$label N=7: exit node stopped, 0 of 7 copies reach 1.1.1.1" || fail "$label N=7: $r copies reached 1.1.1.1 with the exit node stopped"
    docker start "$P-exit" >/dev/null
    sleep 8
}

if [[ " $PARTS " == *" 2 "* ]]; then
    echo "== part 2: the worker's code, N=1 and N=7"
    [ -n "$BASE_SRC" ] && part2 base "$BASE_SRC"
    part2 tree "$SRC"
    if [ -n "$BASE_SRC" ] && [ -f "$WORK/ram" ]; then
        echo "== RAM, cgroup memory.current of the proxy's tunnels"
        awk '{ printf "      %-5s N=%s  tunnels=%s  tunnels=%.1f MiB  earners=%.1f MiB\n", $1, $2, $3, $4/1048576, $5/1048576 }' "$WORK/ram"
    fi
fi

if [[ " $PARTS " == *" 3 "* ]] && [ -n "$BASE_SRC" ]; then
    echo "== part 3: copies of the base branch moved into one tunnel"
    wipe_copies
    rm -f "$CASHPILOT_DATA_DIR/.proxied_held"
    drive "$BASE_SRC" deploy 3 >/dev/null
    before=$(docker ps -q --filter label=cashpilot.role=tunnel | wc -l | tr -d ' ')
    drive "$SRC" migrate >"$WORK/migrate.log" 2>&1 || { fail "migrate raised"; tail -5 "$WORK/migrate.log"; }
    after=$(docker ps -aq --filter label=cashpilot.role=tunnel | wc -l | tr -d ' ')
    r=$(earners_reach)
    [ "$before" = 3 ] && [ "$after" = 1 ] && [ "$r" = 3 ] &&
        pass "migration: $before tunnels became $after, and all $r copies reach 1.1.1.1" ||
        fail "migration: $before tunnels became $after, $r of 3 copies reach 1.1.1.1"
    drive "$SRC" migrate >/dev/null 2>&1
    again=$(docker ps -aq --filter label=cashpilot.role=tunnel | wc -l | tr -d ' ')
    [ "$again" = 1 ] && pass "migration: a second run changes nothing" || fail "migration: a second run left $again tunnels"
    # A stop through the worker's code keeps the tunnel for the other two.
    drive "$SRC" stop labearner0 >/dev/null
    drive "$SRC" heartbeat >/dev/null
    r=$(earners_reach)
    [ "$r" = 2 ] && pass "stop: one copy stopped, the other 2 still reach 1.1.1.1 and the heartbeat did not start it" || fail "stop: $r copies reach after one stop"
fi

restart_daemon() {
    sh -c "$DOCKERD_RESTART" >/dev/null 2>&1 || return 1
    local i
    for i in $(seq 60); do docker info >/dev/null 2>&1 && break; sleep 2; done
    docker info >/dev/null 2>&1 || return 1
    # The lab's control server and exit node have no restart policy; the
    # tunnel (unless-stopped) is what Docker brings back on its own.
    docker start "$P-hs" "$P-exit" >/dev/null
}
# Waits up to 90 s for the proxy's tunnel to run and write /run/ready.
tunnel_ready() {
    local i
    for i in $(seq 45); do
        docker exec cashpilot-tunnel-p3 cat /run/ready >/dev/null 2>&1 && return 0
        sleep 2
    done
    return 1
}
state_of() { docker inspect -f '{{.State.Status}} {{.State.Error}}' "$1" 2>/dev/null || echo missing; }
ids_of_copies() { docker ps -aq --no-trunc --filter label=cashpilot.proxy=3 | sort | tr '\n' ' '; }
# r. a daemon restart, run against one tree; prints what it saw. Returns 0 if
# every copy held, 1 if one did not, 2 if the case could not be set up (which
# the control must never count as the failure it expects).
restart_case() { # src
    local src=$1 ok=0
    wipe_copies
    rm -f "$CASHPILOT_DATA_DIR/.proxied_held"
    drive "$src" deploy 3 >"$WORK/r.log" 2>&1 || { echo "setup: deploy failed: $(tail -2 "$WORK/r.log")"; return 2; }
    drive "$src" stop labearner1 >/dev/null 2>&1 || { echo "setup: stop failed"; return 2; }
    restart_daemon || { echo "setup: the daemon restart command failed or the daemon did not come back"; return 2; }
    if tunnel_ready; then echo "tunnel back and ready by itself"; else echo "tunnel: $(state_of cashpilot-tunnel-p3)"; ok=1; fi
    drive "$src" heartbeat >/dev/null 2>&1 || true
    sleep 3
    local r
    r=$(earners_reach)
    echo "after one heartbeat $r copies reach 1.1.1.1, the stopped one is $(state_of cashpilot-labearner1-p3)"
    [ "$r" = 2 ] || ok=1
    [ "$(docker inspect -f '{{.State.Status}}' cashpilot-labearner1-p3 2>/dev/null)" = running ] && ok=1
    if drive "$src" start labearner1 >"$WORK/r.log" 2>&1; then
        sleep 3
        r=$(earners_reach)
        echo "start of the stopped copy worked; $r copies reach 1.1.1.1"
        [ "$r" = 3 ] || ok=1
    else
        echo "start of the stopped copy failed: $(tail -1 "$WORK/r.log" | cut -c1-200)"
        ok=1
    fi
    return $ok
}

if [[ " $PARTS " == *" 4 "* ]]; then
    echo "== part 4: a daemon restart, an edit and a worker killed mid-move cost no copy"
    if [ -z "$DOCKERD_RESTART" ]; then
        fail "r: DOCKERD_RESTART is not set, so the daemon restart case did not run"
    else
        if out=$(restart_case "$SRC"); then
            pass "r: daemon restart: $(echo "$out" | tr '\n' ';')"
        else
            fail "r: daemon restart: $(echo "$out" | tr '\n' ';')"
        fi
        if [ -n "$PREV_SRC" ]; then
            rc=0
            out=$(restart_case "$PREV_SRC") || rc=$? # set -e: capture the expected failure
            case $rc in
                0) fail "r control: the bind-volume tree also survived, so case r cannot fail: $(echo "$out" | tr '\n' ';')" ;;
                1) pass "r control: the bind-volume tree fails case r: $(echo "$out" | tr '\n' ';')" ;;
                *) fail "r control: could not be set up, so it proves nothing: $(echo "$out" | tr '\n' ';')" ;;
            esac
        fi
    fi

    # e. an edited proxy keeps every container and what the copies wrote.
    wipe_copies
    rm -f "$CASHPILOT_DATA_DIR/.proxied_held"
    drive "$SRC" deploy 3 >/dev/null
    docker exec cashpilot-labearner0-p3 sh -c 'echo lab-device-id > /tmp/deviceid'
    before=$(ids_of_copies)
    export LAB_AUTH_KEY2
    LAB_AUTH_KEY2=$(hs preauthkeys create --user "$USER_ID" --reusable --ephemeral --expiration 2h | tail -1 | tr -d '\r ')
    if drive "$SRC" edit labearner0 >"$WORK/e.log" 2>&1; then
        sleep 3
        after=$(ids_of_copies)
        kept=$(docker exec cashpilot-labearner0-p3 cat /tmp/deviceid 2>/dev/null || echo gone)
        r=$(earners_reach)
        key_now=$(docker exec cashpilot-tunnel-p3 cat /run/cashpilot-secret/auth_key 2>/dev/null || true)
        if [ "$before" = "$after" ] && [ "$kept" = lab-device-id ] && [ "$r" = 3 ] && [ "$key_now" = "$LAB_AUTH_KEY2" ]; then
            pass "e: an edited proxy kept all 4 container ids and the copy's file, and 3 of 3 copies reach 1.1.1.1"
        else
            fail "e: ids kept=$([ "$before" = "$after" ] && echo yes || echo no) file=$kept reach=$r new key in the tunnel=$([ "$key_now" = "$LAB_AUTH_KEY2" ] && echo yes || echo no)"
        fi
    else
        fail "e: the edit failed: $(tail -1 "$WORK/e.log" | cut -c1-200)"
    fi

    # m. a worker killed mid-move, then the heartbeat.
    wipe_copies
    rm -f "$CASHPILOT_DATA_DIR/.proxied_held"
    drive "$SRC" deploy 3 >/dev/null
    docker tag "$TUNNEL_IMAGE" "$P-tunnel-next:1" >/dev/null
    code=0
    CASHPILOT_TUNNEL_IMAGE=$P-tunnel-next:1 drive "$SRC" die-mid-move labearner2 >"$WORK/m.log" 2>&1 || code=$?
    names=$(docker ps -a --filter label=cashpilot.proxy=3 --format '{{.Names}}' | sort | tr '\n' ' ')
    echo "      after the kill (exit $code): $names"
    lost=0
    for i in 0 1 2; do
        docker ps -a --format '{{.Names}}' | grep -q "^cashpilot-labearner$i-p3" || lost=1
    done
    [ "$code" = 9 ] && [ "$lost" = 0 ] && pass "m: killed mid-move, every copy still has a container" ||
        fail "m: exit $code, a copy lost: $names"
    LAB_STALE=0 CASHPILOT_TUNNEL_IMAGE=$P-tunnel-next:1 drive "$SRC" heartbeat >/dev/null 2>&1 || true
    tunnel_ready || true
    LAB_STALE=0 CASHPILOT_TUNNEL_IMAGE=$P-tunnel-next:1 drive "$SRC" heartbeat >/dev/null 2>&1 || true
    sleep 3
    names=$(docker ps -a --filter label=cashpilot.proxy=3 --format '{{.Names}}' | sort | tr '\n' ' ')
    r=$(earners_reach)
    want="cashpilot-labearner0-p3 cashpilot-labearner1-p3 cashpilot-labearner2-p3 cashpilot-tunnel-p3 "
    [ "$names" = "$want" ] && [ "$r" = 3 ] && pass "m: the heartbeat left one tunnel and 3 copies, all reaching 1.1.1.1" ||
        fail "m: after the heartbeat: $names; $r copies reach"
    docker rmi "$P-tunnel-next:1" >/dev/null 2>&1 || true
fi

echo
if [ "$FAILS" -eq 0 ]; then echo "ALL PASSED"; else echo "$FAILS FAILED"; exit 1; fi
