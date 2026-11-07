"""The one-shot owner-label migration (app/owner_migrate.py), against an
in-memory Docker. The live proof, real daemon and a killed run included, is
scripts/owner_migration_live_test.sh."""

from __future__ import annotations

import hashlib
import itertools
import json

import pytest
from docker.errors import APIError, NotFound

from app import owner_migrate as om

OWNER = {om.OWNER_LABEL: om.OWNER}
WORKER_LABELS = {"cashpilot.managed": "true", "cashpilot.service": "mysterium", **OWNER}
_ids = itertools.count(1)


def _id() -> str:
    return f"{next(_ids):064x}"


class Crash(BaseException):  # noqa: N818 - a kill, which nothing catches
    """A kill: the run stops right here."""


class Volume:
    def __init__(self, docker, name, labels=None, driver="local", options=None):
        self.docker, self.name = docker, name
        self.attrs = {"Name": name, "Labels": labels, "Driver": driver, "Options": options}

    def remove(self, force=False):
        if any(name == self.name for c in self.docker.cs.values() for name in c.volume_names()):
            raise APIError("volume is in use")
        del self.docker.vols[self.name]


class Network:
    def __init__(self, docker, name, labels=None, options=None, ipam=None):
        self.docker, self.name, self.id = docker, name, _id()
        self.attrs = {
            "Name": name,
            "Id": self.id,
            "Labels": labels or {},
            "Driver": "bridge",
            "Options": options or {},
            "IPAM": ipam or {},
            "Containers": {},
        }

    def reload(self):
        self.attrs["Containers"] = {
            c.id: {"Name": c.name} for c in self.docker.cs.values() if self.name in c.networks()
        }

    def disconnect(self, cid, force=False):
        self.docker.cs[cid].attrs["NetworkSettings"]["Networks"].pop(self.name)

    def connect(self, name, aliases=None, ipv4_address=None, ipv6_address=None):
        c = self.docker.containers.get(name)
        ipam = {k: v for k, v in (("IPv4Address", ipv4_address), ("IPv6Address", ipv6_address)) if v}
        c.attrs["NetworkSettings"]["Networks"][self.name] = {"Aliases": aliases, "IPAMConfig": ipam or None}
        self.docker.connects.append((self.name, name))

    def remove(self):
        self.reload()
        if self.attrs["Containers"]:
            raise APIError("network has active endpoints")
        del self.docker.nets[self.name]


class Container:
    def __init__(
        self,
        docker,
        name,
        labels,
        mounts=(),
        networks=("bridge",),
        image="sha256:img",
        host=None,
        config=None,
        running=True,
    ):
        self.docker, self.id, self.name = docker, _id(), name
        self.attrs = {
            "Id": self.id,
            "Name": "/" + name,
            "Image": image,
            "Config": {"Image": "earner:1", "Labels": dict(labels), "Hostname": name, **(config or {})},
            "HostConfig": {
                "NetworkMode": networks[0] if networks else "none",
                "Binds": [f"{v}:{t}" for v, t in mounts],
                **(host or {}),
            },
            "Mounts": [{"Type": "volume", "Name": v, "Destination": t, "RW": True} for v, t in mounts],
            "NetworkSettings": {"Networks": {n: {"Aliases": [name]} for n in networks}},
            "State": {"Running": running},
        }

    @property
    def labels(self):
        return self.attrs["Config"]["Labels"]

    @property
    def status(self):
        return "running" if self.attrs["State"]["Running"] else "exited"

    def volume_names(self):
        return [m["Name"] for m in self.attrs["Mounts"]]

    def networks(self):
        return list(self.attrs["NetworkSettings"]["Networks"])

    def start(self):
        self.attrs["State"]["Running"] = True

    def remove(self, force=False):
        self.docker.removed.append(self.name)
        del self.docker.cs[self.id]


class Containers:
    def __init__(self, docker):
        self.docker = docker

    def get(self, ref):
        for c in self.docker.cs.values():
            if ref in (c.id, c.name):
                return c
        raise NotFound(ref)

    def list(self, all=False, filters=None):
        out = list(self.docker.cs.values())
        for f in (
            (filters or {}).get("label", [])
            if isinstance((filters or {}).get("label"), list)
            else [(filters or {}).get("label")]
        ):
            if f is None:
                continue
            key, _, value = f.partition("=")
            out = [c for c in out if key in c.labels and (not value or c.labels[key] == value)]
        if "volume" in (filters or {}):
            out = [c for c in out if filters["volume"] in c.volume_names()]
        return out


class Volumes:
    def __init__(self, docker):
        self.docker = docker

    def get(self, name):
        if name not in self.docker.vols:
            raise NotFound(name)
        return self.docker.vols[name]

    def create(self, name, driver="local", labels=None):
        self.docker.vols[name] = Volume(self.docker, name, labels)
        self.docker.data.setdefault(name, {})
        return self.docker.vols[name]

    def list(self, filters=None):
        wanted = dict(f.split("=", 1) for f in (filters or {}).get("label", []))
        return [
            v
            for v in self.docker.vols.values()
            if all((v.attrs["Labels"] or {}).get(k) == x for k, x in wanted.items())
        ]


class Networks:
    def __init__(self, docker):
        self.docker = docker

    def get(self, name):
        if name not in self.docker.nets:
            raise NotFound(name)
        return self.docker.nets[name]

    def list(self, filters=None):
        key = (filters or {}).get("label")
        return [n for n in self.docker.nets.values() if key in n.attrs["Labels"]]

    def create(
        self,
        name,
        driver=None,
        options=None,
        ipam=None,
        enable_ipv6=False,
        internal=False,
        attachable=False,
        labels=None,
    ):
        net = Network(self.docker, name, labels, options, ipam)
        self.docker.nets[name] = net
        return net


class Images:
    def __init__(self, docker):
        self.docker = docker

    def get(self, ref):
        if ref in self.docker.tags:
            return type("I", (), {"id": self.docker.tags[ref]})()
        raise NotFound(ref)


class Api:
    def __init__(self, docker):
        self.docker = docker
        self.crash_on_create = False

    def stop(self, cid):
        self.docker.cs[cid].attrs["State"]["Running"] = False

    def start(self, cid):
        self.docker.cs[cid].attrs["State"]["Running"] = True

    def _url(self, path):
        return path

    def _post_json(self, url, data, params):
        if self.crash_on_create:
            self.crash_on_create = False
            raise Crash("killed while recreating")
        d = self.docker
        c = Container(d, params["name"], data["Labels"], running=False, image=data["Image"])
        c.attrs["Config"] = {k: v for k, v in data.items() if k not in ("HostConfig", "NetworkingConfig")}
        c.attrs["HostConfig"] = data["HostConfig"]
        mounts = []
        for bind in data["HostConfig"].get("Binds") or []:
            src, dst = bind.split(":")[:2]
            if src not in d.vols:
                raise APIError(f"no such volume {src}")
            mounts.append({"Type": "volume", "Name": src, "Destination": dst, "RW": True})
        c.attrs["Mounts"] = mounts
        c.attrs["NetworkSettings"]["Networks"] = {
            n: dict(ep) for n, ep in data["NetworkingConfig"]["EndpointsConfig"].items()
        } or ({} if data["HostConfig"]["NetworkMode"] != "bridge" else {"bridge": {}})
        for n in c.networks():
            if n != "bridge" and n not in d.nets:
                raise APIError(f"no such network {n}")
        d.cs[c.id] = c
        d.created.append(params["name"])
        return c.id

    def _result(self, resp, json_=False):
        return {"Id": resp}


class FakeDocker:
    def __init__(self):
        self.cs: dict[str, Container] = {}
        self.vols: dict[str, Volume] = {}
        self.nets: dict[str, Network] = {"bridge": Network(self, "bridge")}
        self.data: dict[str, dict[str, str]] = {}
        self.tags = {"earner:1": "sha256:img"}
        self.removed, self.created, self.connects = [], [], []
        self.containers, self.volumes, self.networks = Containers(self), Volumes(self), Networks(self)
        self.images, self.api = Images(self), Api(self)

    def add(self, container: Container) -> Container:
        self.cs[container.id] = container
        return container

    def volume(self, name, files=None, labels=None, **kw):
        self.vols[name] = Volume(self, name, labels, **kw)
        self.data[name] = dict(files or {})


def _digest(files: dict[str, str]) -> dict:
    return {
        "digest": hashlib.sha256(json.dumps(sorted(files.items())).encode()).hexdigest(),
        "files": len(files),
        "bytes": sum(len(v) for v in files.values()),
    }


class FakeMigrator(om.Migrator):
    def __init__(self, docker, state, **kw):
        super().__init__(docker, state, image="sha256:worker", project="cashpilot", **kw)
        self.docker = docker
        self.copies: list[tuple[str, str]] = []
        self.crash_at: int | None = None  # kill during the Nth copy, after it wiped the target
        self.fail_copies = 0  # the next N copies fail with an error, as a full disk would

    def copy(self, source, target):
        self.docker.data[target] = {}
        if self.fail_copies:
            self.fail_copies -= 1
            raise RuntimeError(f"no space left copying {source} into {target}")
        if self.crash_at is not None and len(self.copies) + 1 == self.crash_at:
            self.crash_at = None
            self.docker.data[target] = {"half": "copied"}
            raise Crash(f"killed copying {source} into {target}")
        self.copies.append((source, target))
        self.docker.data[target] = dict(self.docker.data[source])
        return _digest(self.docker.data[target])


IDENTITY = {"keystore/UTC--key": "the private key", "node.db": "settings"}


@pytest.fixture
def install():
    """An install made before owner isolation, through the raw socket."""
    d = FakeDocker()
    d.volume("mysterium-data", IDENTITY)
    d.nets["cashpilot-isolated"] = Network(
        d,
        "cashpilot-isolated",
        {"cashpilot.isolation": "managed"},
        {"com.docker.network.bridge.name": "cashpilot0"},
        {"Driver": "default", "Config": [{"Subnet": "172.30.0.0/24", "Gateway": "172.30.0.1"}]},
    )
    myst = d.add(
        Container(
            d,
            "cashpilot-mysterium",
            WORKER_LABELS,
            [("mysterium-data", "/var/lib/mysterium-node")],
            networks=("cashpilot-isolated",),
        )
    )
    d.volume("hand-data", {"x": "1"})
    hand = d.add(Container(d, "my-honeygain", {}, [("hand-data", "/data")]))
    return d, myst, hand


def _run(m: om.Migrator) -> int:
    try:
        return m.run([])
    except Crash:
        return -9


def test_the_identity_moves_onto_a_labelled_volume_of_the_same_name(install, tmp_path):
    d, myst, hand = install
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run([]) == 0
    assert d.vols["mysterium-data"].attrs["Labels"] == OWNER
    assert d.data["mysterium-data"] == IDENTITY
    backup = d.vols[om.backup_name("mysterium-data")]
    assert backup.attrs["Labels"] == {om.BACKUP_LABEL: "mysterium-data"}
    assert d.data[backup.name] == IDENTITY
    new = d.containers.get("cashpilot-mysterium")
    assert new.id != myst.id and new.status == "running"
    assert new.labels == {**WORKER_LABELS, om.RECREATED_LABEL: myst.id}
    assert new.volume_names() == ["mysterium-data"]
    assert new.networks() == ["cashpilot-isolated"]
    assert d.nets["cashpilot-isolated"].attrs["Labels"] == {"cashpilot.isolation": "managed", **OWNER}
    assert d.nets["cashpilot-isolated"].attrs["Options"] == {"com.docker.network.bridge.name": "cashpilot0"}
    # The container the user started by hand, and its volume, are not CashPilot's.
    assert d.containers.get("my-honeygain") is hand and hand.status == "running"
    assert d.vols["hand-data"].attrs["Labels"] is None


def test_a_second_run_finds_nothing_to_do(install, tmp_path):
    d, _, _ = install
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    before = d.containers.get("cashpilot-mysterium").id
    again = FakeMigrator(d, om.State(tmp_path))
    assert again.run([]) == 0
    assert again.copies == []
    assert d.containers.get("cashpilot-mysterium").id == before


def test_a_stopped_earner_stays_stopped(tmp_path):
    d = FakeDocker()
    d.volume("earnapp-data", {"uuid": "sdk-node-1"})
    d.add(Container(d, "cashpilot-earnapp", WORKER_LABELS, [("earnapp-data", "/etc/earnapp")], running=False))
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert d.containers.get("cashpilot-earnapp").status == "exited"


def test_a_backup_that_fails_puts_the_earner_back_to_work_and_counts_once(install, tmp_path):
    d, myst, _ = install
    for _ in range(2):
        failing = FakeMigrator(d, om.State(tmp_path))
        failing.fail_copies = 1  # a full disk
        assert failing.run([]) == 1
        assert failing.failures == 1
        # Nothing was removed, so the same earner earns on its own volume again.
        assert d.containers.get("cashpilot-mysterium") is myst and myst.status == "running"
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert d.containers.get("cashpilot-mysterium").status == "running"
    assert d.data["mysterium-data"] == IDENTITY


def test_one_earner_that_will_not_start_again_does_not_keep_the_others_stopped(tmp_path):
    d = FakeDocker()
    d.volume("shared", {"f": "1"})
    first = d.add(Container(d, "cashpilot-a", WORKER_LABELS, [("shared", "/s")]))
    second = d.add(Container(d, "cashpilot-b", WORKER_LABELS, [("shared", "/s")]))
    failing = FakeMigrator(d, om.State(tmp_path))
    failing.fail_copies = 1
    real_start = d.api.start

    def start(cid):
        if cid == first.id:
            raise RuntimeError("port already in use")
        real_start(cid)

    d.api.start = start
    assert failing.run([]) == 1
    # The backup error and the earner that would not start, each reported.
    assert failing.failures == 2
    assert first.status == "exited" and second.status == "running"
    # The plan stays, so the retry still knows cashpilot-a was running; its
    # backup record does not, so the retry copies the volume again.
    assert om.State(tmp_path).all("volumes") == []
    assert len(om.State(tmp_path).all("plans")) == 1
    d.api.start = real_start
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert {c.status for c in (d.containers.get("cashpilot-a"), d.containers.get("cashpilot-b"))} == {"running"}


def test_after_a_failed_backup_the_retry_copies_what_the_earner_wrote_since(tmp_path):
    d = FakeDocker()
    d.volume("a-data", {"f": "old"})
    d.volume("b-data", {"g": "1"})
    c = d.add(Container(d, "cashpilot-two", WORKER_LABELS, [("a-data", "/a"), ("b-data", "/b")]))
    failing = FakeMigrator(d, om.State(tmp_path))
    real_copy = failing.copy

    def second_fails(source, target):
        if source == "b-data":
            raise RuntimeError("no space left")
        return real_copy(source, target)

    failing.copy = second_fails
    assert failing.run([]) == 1
    assert c.status == "running"
    d.data["a-data"] = {"f": "new"}  # the earner kept working
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert d.data["a-data"] == {"f": "new"}


@pytest.mark.parametrize("crash_at", [1, 2], ids=["killed copying into the backup", "killed copying back"])
def test_a_run_killed_mid_copy_is_finished_by_the_next(install, tmp_path, crash_at):
    d, _, _ = install
    first = FakeMigrator(d, om.State(tmp_path))
    first.crash_at = crash_at
    assert _run(first) == -9
    # Whatever the kill left, the identity is whole in one verified place.
    assert IDENTITY in (d.data.get("mysterium-data"), d.data.get(om.backup_name("mysterium-data")))
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert d.data["mysterium-data"] == IDENTITY
    assert d.data[om.backup_name("mysterium-data")] == IDENTITY
    assert d.vols["mysterium-data"].attrs["Labels"] == OWNER
    assert d.containers.get("cashpilot-mysterium").status == "running"


def test_a_run_killed_after_the_container_went_recreates_it(install, tmp_path):
    d, myst, _ = install
    first = FakeMigrator(d, om.State(tmp_path))
    d.api.crash_on_create = True
    assert _run(first) == -9
    with pytest.raises(NotFound):
        d.containers.get("cashpilot-mysterium")
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    new = d.containers.get("cashpilot-mysterium")
    assert new.status == "running" and new.volume_names() == ["mysterium-data"]
    assert d.data["mysterium-data"] == IDENTITY


def test_a_run_killed_at_every_copy_still_ends_whole(install, tmp_path):
    d, _, _ = install
    state = om.State(tmp_path)
    for attempt in range(1, 6):
        m = FakeMigrator(d, state)
        m.crash_at = 1
        if _run(m) != -9:
            break
        assert IDENTITY in (d.data.get("mysterium-data"), d.data.get(om.backup_name("mysterium-data"))), attempt
    assert FakeMigrator(d, state).run([]) == 0
    assert d.data["mysterium-data"] == IDENTITY


def test_a_volume_another_container_shares_is_left_alone(install, tmp_path):
    d, myst, _ = install
    d.add(Container(d, "users-backup-job", {}, [("mysterium-data", "/backup")]))
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run([]) == 0 and m.warnings == 1
    assert d.vols["mysterium-data"].attrs["Labels"] is None
    assert d.containers.get("cashpilot-mysterium") is myst
    assert m.copies == []


def test_a_volume_with_driver_options_is_left_alone(tmp_path):
    d = FakeDocker()
    d.volume("storj-identity", {"id": "x"}, options={"type": "none", "o": "bind", "device": "/mnt/storj"})
    c = d.add(Container(d, "cashpilot-storj", WORKER_LABELS, [("storj-identity", "/app/identity")]))
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run([]) == 0 and m.warnings == 1
    assert d.containers.get("cashpilot-storj") is c and m.copies == []


def test_a_fence_shared_with_a_users_container_is_left_alone(install, tmp_path):
    d, _, hand = install
    hand.attrs["NetworkSettings"]["Networks"]["cashpilot-isolated"] = {}
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run([]) == 0 and m.warnings == 1
    assert om.OWNER_LABEL not in d.nets["cashpilot-isolated"].attrs["Labels"]


def test_the_operators_own_bridge_the_earners_are_on_gets_the_label(tmp_path):
    d = FakeDocker()
    d.nets["my-earners"] = Network(d, "my-earners", {}, {"com.docker.network.bridge.name": "cp-isolated"})
    d.add(Container(d, "cashpilot-honeygain", WORKER_LABELS, networks=("my-earners",)))
    d.add(Container(d, "cashpilot-repocket", WORKER_LABELS, networks=("bridge",)))
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert d.nets["my-earners"].attrs["Labels"] == OWNER
    assert d.nets["my-earners"].attrs["Options"] == {"com.docker.network.bridge.name": "cp-isolated"}
    assert d.containers.get("cashpilot-honeygain").networks() == ["my-earners"]
    assert d.nets["bridge"].attrs["Labels"] == {}


def test_a_member_with_a_static_address_gets_it_back_before_anyone_else_connects(tmp_path):
    d = FakeDocker()
    d.nets["my-earners"] = Network(d, "my-earners", {}, {})
    d.add(Container(d, "cashpilot-honeygain", WORKER_LABELS, networks=("my-earners",)))
    pinned = d.add(Container(d, "cashpilot-repocket", WORKER_LABELS, networks=("my-earners",)))
    pinned.attrs["NetworkSettings"]["Networks"]["my-earners"]["IPAMConfig"] = {"IPv4Address": "172.30.0.9"}
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    endpoint = d.containers.get("cashpilot-repocket").attrs["NetworkSettings"]["Networks"]["my-earners"]
    assert endpoint["IPAMConfig"] == {"IPv4Address": "172.30.0.9"}
    assert [n for net, n in d.connects if net == "my-earners"][0] == "cashpilot-repocket"


def test_renamed_compose_volumes_are_copied_once_and_the_old_ones_kept(tmp_path):
    d = FakeDocker()
    labels = lambda key: {"com.docker.compose.project": "cashpilot", "com.docker.compose.volume": key}  # noqa: E731
    d.volume("cashpilot_cashpilot_fleet", {"fleet_key": "enrol"}, labels=labels("cashpilot_fleet"))
    d.volume("cashpilot_cashpilot_fleet_owned", {}, labels={**labels("cashpilot_fleet_owned"), **OWNER})
    pairs = [("cashpilot_fleet", "cashpilot_fleet_owned"), ("cashpilot_worker_data", "cashpilot_worker_data_owned")]
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run(pairs) == 0
    assert d.data["cashpilot_cashpilot_fleet_owned"] == {"fleet_key": "enrol"}
    assert d.data["cashpilot_cashpilot_fleet"] == {"fleet_key": "enrol"}
    d.data["cashpilot_cashpilot_fleet_owned"]["fleet_key"] = "rotated since"
    again = FakeMigrator(d, om.State(tmp_path))
    assert again.run(pairs) == 0
    assert again.copies == []
    assert d.data["cashpilot_cashpilot_fleet_owned"] == {"fleet_key": "rotated since"}


def test_a_leftover_helper_the_worker_cannot_remove_any_more_goes(tmp_path):
    d = FakeDocker()
    d.add(Container(d, "cashpilot-updater", {"cashpilot.updater": "true"}, running=False))
    running = d.add(Container(d, "cashpilot-fence", {"cashpilot.probe": "fence"}, running=True))
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert "cashpilot-updater" in d.removed
    assert d.containers.get("cashpilot-fence") is running


def test_the_recreate_names_an_anonymous_volume_and_keeps_the_image_it_ran(tmp_path):
    d = FakeDocker()
    d.tags["earner:1"] = "sha256:newer"
    c = Container(d, "cashpilot-x", WORKER_LABELS, networks=())
    c.attrs["HostConfig"]["NetworkMode"] = "container:abc"
    c.attrs["Mounts"] = [{"Type": "volume", "Name": "f" * 64, "Destination": "/var/lib/x", "RW": True}]
    body = FakeMigrator(d, om.State(tmp_path)).create_body(c.attrs)
    assert body["Image"] == "sha256:img"
    assert f"{'f' * 64}:/var/lib/x" in body["HostConfig"]["Binds"]
    assert "Hostname" not in body
    assert body["Labels"][om.OWNER_LABEL] == om.OWNER
    assert body["NetworkingConfig"] == {"EndpointsConfig": {}}


def test_the_compose_volume_list_parses_like_the_compose_files_write_it():
    assert om._pairs("a=b, c=d,,bad") == [("a", "b"), ("c", "d")]
    assert om._pairs("") == []


def test_a_volume_that_only_shares_the_backups_name_is_never_copied_into(install, tmp_path):
    d, myst, _ = install
    stray = om.backup_name("mysterium-data")
    d.volume(stray, {"photos": "the operator's own"})
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run([]) == 1
    assert d.data[stray] == {"photos": "the operator's own"}
    assert m.copies == []
    # Nothing was removed: the earner earns on its own volume, as before.
    assert d.containers.get("cashpilot-mysterium") is myst and myst.status == "running"
    assert d.data["mysterium-data"] == IDENTITY


def test_a_backup_of_another_volume_is_not_reused_either(install, tmp_path):
    d, _, _ = install
    stray = om.backup_name("mysterium-data")
    d.volume(stray, {"k": "v"}, labels={om.BACKUP_LABEL: "some-other-volume"})
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 1
    assert d.data[stray] == {"k": "v"}


def _compose(key, owner=False):
    return {"com.docker.compose.project": "cashpilot", "com.docker.compose.volume": key, **(OWNER if owner else {})}


def test_the_old_worker_is_stopped_before_its_volume_is_copied(tmp_path):
    d = FakeDocker()
    d.volume("cashpilot_cashpilot_worker_data", {".worker_key": "k1"}, labels=_compose("cashpilot_worker_data"))
    d.volume("cashpilot_cashpilot_worker_data_owned", {}, labels=_compose("cashpilot_worker_data_owned", True))
    old = d.add(Container(d, "cashpilot-worker", {}, [("cashpilot_cashpilot_worker_data", "/data")]))
    me = d.add(Container(d, "cashpilot-migrate", {}, [("cashpilot_cashpilot_worker_data", "/peek")]))
    m = FakeMigrator(d, om.State(tmp_path), self_id=me.id)
    real_copy = m.copy
    seen = []

    def copy(source, target):
        seen.append(old.status)
        return real_copy(source, target)

    m.copy = copy
    assert m.run([("cashpilot_worker_data", "cashpilot_worker_data_owned")]) == 0
    assert seen == ["exited"]
    assert me.status == "running"
    assert d.data["cashpilot_cashpilot_worker_data_owned"] == {".worker_key": "k1"}


def test_a_new_compose_volume_without_the_label_is_refused_before_any_copy(tmp_path):
    d = FakeDocker()
    d.volume("cashpilot_cashpilot_fleet", {"fleet_key": "enrol"}, labels=_compose("cashpilot_fleet"))
    d.volume("cashpilot_cashpilot_fleet_owned", {}, labels=_compose("cashpilot_fleet_owned"))
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run([("cashpilot_fleet", "cashpilot_fleet_owned")]) == 1
    assert m.copies == []


def _two_on_a_bridge():
    d = FakeDocker()
    d.nets["my-earners"] = Network(d, "my-earners", {}, {})
    a = d.add(Container(d, "cashpilot-a", WORKER_LABELS, networks=("my-earners",)))
    b = d.add(Container(d, "cashpilot-b", WORKER_LABELS, networks=("my-earners",)))
    return d, a, b


def _crash_on_second_disconnect(net):
    real, calls = net.disconnect, []

    def disconnect(cid, force=False):
        calls.append(cid)
        if len(calls) == 2:
            raise Crash("killed while disconnecting")
        real(cid, force)

    net.disconnect = disconnect
    return real


def test_a_stranger_that_joined_before_the_retry_leaves_the_network_whole(tmp_path):
    d, a, b = _two_on_a_bridge()
    net = d.nets["my-earners"]
    real = _crash_on_second_disconnect(net)
    assert _run(FakeMigrator(d, om.State(tmp_path))) == -9
    net.disconnect = real
    stranger = d.add(Container(d, "my-own-app", {}, networks=("my-earners",)))
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run([]) == 0 and m.warnings == 1
    assert d.nets["my-earners"] is net and om.OWNER_LABEL not in net.attrs["Labels"]
    for c in (a, b, stranger):
        assert "my-earners" in c.networks(), c.name


def test_a_worker_container_that_joined_before_the_retry_comes_along(tmp_path):
    d, a, b = _two_on_a_bridge()
    real = _crash_on_second_disconnect(d.nets["my-earners"])
    assert _run(FakeMigrator(d, om.State(tmp_path))) == -9
    d.nets["my-earners"].disconnect = real
    late = d.add(Container(d, "cashpilot-c", WORKER_LABELS, networks=("my-earners",)))
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert d.nets["my-earners"].attrs["Labels"] == OWNER
    for c in (a, b, late):
        assert "my-earners" in c.networks(), c.name


def test_a_network_that_cannot_be_made_again_is_made_by_the_next_run(tmp_path):
    d, a, b = _two_on_a_bridge()
    real_create = d.networks.create

    def taken(*args, **kw):
        raise APIError("Pool overlaps with other one on this address space")

    d.networks.create = taken
    m = FakeMigrator(d, om.State(tmp_path))
    assert m.run([]) == 1
    d.networks.create = real_create
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    assert d.nets["my-earners"].attrs["Labels"] == OWNER
    assert "my-earners" in a.networks() and "my-earners" in b.networks()


def test_a_container_that_took_the_earners_name_is_not_taken_for_it(install, tmp_path):
    d, _, _ = install
    d.api.crash_on_create = True
    assert _run(FakeMigrator(d, om.State(tmp_path))) == -9
    squatter = d.add(Container(d, "cashpilot-mysterium", {}, running=False))
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 1
    assert squatter.status == "exited"
    squatter.remove()
    assert FakeMigrator(d, om.State(tmp_path)).run([]) == 0
    new = d.containers.get("cashpilot-mysterium")
    assert new.status == "running" and new.volume_names() == ["mysterium-data"]
