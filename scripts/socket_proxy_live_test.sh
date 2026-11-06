#!/usr/bin/env bash
# Proves the Docker socket proxy in docker-compose.yml against a real daemon
# (docs/security-defaults.md, "Docker socket proxy").
#
# Run it only on a disposable Docker host: it starts the shipped compose
# project (UI, worker and proxy) under their real container names, and the
# positive control briefly turns the daemon into a swarm manager and leaves it
# again. It refuses to start when a cashpilot-ui, cashpilot-worker or
# cashpilot-socket-proxy container already exists.
#
# What it checks:
#   a. every Docker call the worker makes passes the proxy, through the real
#      worker code in the real worker container: deploys (bind from the allowed
#      folder, NET_RAW; host networking with NET_ADMIN and /dev/net/tun), the
#      catalog's exec readers, logs, stats, pause and file reads, stop, start,
#      restart, volumes, the tunnel sidecar (sysctls, put_archive, an earner in
#      its namespace), the isolation check and the activity round; and the
#      proxy logged no refusal while they ran;
#   b. the proxy refuses a privileged create, a bind of / and of the socket,
#      SYS_ADMIN, a device, host PID, seccomp=unconfined, a create without
#      no-new-privileges, the same privileged create spelled in lowercase, a
#      local volume bound to /, exec of sh, exec with LD_PRELOAD, container
#      update, swarm init, a build, plugins and events;
#   b2. a container created in the proxy's process namespace cannot read the
#      proxy's files (/proc/1/root, where the host socket is);
#   c. the raw socket accepts every request in (b), so each refusal is the
#      proxy's own and not a malformed request (the positive control);
#   d. the in-app update recreates the UI and worker through the proxy, keeps
#      the proxy, and the new worker still reaches Docker through it;
#   e. a restarted proxy replaces its socket and the worker reconnects.
#
# Needs: docker, base64, and either the compose plugin or the docker CLI image
# (COMPOSE_IMAGE) to run compose in. Builds the worker image from this checkout
# and serves it from a local registry, so the update has something to pull.
#
# Usage: TUNNEL_IMAGE=cashpilot-tunnel:test scripts/socket_proxy_live_test.sh
#   WORK_DIR   a folder the daemon can bind (default: ./.socket-proxy-live)
#   KEEP=1     leave everything running for a look afterwards
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
WORK_DIR=${WORK_DIR:-$ROOT/.socket-proxy-live}
TUNNEL_IMAGE=${TUNNEL_IMAGE:-}
REGISTRY_IMAGE=registry:3.0.0
COMPOSE_IMAGE=${COMPOSE_IMAGE:-docker:27.5.1-cli}
ALPINE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
REG_PORT=${REG_PORT:-5055}
REG=127.0.0.1:$REG_PORT
WORKER_IMAGE=$REG/cashpilot-worker:live
UI_IMAGE=$REG/cashpilot:live
PROJECT=cplive
P=cplive

FAILS=0
pass() { echo "PASS  $*"; }
fail() {
    echo "FAIL  $*"
    FAILS=$((FAILS + 1))
}

if docker compose version >/dev/null 2>&1; then
    compose() { (cd "$WORK_DIR/project" && docker compose -p "$PROJECT" "$@"); }
else
    compose() {
        docker run --rm -i --label "$P=1" -v /var/run/docker.sock:/var/run/docker.sock \
            -v "$WORK_DIR/project:$WORK_DIR/project" -w "$WORK_DIR/project" "$COMPOSE_IMAGE" \
            docker compose -p "$PROJECT" "$@"
    }
fi

cleanup() {
    [ "${KEEP:-0}" = 1 ] && return
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    docker ps -aq --filter label=cashpilot.live-test=1 | xargs -r docker rm -fv >/dev/null 2>&1 || true
    docker ps -aq --filter "label=$P=1" | xargs -r docker rm -fv >/dev/null 2>&1 || true
    docker rm -f cashpilot-updater >/dev/null 2>&1 || true
    docker volume ls -q --filter label=cashpilot.live-test=1 | xargs -r docker volume rm -f >/dev/null 2>&1 || true
    docker volume rm -f cashpilot-docker-api cashpilot-cplive-data >/dev/null 2>&1 || true
    # The fence this run built: its network and its host firewall tables, removed
    # with the worker image it ran from, before that image goes.
    docker network rm cashpilot-isolated >/dev/null 2>&1 || true
    for family in ip ip6; do
        docker run --rm --network host --cap-add NET_ADMIN --entrypoint nft "$P-worker:build" \
            delete table "$family" cashpilot >/dev/null 2>&1 || true
    done
    docker rmi -f "$WORKER_IMAGE" "$UI_IMAGE" "$P-worker:build" >/dev/null 2>&1 || true
}
trap 'jobs -p | xargs -r kill 2>/dev/null; cleanup' EXIT

for name in cashpilot-ui cashpilot-worker cashpilot-socket-proxy cashpilot-updater; do
    if docker inspect "$name" >/dev/null 2>&1; then
        echo "A container named $name already exists; this test needs a host without CashPilot." >&2
        trap - EXIT
        exit 2
    fi
done
# A network left by an earlier run would let the fence skip the create call
# the proxy has to allow, so a refusal there could never show.
if docker network inspect cashpilot-isolated >/dev/null 2>&1; then
    echo "A network named cashpilot-isolated already exists; this test needs a host without CashPilot." >&2
    trap - EXIT
    exit 2
fi
# A managed container already on the default bridge makes the fence treat
# this host as an upgraded install and stay off, so the fenced deploy below
# would land on the default bridge and prove nothing.
if [ -n "$(docker ps -aq --filter label=cashpilot.managed=true)" ]; then
    echo "CashPilot-managed containers already exist on this host; this test needs a host without CashPilot." >&2
    trap - EXIT
    exit 2
fi
if docker volume inspect cashpilot-docker-api >/dev/null 2>&1; then
    echo "The volume cashpilot-docker-api already exists; this test needs a host without CashPilot." >&2
    trap - EXIT
    exit 2
fi

# The positive control turns the daemon into a swarm manager and force-leaves
# afterwards, which would take a host out of a swarm it already belongs to.
if [ "$(docker info -f '{{.Swarm.LocalNodeState}}')" != inactive ]; then
    echo "This daemon is part of a swarm; the positive control would make it leave. Use another host." >&2
    trap - EXIT
    exit 2
fi

mkdir -p "$WORK_DIR/project" "$WORK_DIR/binds/plain"

echo "== build the worker from this checkout and serve it from a local registry"
docker run -d --name "$P-registry" --label "$P=1" -p "$REG:5000" "$REGISTRY_IMAGE" >/dev/null
docker build -q -f "$ROOT/Dockerfile.worker" -t "$P-worker:build" "$ROOT" >/dev/null
docker tag "$P-worker:build" "$WORKER_IMAGE"
# Any UI image will do: the test needs a second compose service to recreate.
docker build -q -t "$UI_IMAGE" - >/dev/null <<EOF
FROM $ALPINE
LABEL cashpilot.live-test.role=ui
CMD ["sleep", "infinity"]
EOF
for _ in $(seq 1 20); do docker push -q "$WORKER_IMAGE" >/dev/null 2>&1 && break; sleep 1; done
docker push -q "$UI_IMAGE" >/dev/null

echo "== bring up the shipped compose file (UI, worker, proxy) through the raw socket, as you would"
sed -e "s#image: drumsergio/cashpilot-worker:[0-9.]*#image: $WORKER_IMAGE#" \
    -e "s#image: drumsergio/cashpilot:[0-9.]*#image: $UI_IMAGE#" \
    "$ROOT/docker-compose.yml" >"$WORK_DIR/project/docker-compose.yml"
# The UI stand-in has no web server; its healthcheck is not what is tested.
cat >"$WORK_DIR/project/.env" <<EOF
CASHPILOT_COMPOSE_DIR=$WORK_DIR/project
CASHPILOT_PROXY_BIND_MOUNTS=$WORK_DIR/binds
CASHPILOT_UI_PORT=18080
CASHPILOT_API_KEY=live-test-key
CASHPILOT_ALLOW_EPHEMERAL_KEY=true
EOF
compose up -d 2>&1 | tail -3
for _ in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' cashpilot-worker 2>/dev/null)" = healthy ] && break
    sleep 2
done
docker inspect -f '{{.State.Health.Status}}' cashpilot-worker | grep -qx healthy && pass "the worker is healthy behind the proxy" \
    || fail "the worker is not healthy: $(docker logs --tail 5 cashpilot-worker 2>&1 | tr '\n' ' ')"
docker inspect -f '{{range .Mounts}}{{.Source}} {{end}}' cashpilot-worker | grep -q docker.sock \
    && fail "the worker mounts the Docker socket" || pass "the worker mounts no Docker socket"

POLICY=$(docker cp cashpilot-socket-proxy:/etc/sockguard/sockguard.yaml - | tar -xO | base64 | tr -d '\n')
driver() {
    local phase=$1
    shift
    docker exec -i -u 1000:1000 -e LIVE_POLICY="$POLICY" -e LIVE_ALPINE="$ALPINE" \
        -e LIVE_BIND_DIR="$WORK_DIR/binds" -e LIVE_TUNNEL_IMAGE="$TUNNEL_IMAGE" -e CASHPILOT_TUNNEL_IMAGE="$TUNNEL_IMAGE" "$@" \
        cashpilot-worker python - "$phase" <"$ROOT/scripts/socket_proxy_live_driver.py"
}
count() { grep -c "$1" || true; }
show() {
    echo "$1" | grep -E '^(PASS|FAIL)' || true
    echo "$1" | grep -vE '^(PASS|FAIL)' | sed 's/^/    | /' | tail -15 || true
}

echo "== a. every call the worker makes passes"
docker pull -q "$ALPINE" >/dev/null
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
out=$(driver allowed 2>&1) || true
show "$out"
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
[ "$(echo "$out" | count '^PASS')" -ge 25 ] || fail "too few allowed checks ran: $(echo "$out" | tail -3 | tr '\n' ' ')"
denied=$(docker logs --since "$since" cashpilot-socket-proxy 2>&1 | grep 'request_denied' || true)
[ -z "$denied" ] && pass "the proxy refused nothing while the worker ran" \
    || fail "the proxy refused calls the worker makes: $(echo "$denied" | head -3)"

echo "== b. the proxy refuses"
out=$(driver refused 2>&1) || true
show "$out"
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
[ "$(echo "$out" | count '^PASS')" -ge 17 ] || fail "too few refusal checks ran"
# The "refused nothing" check in (a) reads the same log; it must be able to see a refusal.
# Captured first: under pipefail, grep -q closing the pipe early fails the
# pipeline with SIGPIPE even when the line is there.
proxy_log=$(docker logs --since "$since" cashpilot-socket-proxy 2>&1 || true)
case "$proxy_log" in
*request_denied*) pass "the proxy logs its refusals" ;;
*) fail "the proxy logged none of the refusals, so the check in (a) cannot fail" ;;
esac

echo "== b2. a container in the proxy's process namespace cannot reach its files"
# sockguard lets PidMode container:<name> through; the proxy's extra capability
# is what keeps the joiner out of /proc/1/root, where the host socket is.
joined=$(docker exec -i -u 1000:1000 cashpilot-worker python - "$ALPINE" <<'PY' 2>&1
import sys, docker
c = docker.from_env().containers.run(
    sys.argv[1], ["sh", "-c", "ls /proc/1/root/var/run/docker.sock 2>&1; true"],
    pid_mode="container:cashpilot-socket-proxy", security_opt=["no-new-privileges:true"],
    labels={"cashpilot.live-test": "1"}, detach=True)
c.wait(timeout=60)
print(c.logs().decode().strip())
c.remove(force=True)
PY
) || true
echo "$joined" | grep -q "Permission denied" && pass "the joiner is refused the proxy's files" \
    || fail "a container in the proxy's process namespace reached its files: $joined"

echo "== c. positive control: the raw socket accepts the same requests"
out=$(docker run --rm -i --label "$P=1" -u 0:0 --entrypoint python -e LIVE_ALPINE="$ALPINE" \
    -v /var/run/docker.sock:/var/run/docker.sock "$WORKER_IMAGE" - control \
    <"$ROOT/scripts/socket_proxy_live_driver.py" 2>&1) || true
show "$out"
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
[ "$(echo "$out" | count '^PASS')" -ge 17 ] || fail "too few control checks ran"
docker info -f '{{.Swarm.LocalNodeState}}' | grep -qx inactive && pass "the control left swarm mode" \
    || fail "the daemon is still in swarm mode; run docker swarm leave --force"

echo "== d. the in-app update recreates the UI and worker through the proxy"
old_worker=$(docker inspect -f '{{.Id}}' cashpilot-worker)
old_ui=$(docker inspect -f '{{.Id}}' cashpilot-ui)
old_proxy=$(docker inspect -f '{{.Id}}' cashpilot-socket-proxy)
# A new worker image under the same tag, so the update has something to pull.
docker build -q -t "$WORKER_IMAGE" - >/dev/null <<EOF
FROM $WORKER_IMAGE
LABEL cashpilot.live-test.update=2
EOF
docker build -q -t "$UI_IMAGE" - >/dev/null <<EOF
FROM $UI_IMAGE
LABEL cashpilot.live-test.update=2
EOF
docker push -q "$WORKER_IMAGE" >/dev/null
docker push -q "$UI_IMAGE" >/dev/null
docker rmi "$WORKER_IMAGE" "$UI_IMAGE" >/dev/null
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
out=$(driver update 2>&1) || true
show "$out"
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
# The helper removes itself when done; wait for that, then for the new worker.
for _ in $(seq 1 90); do docker inspect cashpilot-updater >/dev/null 2>&1 || break; sleep 2; done
for _ in $(seq 1 60); do
    [ "$(docker inspect -f '{{.State.Health.Status}}' cashpilot-worker 2>/dev/null)" = healthy ] && break
    sleep 2
done
[ "$(docker inspect -f '{{.Id}}' cashpilot-worker 2>/dev/null)" != "$old_worker" ] && pass "the update recreated the worker" \
    || fail "the worker was not recreated"
[ "$(docker inspect -f '{{.Id}}' cashpilot-ui 2>/dev/null)" != "$old_ui" ] && pass "the update recreated the UI" \
    || fail "the UI was not recreated"
[ "$(docker inspect -f '{{.Id}}' cashpilot-socket-proxy)" = "$old_proxy" ] && pass "the update left the proxy alone" \
    || fail "the update recreated the proxy"
[ "$(docker inspect -f '{{index .Config.Labels "cashpilot.live-test.update"}}' cashpilot-worker 2>/dev/null)" = 2 ] \
    && pass "the new worker runs the pulled image" || fail "the new worker does not run the pulled image"
[ "$(driver access 2>/dev/null)" = proxy ] && pass "the new worker reaches Docker through the proxy" \
    || fail "the new worker does not reach Docker through the proxy"
denied=$(docker logs --since "$since" cashpilot-socket-proxy 2>&1 | grep 'request_denied' || true)
[ -z "$denied" ] && pass "the proxy refused nothing the update or Compose asked for" \
    || fail "the proxy refused part of the update: $(echo "$denied" | head -3)"

echo "== e. a restarted proxy replaces its socket and the worker reconnects"
docker restart cashpilot-socket-proxy >/dev/null
sleep 3
[ "$(driver access 2>/dev/null)" = proxy ] && out=$(docker exec -u 1000:1000 cashpilot-worker \
    python -c 'from app import orchestrator; orchestrator._get_client().ping(); print("ok")' 2>&1) || true
[ "$out" = ok ] && pass "the worker reaches Docker after a proxy restart" || fail "no Docker after a proxy restart: $out"

echo
if [ "$FAILS" -eq 0 ]; then echo "ALL PASSED"; else echo "$FAILS FAILED"; fi
exit "$FAILS"
