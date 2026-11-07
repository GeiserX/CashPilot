#!/usr/bin/env bash
# Proves the upgrade to the socket proxy's owner isolation (app/owner_migrate.py,
# the cashpilot-migrate service) on a real daemon, from an install made the way
# releases before it made one.
#
# Run it only on a disposable Docker host: it uses the real container names
# (cashpilot-ui, cashpilot-worker, cashpilot-socket-proxy, cashpilot-mysterium)
# and refuses to start when any of them, or the fence network, exists.
#
#   1. seeds an old install: the previous release's compose file and worker
#      image, a Mysterium-style earner keeping a known identity in the named
#      volume mysterium-data on an unlabelled cashpilot-isolated network, an
#      earner the user started by hand, and known files in the UI's, the
#      worker's and the fleet volumes;
#   2. red control: through that install's worker, the three attacks on the
#      UI's data succeed; then its Update button brings this checkout's worker
#      image onto the old compose file, which must still deploy and update;
#   3. upgrades with this checkout's compose file and `up -d --force-recreate`,
#      kills the migration while it copies the identity, shows what the kill
#      left, and runs the upgrade again, which must finish;
#   4. checks the identity has the same sha256, the earner runs on the fence,
#      the attacks are refused, the hand-started earner is untouched and
#      invisible, the worker can restart, back up and redeploy the earner, a
#      second run does nothing, and the in-app update recreates the worker.
#
# Usage: OLD_ROOT=/path/to/previous-release-checkout scripts/owner_migration_live_test.sh
#   WORK_DIR        a folder the daemon can bind (default: ./.owner-migration-live)
#   COMPOSE_PLUGIN  a docker-compose plugin binary to run instead of the host's
#                   (the floor, 2.23.1, for example), in the docker CLI image
#   KEEP=1          leave everything for a look afterwards; CLEANUP_ONLY=1 removes it
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/.." && pwd)
OLD_ROOT=${OLD_ROOT:?set OLD_ROOT to a checkout of the release before owner isolation}
WORK_DIR=${WORK_DIR:-$ROOT/.owner-migration-live}
COMPOSE_PLUGIN=${COMPOSE_PLUGIN:-}
REGISTRY_IMAGE=registry:3.0.0
CLI_IMAGE=docker:27.5.1-cli
ALPINE=alpine:3.22@sha256:2e0b81d60597f449baa56dc25d355367869d2dca4cd57e866f1e2b52af3eb55f
REG_PORT=${REG_PORT:-5056}
REG=127.0.0.1:$REG_PORT
PROJECT=cpmig
P=cpmig
IDENTITY=mysterium-data
BACKUP=$IDENTITY-pre-isolation
EARNER=cashpilot-mysterium
HAND=my-honeygain

FAILS=0
pass() { echo "PASS  $*"; }
fail() {
    echo "FAIL  $*"
    FAILS=$((FAILS + 1))
}
count() { grep -c "$1" || true; }

compose() {
    if [ -n "$COMPOSE_PLUGIN" ]; then
        docker run --rm -i --label "$P=1" -v /var/run/docker.sock:/var/run/docker.sock \
            -v "$COMPOSE_PLUGIN:/usr/local/libexec/docker/cli-plugins/docker-compose:ro" \
            -v "$WORK_DIR/project:$WORK_DIR/project" -w "$WORK_DIR/project" "$CLI_IMAGE" \
            docker compose -p "$PROJECT" "$@"
    else
        (cd "$WORK_DIR/project" && docker compose -p "$PROJECT" "$@")
    fi
}

# One digest of every file in a volume, read through the raw socket.
tree_sum() {
    docker run --rm -v "$1:/v:ro" "$ALPINE" sh -c 'cd /v && find . -type f | sort | xargs -r sha256sum | sha256sum | cut -c1-64'
}

LEGACY_CLEANUP='for spec in "iptables-legacy nat CP-POST POSTROUTING" "iptables-legacy mangle CP-FWD FORWARD" "iptables-legacy mangle CP-IN INPUT" "ip6tables-legacy mangle CP6-FWD FORWARD" "ip6tables-legacy mangle CP6-IN INPUT"; do
    set -- $spec
    command -v "$1" >/dev/null 2>&1 || continue
    "$1" -w -t "$2" -S "$4" 2>/dev/null | grep -- "-j $3\$" | sed "s/^-A /-D /" | while read -r rule; do
        eval "\"\$1\" -w -t \"\$2\" $rule"
    done
    "$1" -w -t "$2" -F "$3" 2>/dev/null
    "$1" -w -t "$2" -X "$3" 2>/dev/null
done
true'

cleanup() {
    [ "${KEEP:-0}" = 1 ] && return
    compose down -v --remove-orphans >/dev/null 2>&1 || true
    docker rm -f "$EARNER" "$HAND" cashpilot-ui cashpilot-worker cashpilot-socket-proxy cashpilot-migrate \
        cashpilot-migrate-copy cashpilot-updater >/dev/null 2>&1 || true
    docker ps -aq --filter label=cashpilot.live-test=1 | xargs -r docker rm -fv >/dev/null 2>&1 || true
    docker ps -aq --filter "label=$P=1" | xargs -r docker rm -fv >/dev/null 2>&1 || true
    docker ps -aq --filter label=cashpilot.probe | xargs -r docker rm -fv >/dev/null 2>&1 || true
    for v in "$IDENTITY" "$BACKUP" "$HAND-data" cashpilot-docker-api cashpilot-docker-api-owned \
        "${PROJECT}_cashpilot_data" "${PROJECT}_cashpilot_worker_data" "${PROJECT}_cashpilot_fleet" \
        "${PROJECT}_cashpilot_worker_data_owned" "${PROJECT}_cashpilot_fleet_owned"; do
        docker volume rm -f "$v" >/dev/null 2>&1 || true
    done
    # The migration's records: root's, in the compose folder.
    docker run --rm -v "$WORK_DIR/project:/p" "$ALPINE" rm -rf /p/cashpilot-migrate-state >/dev/null 2>&1 || true
    docker network rm cashpilot-isolated "${PROJECT}_default" "${PROJECT}_cashpilot_owned" >/dev/null 2>&1 || true
    for family in ip ip6; do
        docker run --rm --network host --cap-add NET_ADMIN --entrypoint nft "$REG/cashpilot-worker:new" \
            delete table "$family" cashpilot >/dev/null 2>&1 || true
    done
    docker run --rm --network host --cap-add NET_ADMIN --entrypoint sh "$REG/cashpilot-worker:new" -c "$LEGACY_CLEANUP" \
        >/dev/null 2>&1 || true
    docker rm -f "$P-registry" >/dev/null 2>&1 || true
    docker rmi -f "$REG/cashpilot-worker:old" "$REG/cashpilot-worker:new" "$REG/cashpilot:live" >/dev/null 2>&1 || true
}
if [ "${CLEANUP_ONLY:-0}" = 1 ]; then
    KEEP=0 cleanup
    exit 0
fi
trap 'jobs -p | xargs -r kill 2>/dev/null; cleanup' EXIT

for name in cashpilot-ui cashpilot-worker cashpilot-socket-proxy cashpilot-migrate cashpilot-updater "$EARNER" "$HAND"; do
    if docker inspect "$name" >/dev/null 2>&1; then
        echo "A container named $name already exists; this test needs a host without CashPilot." >&2
        trap - EXIT
        exit 2
    fi
done
for v in "$IDENTITY" "$BACKUP" cashpilot-docker-api cashpilot-docker-api-owned; do
    if docker volume inspect "$v" >/dev/null 2>&1; then
        echo "The volume $v already exists; this test needs a host without CashPilot." >&2
        trap - EXIT
        exit 2
    fi
done
if docker network inspect cashpilot-isolated >/dev/null 2>&1; then
    echo "A network named cashpilot-isolated already exists; this test needs a host without CashPilot." >&2
    trap - EXIT
    exit 2
fi

mkdir -p "$WORK_DIR/project"
compose version

echo "== build the previous release's worker and this checkout's, and serve them from a local registry"
docker run -d --name "$P-registry" --label "$P=1" -p "$REG:5000" "$REGISTRY_IMAGE" >/dev/null
docker build -q -f "$OLD_ROOT/Dockerfile.worker" -t "$REG/cashpilot-worker:old" "$OLD_ROOT" >/dev/null
docker build -q -f "$ROOT/Dockerfile.worker" -t "$REG/cashpilot-worker:new" "$ROOT" >/dev/null
docker build -q -t "$REG/cashpilot:live" - >/dev/null <<EOF
FROM $ALPINE
RUN mkdir -p /data && echo the-ui-fernet-key > /data/.fernet_key
CMD ["sleep", "infinity"]
EOF
for _ in $(seq 1 20); do docker push -q "$REG/cashpilot-worker:old" >/dev/null 2>&1 && break; sleep 1; done
docker push -q "$REG/cashpilot-worker:new" >/dev/null
docker push -q "$REG/cashpilot:live" >/dev/null
docker pull -q "$ALPINE" >/dev/null

use_compose() {
    sed -e "s#image: drumsergio/cashpilot-worker:[0-9.]*#image: $REG/cashpilot-worker:$2#" \
        -e "s#image: drumsergio/cashpilot:[0-9.]*#image: $REG/cashpilot:live#" \
        "$1/docker-compose.yml" >"$WORK_DIR/project/docker-compose.yml"
}
wait_healthy() {
    for _ in $(seq 1 60); do
        [ "$(docker inspect -f '{{.State.Health.Status}}' cashpilot-worker 2>/dev/null)" = healthy ] && return 0
        sleep 2
    done
    return 1
}
driver() {
    local phase=$1
    shift
    docker exec -i -u 1000:1000 -e LIVE_ALPINE="$ALPINE" -e LIVE_UI=cashpilot-ui \
        -e LIVE_UI_VOLUME="${PROJECT}_cashpilot_data" -e LIVE_HAND="$HAND" "$@" \
        cashpilot-worker python - "$phase" <"$ROOT/scripts/socket_proxy_live_driver.py"
}
show() {
    echo "$1" | grep -E '^(PASS|FAIL)' | sed 's/^/    /' || true
}

echo "== 1. seed an install made before owner isolation, through the raw socket"
use_compose "$OLD_ROOT" old
printf 'CASHPILOT_COMPOSE_DIR=%s\nCASHPILOT_UI_PORT=18081\nCASHPILOT_API_KEY=live-test-key\nCASHPILOT_SECRET_KEY=the-ui-session-secret\nCASHPILOT_ALLOW_EPHEMERAL_KEY=true\n' \
    "$WORK_DIR/project" >"$WORK_DIR/project/.env"
compose up -d 2>&1 | tail -2
wait_healthy && pass "the old worker is healthy behind the old proxy" || fail "the old worker is not healthy"
# A fresh old worker makes the fence on its first start; make it the same way if not.
if docker network inspect cashpilot-isolated >/dev/null 2>&1; then
    echo "    the old worker made cashpilot-isolated itself"
else
    docker network create --driver bridge --label cashpilot.isolation=managed \
        -o com.docker.network.bridge.name=cp-isolated -o com.docker.network.bridge.enable_ip_masquerade=false \
        -o com.docker.network.bridge.enable_icc=false cashpilot-isolated >/dev/null
fi
docker volume create "$IDENTITY" >/dev/null
# A keystore, and enough data that the copy takes long enough to be killed in.
docker run --rm -v "$IDENTITY:/v" "$ALPINE" sh -c \
    'mkdir -p /v/keystore && head -c 64 /dev/urandom | od -An -tx1 | tr -d " \n" > /v/keystore/UTC--node-key && chmod 600 /v/keystore/UTC--node-key && head -c 41943040 /dev/urandom > /v/node.db && ln -s keystore/UTC--node-key /v/current'
docker run -d --name "$EARNER" --label cashpilot.managed=true --label cashpilot.service=mysterium \
    --label cashpilot.version=1 --label cashpilot.category=bandwidth --label cashpilot.deployed-by=worker \
    --network cashpilot-isolated -v "$IDENTITY:/var/lib/mysterium-node" --cap-drop ALL \
    --security-opt no-new-privileges:true --restart unless-stopped "$ALPINE" sleep infinity >/dev/null
docker run -d --name "$HAND" -v "$HAND-data:/data" "$ALPINE" sleep infinity >/dev/null
docker run --rm -v "${PROJECT}_cashpilot_fleet:/f" "$ALPINE" sh -c 'echo the-enrolment-key > /f/live-fleet-key'
docker run --rm -v "${PROJECT}_cashpilot_worker_data:/d" "$ALPINE" sh -c 'echo the-worker-state > /d/live-worker-file'
before=$(tree_sum "$IDENTITY")
earner_before=$(docker inspect -f '{{.Id}}' "$EARNER")
hand_before=$(docker inspect -f '{{.Id}}' "$HAND")
echo "    identity $IDENTITY sha256 $before"
for kind in volume network; do
    labels=$(docker "$kind" inspect -f '{{json .Labels}}' "$([ $kind = volume ] && echo "$IDENTITY" || echo cashpilot-isolated)")
    echo "    $kind labels before: $labels"
done

echo "== 2. red control: on the old install the worker reads the UI's data"
rc=0
out=$(driver attacks 2>&1) || rc=$?
echo "$out" | sed 's/^/    | /'
# The driver exits with its number of failures: exactly the three attacks.
[ "$rc" -eq 3 ] || fail "the attacks phase exited $rc, not 3"
[ "$(echo "$out" | count '^FAIL  proxy refuses: .*  20[01] ')" -eq 3 ] && pass "all three attacks succeed before the upgrade" \
    || fail "an attack was already refused before the upgrade, so the checks below prove nothing"

echo "== 2b. the Update button brings the new worker image to the old compose file"
# Most installs get the new image this way first and take the compose file later.
docker tag "$REG/cashpilot-worker:new" "$REG/cashpilot-worker:old"
docker push -q "$REG/cashpilot-worker:old" >/dev/null
new_image=$(docker image inspect -f '{{.Id}}' "$REG/cashpilot-worker:new")
update_worker() {
    out=$(driver update 2>&1) || true
    show "$out"
    FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
    for _ in $(seq 1 90); do docker inspect cashpilot-updater >/dev/null 2>&1 || break; sleep 2; done
    sleep 2
    wait_healthy || true
}
update_worker
[ "$(docker inspect -f '{{.Image}}' cashpilot-worker)" = "$new_image" ] \
    && pass "the old worker's update brought the new image" || fail "the worker does not run the new image"
[ "$(driver access 2>/dev/null)" = proxy ] && pass "it still reaches Docker through the old proxy" \
    || fail "it does not reach Docker through the old proxy"
rc=0
out=$(driver fresh 2>&1) || rc=$?
[ "$rc" -eq 0 ] || fail "the fresh phase exited $rc"
show "$out"
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
[ "$(echo "$out" | count '^PASS')" -eq 3 ] || fail "the fresh-earner checks did not all run"
before_second=$(docker inspect -f '{{.Id}}' cashpilot-worker)
printf 'FROM %s\nLABEL cashpilot.live-test.update=old-compose\n' "$REG/cashpilot-worker:new" \
    | docker build -q -t "$REG/cashpilot-worker:old" - >/dev/null
docker push -q "$REG/cashpilot-worker:old" >/dev/null
# Now the new image's own update helper, on the old compose file's socket volume.
update_worker
if [ "$(docker inspect -f '{{.Id}}' cashpilot-worker)" != "$before_second" ] \
    && [ "$(docker inspect -f '{{index .Config.Labels "cashpilot.live-test.update"}}' cashpilot-worker)" = old-compose ]; then
    pass "the new image updates itself on the old compose file"
else
    fail "the new image cannot update itself there"
fi
if docker volume inspect cashpilot-docker-api-owned >/dev/null 2>&1; then
    fail "the update made an empty cashpilot-docker-api-owned"
else
    pass "the update used the socket volume the worker has"
fi

echo "== 3. upgrade with the new compose file, and kill the migration while it copies the identity"
use_compose "$ROOT" new
(compose up -d --force-recreate >"$WORK_DIR/up1.log" 2>&1; echo "exit $?" >>"$WORK_DIR/up1.log") &
upgrade=$!
killed=""
for _ in $(seq 1 600); do
    logs=$(docker logs cashpilot-migrate 2>&1 || true)
    case "$logs" in
    *"Copying $IDENTITY into its backup"*)
        # Wait for data to land in the backup, so the kill falls inside the copy.
        for _ in $(seq 1 200); do
            got=$(docker exec cashpilot-migrate-copy du -sk /to 2>/dev/null | cut -f1 || true)
            [ "${got:-0}" -ge 1024 ] 2>/dev/null && break
            sleep 0.02
        done
        docker kill cashpilot-migrate >/dev/null 2>&1 || true
        docker kill cashpilot-migrate-copy >/dev/null 2>&1 || true
        killed=yes
        break
        ;;
    esac
    sleep 0.1
done
wait "$upgrade" || true
[ -n "$killed" ] && pass "killed the migration and its copy helper mid-copy" || fail "the copy never started"
tail -4 "$WORK_DIR/up1.log" | sed 's/^/    | /'
docker logs cashpilot-migrate 2>&1 | tail -6 | sed 's/^/    migrate| /'
partial=$(docker run --rm -v "$BACKUP:/b:ro" "$ALPINE" sh -c 'du -sk /b | cut -f1' 2>/dev/null || echo none)
echo "    what the kill left: backup $BACKUP holds ${partial} KiB of ~40964 KiB"
[ "${partial:-0}" -gt 4 ] 2>/dev/null && pass "the kill came after data reached the backup" \
    || fail "the backup was still empty when the kill came (${partial} KiB)"
recorded=$(docker run --rm -v "$WORK_DIR/project:/p:ro" "$ALPINE" sh -c 'ls /p/cashpilot-migrate-state/volumes 2>/dev/null' || true)
[ -z "$recorded" ] && pass "no verified backup was recorded before the kill" || fail "a backup was recorded: $recorded"
[ "$(tree_sum "$IDENTITY")" = "$before" ] && pass "the identity is untouched by the killed run" \
    || fail "the killed run changed the identity"

echo "== 3b. run the upgrade again"
if compose up -d --force-recreate >"$WORK_DIR/up2.log" 2>&1; then pass "the second upgrade run finished"; else
    fail "the second upgrade run failed"
    tail -15 "$WORK_DIR/up2.log"
fi
docker logs cashpilot-migrate 2>&1 | sed 's/^[0-9-]* [0-9:,]* /    migrate| /'

echo "== 4. after the upgrade"
perm=$(docker run --rm -v "$WORK_DIR/project:/p:ro" "$ALPINE" stat -c '%a %u' /p/cashpilot-migrate-state)
[ "$perm" = "700 0" ] && pass "the migration's records are root's only ($perm)" || fail "the records folder is $perm"
wait_healthy && pass "the new worker is healthy behind the new proxy" || fail "the new worker is not healthy"
after=$(tree_sum "$IDENTITY")
[ "$after" = "$before" ] && pass "the identity has the same sha256 ($after)" || fail "identity changed: $before -> $after"
[ "$(tree_sum "$BACKUP")" = "$before" ] && pass "the backup $BACKUP holds the same identity" || fail "the backup differs"
[ "$(docker volume inspect -f '{{index .Labels "cashpilot.backup-of"}}' "$BACKUP")" = "$IDENTITY" ] \
    && pass "the backup says whose data it holds" || fail "the backup carries no cashpilot.backup-of label"
echo "    volume labels after: $(docker volume inspect -f '{{json .Labels}}' "$IDENTITY")"
echo "    network labels after: $(docker network inspect -f '{{json .Labels}}' cashpilot-isolated)"
[ "$(docker volume inspect -f '{{index .Labels "cashpilot.deployed-by"}}' "$IDENTITY")" = worker ] \
    && pass "$IDENTITY carries the owner label" || fail "$IDENTITY carries no owner label"
[ "$(docker network inspect -f '{{index .Labels "cashpilot.deployed-by"}}' cashpilot-isolated)" = worker ] \
    && pass "cashpilot-isolated carries the owner label" || fail "cashpilot-isolated carries no owner label"
[ "$(docker inspect -f '{{.State.Running}}' "$EARNER")" = true ] && pass "the earner is running" || fail "the earner is not running"
[ "$(docker inspect -f '{{.Id}}' "$EARNER")" != "$earner_before" ] && pass "the earner was recreated" || fail "the earner is the old container"
nets=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$EARNER")
[ "$nets" = "cashpilot-isolated " ] && pass "the earner is back on the fence" || fail "the earner is on: $nets"
for pair in "cashpilot_fleet:live-fleet-key:the-enrolment-key" "cashpilot_worker_data:live-worker-file:the-worker-state"; do
    key=${pair%%:*}
    rest=${pair#*:}
    file=${rest%%:*}
    want=${rest#*:}
    got=$(docker run --rm -v "${PROJECT}_${key}_owned:/v:ro" "$ALPINE" cat "/v/$file" 2>&1 || true)
    [ "$got" = "$want" ] && pass "${key}_owned holds what $key held" || fail "${key}_owned: $got"
    docker volume inspect "${PROJECT}_${key}" >/dev/null 2>&1 && pass "the old ${PROJECT}_${key} is kept" \
        || fail "the old ${PROJECT}_${key} is gone"
done
[ "$(docker inspect -f '{{.Id}} {{.State.Running}}' "$HAND")" = "$hand_before true" ] \
    && pass "the hand-started earner is the same container, still running" || fail "the hand-started earner was touched"
[ "$(docker volume inspect -f '{{json .Labels}}' "$HAND-data")" = null ] \
    && pass "its volume was left as it was" || fail "its volume was relabelled"

rc=0
out=$(driver attacks 2>&1) || rc=$?
show "$out"
[ "$rc" -eq 0 ] || fail "the attacks phase exited $rc"
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
[ "$(echo "$out" | count '^PASS')" -eq 3 ] || fail "the attack checks did not all run"
rc=0
out=$(driver hidden 2>&1) || rc=$?
[ "$rc" -eq 0 ] || fail "the hidden phase exited $rc"
show "$out"
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
[ "$(echo "$out" | count '^PASS')" -eq 2 ] || fail "the hidden-container checks did not all run"
rc=0
out=$(driver migrated 2>&1) || rc=$?
[ "$rc" -eq 0 ] || fail "the migrated phase exited $rc"
echo "$out" | sed 's/^/    /'
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
[ "$(echo "$out" | count '^PASS')" -ge 5 ] || fail "the migrated-earner checks did not all run"
[ "$(tree_sum "$IDENTITY")" = "$before" ] && pass "the identity is the same after the worker redeployed it" \
    || fail "the redeploy changed the identity"
nets=$(docker inspect -f '{{range $k, $v := .NetworkSettings.Networks}}{{$k}} {{end}}' "$EARNER")
[ "$nets" = "cashpilot-isolated " ] && pass "the redeployed earner is on the fence" || fail "the redeployed earner is on: $nets"

echo "== 5. a third docker compose up finds nothing to do"
earner_now=$(docker inspect -f '{{.Id}}' "$EARNER")
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
compose up -d >"$WORK_DIR/up3.log" 2>&1 && pass "docker compose up -d again" || fail "docker compose up -d failed again"
logs=$(docker logs --since "$since" cashpilot-migrate 2>&1 || true)
case "$logs" in
*Copying*) fail "the run copied something again" ;;
*"Migration complete"*) pass "the migration ran and found nothing to do" ;;
*) fail "the migration did not report: $(echo "$logs" | tail -2)" ;;
esac
[ "$(docker inspect -f '{{.Id}}' "$EARNER")" = "$earner_now" ] && pass "the earner was left alone" || fail "the earner was recreated again"

echo "== 6. the in-app update recreates the worker through the proxy"
old_worker=$(docker inspect -f '{{.Id}}' cashpilot-worker)
old_ui=$(docker inspect -f '{{.Id}}' cashpilot-ui)
old_proxy=$(docker inspect -f '{{.Id}}' cashpilot-socket-proxy)
docker build -q -t "$REG/cashpilot-worker:new" - >/dev/null <<EOF
FROM $REG/cashpilot-worker:new
LABEL cashpilot.live-test.update=2
EOF
docker push -q "$REG/cashpilot-worker:new" >/dev/null
docker rmi "$REG/cashpilot-worker:new" >/dev/null
since=$(date -u +%Y-%m-%dT%H:%M:%SZ)
out=$(driver update 2>&1) || true
show "$out"
FAILS=$((FAILS + $(echo "$out" | count '^FAIL')))
for _ in $(seq 1 90); do docker inspect cashpilot-updater >/dev/null 2>&1 || break; sleep 2; done
wait_healthy || true
[ "$(docker inspect -f '{{.Id}}' cashpilot-worker 2>/dev/null)" != "$old_worker" ] && pass "the update recreated the worker" \
    || fail "the worker was not recreated"
[ "$(docker inspect -f '{{index .Config.Labels "cashpilot.live-test.update"}}' cashpilot-worker 2>/dev/null)" = 2 ] \
    && pass "the new worker runs the pulled image" || fail "the new worker does not run the pulled image"
[ "$(docker inspect -f '{{.Id}}' cashpilot-ui)" = "$old_ui" ] && pass "the update left the UI alone" || fail "the update recreated the UI"
[ "$(docker inspect -f '{{.Id}}' cashpilot-socket-proxy)" = "$old_proxy" ] && pass "the update left the proxy alone" \
    || fail "the update recreated the proxy"
[ "$(driver access 2>/dev/null)" = proxy ] && pass "the new worker reaches Docker through the proxy" \
    || fail "the new worker does not reach Docker through the proxy"
denied=$(docker logs --since "$since" cashpilot-socket-proxy 2>&1 | grep request_denied | grep -v 'containers/cashpilot-ui/json' | grep -v '"status":404' || true)
# A 404 is the proxy saying a thing does not exist yet (the helper, the image
# before its pull), which is what Compose asks to find out.
[ -z "$denied" ] && pass "the proxy refused nothing the update or Compose asked for" \
    || fail "the proxy refused part of the update: $(echo "$denied" | head -3)"

echo
if [ "$FAILS" -eq 0 ]; then echo "ALL PASSED"; else echo "$FAILS FAILED"; fi
exit "$FAILS"
