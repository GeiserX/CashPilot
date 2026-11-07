"""One-shot migration to the socket proxy's owner isolation.

The proxy lets the worker touch only containers, volumes and networks that
carry ``cashpilot.deployed-by=worker`` (app/socket_policy.py, ``ownership``).
Docker cannot add a label to an existing volume or network, so what an older
release made without it would become unusable through the proxy: a Mysterium
identity volume could no longer be mounted by the next update of that node.

This runs from the compose file with the host's raw socket, before the proxy
starts (``cashpilot-migrate``, which the proxy depends on), and does three jobs:

- copies each compose volume the file renamed (the worker's data, the fleet
  key) from its old name into its new, labelled one, and leaves the old one;
- recreates an unlabelled fence network (``cashpilot-isolated``) with the
  label, and puts its containers back on it;
- moves every named volume a worker container uses onto a labelled volume of
  the same name: the container is stopped, the volume copied to a backup and
  verified, the container removed, the volume recreated with the label, the
  backup copied back and verified, and the container recreated as it was.

Every step is recorded in the state volume before the next one starts, so a
run killed at any point is finished by the next one. Backups and old volumes
are never deleted; UPGRADING.md says how to remove them.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import socket
import sys
from pathlib import Path
from typing import Any

from app.socket_policy import OWNER, OWNER_LABEL

logger = logging.getLogger("cashpilot.migrate")
#: On a backup volume: the volume whose data it holds.
BACKUP_LABEL = "cashpilot.backup-of"
BACKUP_SUFFIX = "-pre-isolation"
#: On every helper container, so a leftover from a killed run can be found.
HELPER_LABEL = "cashpilot.migrate"
HELPER_NAME = "cashpilot-migrate-copy"
#: The fence network's own label (app/lan_fence.py NETWORK_LABEL).
FENCE_LABEL = "cashpilot.isolation"
#: Docker's own networks: they carry no labels and cannot be recreated.
BUILTIN_NETWORKS = frozenset({"bridge", "host", "none", "default"})
#: Labels of the short-lived containers older workers left behind on a crash.
HELPER_KINDS = ("cashpilot.updater", "cashpilot.probe")

#: Wipes /to, copies /from into it with owners, modes and links, then prints
#: a digest of each tree (paths, types, modes, owners, contents, link targets).
COPY_SCRIPT = r"""
import hashlib, json, os, shutil, subprocess, sys
src, dst = "/from", "/to"
for entry in os.listdir(dst):
    path = os.path.join(dst, entry)
    if os.path.isdir(path) and not os.path.islink(path):
        shutil.rmtree(path)
    else:
        os.unlink(path)
subprocess.run(["cp", "-a", src + "/.", dst + "/"], check=True)
st = os.lstat(src)
os.chown(dst, st.st_uid, st.st_gid)
os.chmod(dst, st.st_mode & 0o7777)

def digest(root):
    h, files, size = hashlib.sha256(), 0, 0
    paths = [root]
    for dirpath, dirnames, filenames in os.walk(root):
        paths += [os.path.join(dirpath, n) for n in dirnames + filenames]
    for path in sorted(paths):
        st = os.lstat(path)
        rel = os.path.relpath(path, root)
        h.update(f"{rel}\0{st.st_mode}\0{st.st_uid}\0{st.st_gid}\0".encode())
        if os.path.islink(path):
            h.update(os.readlink(path).encode())
        elif os.path.isfile(path):
            files += 1
            size += st.st_size
            with open(path, "rb") as fh:
                for chunk in iter(lambda: fh.read(1 << 20), b""):
                    h.update(chunk)
        h.update(b"\n")
    return {"digest": h.hexdigest(), "files": files, "bytes": size}

print(json.dumps({"from": digest(src), "to": digest(dst)}))
"""


class MigrationError(RuntimeError):
    pass


class LeftAlone(MigrationError):  # noqa: N818 - not a failure: something else shares it
    """Not CashPilot's alone, so not touched. A warning, not a failure: the stack
    still starts, and the worker names it if it ever needs it."""


def owned(labels: dict[str, str] | None) -> bool:
    return (labels or {}).get(OWNER_LABEL) == OWNER


def backup_name(volume: str) -> str:
    return volume + BACKUP_SUFFIX


class State:
    """One JSON file per record, written atomically, in the state folder."""

    def __init__(self, root: Path) -> None:
        self.root = root

    def _path(self, kind: str, key: str) -> Path:
        return self.root / kind / f"{key}.json"

    def get(self, kind: str, key: str) -> dict[str, Any] | None:
        path = self._path(kind, key)
        return json.loads(path.read_text()) if path.exists() else None

    def put(self, kind: str, key: str, record: dict[str, Any]) -> None:
        path = self._path(kind, key)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(record, indent=1, sort_keys=True))
        os.replace(tmp, path)

    def drop(self, kind: str, key: str) -> None:
        self._path(kind, key).unlink(missing_ok=True)

    def all(self, kind: str) -> list[dict[str, Any]]:
        folder = self.root / kind
        return [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))] if folder.is_dir() else []


class Migrator:
    def __init__(self, client: Any, state: State, image: str, project: str = "") -> None:
        self.client = client
        self.state = state
        self.image = image
        self.project = project
        self.failures = 0
        self.warnings = 0

    # -- Docker primitives (the unit tests replace these) --------------------

    def copy(self, source: str, target: str) -> dict[str, Any]:
        """Copy volume ``source`` into volume ``target`` (wiped first); both digests."""
        self._remove_helper()
        helper = self.client.containers.run(
            self.image,
            entrypoint=["python", "-c", COPY_SCRIPT],
            command=[],
            name=HELPER_NAME,
            user="0:0",
            volumes={source: {"bind": "/from", "mode": "ro"}, target: {"bind": "/to", "mode": "rw"}},
            network_mode="none",
            cap_drop=["ALL"],
            cap_add=["CHOWN", "DAC_OVERRIDE", "FOWNER", "FSETID"],
            security_opt=["no-new-privileges:true"],
            labels={HELPER_LABEL: "copy"},
            detach=True,
        )
        try:
            status = helper.wait()
            out = helper.logs(stdout=True, stderr=True).decode("utf-8", "replace").strip()
        finally:
            self._remove_helper()
        if (status or {}).get("StatusCode") != 0:
            raise MigrationError(f"copying {source} into {target} failed: {out[-400:]}")
        result = json.loads(out.splitlines()[-1])
        if result["from"] != result["to"]:
            raise MigrationError(f"the copy of {source} in {target} does not match it: {result}")
        return result["from"]

    def _remove_helper(self) -> None:
        from docker.errors import NotFound

        with contextlib.suppress(NotFound):
            self.client.containers.get(HELPER_NAME).remove(force=True)

    # -- the run ------------------------------------------------------------

    def run(self, compose_volumes: list[tuple[str, str]]) -> int:
        self._remove_helper()
        for job in (
            lambda: self.copy_compose_volumes(compose_volumes),
            self.remove_stale_helpers,
            self.migrate_networks,
            self.migrate_volumes,
        ):
            try:
                job()
            except Exception as exc:  # noqa: BLE001 - logged; the next job and the next run go on
                self.fail(f"{exc}")
        if self.failures:
            logger.error(
                "Migration incomplete (%d problem(s) above). An earner named above may be stopped or "
                "removed, but no data is lost: each volume it removed has a checked backup and each "
                "container it removed is recorded. Fix what is named, then run docker compose up -d "
                "again: it carries on from where this run stopped.",
                self.failures,
            )
            return 1
        if self.warnings:
            logger.warning("Migration done, with %d thing(s) left as they were (above).", self.warnings)
        else:
            logger.info("Migration complete: everything the worker uses carries %s=%s.", OWNER_LABEL, OWNER)
        return 0

    def fail(self, message: str) -> None:
        self.failures += 1
        logger.error("%s", message)

    def warn(self, message: str) -> None:
        self.warnings += 1
        logger.warning("%s", message)

    # -- compose volumes ----------------------------------------------------

    def _compose_volume(self, key: str) -> Any | None:
        found = self.client.volumes.list(
            filters={"label": [f"com.docker.compose.project={self.project}", f"com.docker.compose.volume={key}"]}
        )
        return found[0] if found else None

    def copy_compose_volumes(self, pairs: list[tuple[str, str]]) -> None:
        """Copy each renamed compose volume into its new name, once; the old one stays."""
        for old_key, new_key in pairs:
            old = self._compose_volume(old_key)
            if old is None:
                continue
            new = self._compose_volume(new_key)
            if new is None:
                raise MigrationError(f"{new_key} does not exist; run this from docker compose up, which creates it")
            if (self.state.get("compose", new.name) or {}).get("done"):
                continue
            result = self.copy(old.name, new.name)
            self.state.put("compose", new.name, {"done": True, "from": old.name, "digest": result})
            logger.info(
                "Copied %s into %s (%d files, sha256 %s). %s is left as it was, as a backup.",
                old.name,
                new.name,
                result["files"],
                result["digest"],
                old.name,
            )

    # -- leftovers ----------------------------------------------------------

    def remove_stale_helpers(self) -> None:
        """Stopped helper containers an older worker left behind and could no longer remove."""
        for kind in HELPER_KINDS:
            for c in self.client.containers.list(all=True, filters={"label": kind}):
                if not owned(c.labels) and c.status != "running":
                    logger.info("Removing the leftover helper container %s", c.name)
                    c.remove(force=True)

    # -- networks -----------------------------------------------------------

    def migrate_networks(self) -> None:
        """The LAN fence's network, and any network of the operator's that worker
        containers are on (CASHPILOT_CONTAINER_NETWORK). Docker's own are left."""
        from docker.errors import NotFound

        names = {r["name"] for r in self.state.all("networks") if not r.get("done")}
        for net in self.client.networks.list(filters={"label": FENCE_LABEL}):
            names.add((net.attrs or {}).get("Name") or net.name)
        for c in self.client.containers.list(all=True, filters={"label": f"{OWNER_LABEL}={OWNER}"}):
            names.update(((c.attrs or {}).get("NetworkSettings") or {}).get("Networks") or {})
        for name in sorted(names - BUILTIN_NETWORKS):
            try:
                if (self.state.get("networks", name) or {}).get("done"):
                    continue
                if self.state.get("networks", name) is None:
                    try:
                        if owned((self.client.networks.get(name).attrs or {}).get("Labels")):
                            continue
                    except NotFound:
                        continue
                self.migrate_network(name)
            except LeftAlone as exc:
                self.warn(f"Network {name}: {exc}")
            except Exception as exc:  # noqa: BLE001 - logged, the others go on
                self.fail(f"Network {name}: {exc}")

    def migrate_network(self, name: str) -> None:
        from docker.errors import NotFound

        record = self.state.get("networks", name)
        if record is None:
            net = self.client.networks.get(name)
            net.reload()
            attrs = net.attrs or {}
            members = []
            for cid in attrs.get("Containers") or {}:
                c = self.client.containers.get(cid)
                if not owned(c.labels):
                    raise LeftAlone(
                        f"{c.name} is on it and was not deployed by the worker, so the network was left as it "
                        f"was, and the worker cannot put services on it. To move it, disconnect that container "
                        f"(docker network disconnect {name} {c.name}) and run docker compose up -d again."
                    )
                endpoint = ((c.attrs.get("NetworkSettings") or {}).get("Networks") or {}).get(name) or {}
                aliases = [a for a in endpoint.get("Aliases") or [] if a != c.id[:12]]
                # An address the operator pinned; Docker's own picks are not kept.
                static = endpoint.get("IPAMConfig") or {}
                members.append(
                    {
                        "name": c.name,
                        "aliases": aliases,
                        "ipv4": static.get("IPv4Address") or None,
                        "ipv6": static.get("IPv6Address") or None,
                    }
                )
            record = {
                "name": name,
                "driver": attrs.get("Driver") or "bridge",
                "options": attrs.get("Options") or {},
                "ipam": attrs.get("IPAM") or {},
                "ipv6": bool(attrs.get("EnableIPv6")),
                "internal": bool(attrs.get("Internal")),
                "attachable": bool(attrs.get("Attachable")),
                "labels": attrs.get("Labels") or {},
                "members": members,
                "done": False,
            }
            self.state.put("networks", name, record)
        if record.get("done"):
            return
        try:
            net = self.client.networks.get(name)
            net.reload()
        except NotFound:
            net = None
        if net is not None and not owned((net.attrs or {}).get("Labels")):
            for cid in list((net.attrs or {}).get("Containers") or {}):
                net.disconnect(cid, force=True)
            net.remove()
            net = None
        if net is None:
            net = self._create_network(record)
        net.reload()
        connected = {v.get("Name") for v in ((net.attrs or {}).get("Containers") or {}).values()}
        # Pinned addresses first, so no member Docker addresses itself takes one.
        for member in sorted(record["members"], key=lambda m: not (m.get("ipv4") or m.get("ipv6"))):
            if member["name"] in connected:
                continue
            try:
                self.client.containers.get(member["name"])
            except NotFound:
                continue  # removed since; a volume plan recreates it on this network
            net.connect(
                member["name"],
                aliases=member["aliases"] or None,
                ipv4_address=member.get("ipv4"),
                ipv6_address=member.get("ipv6"),
            )
        record["done"] = True
        self.state.put("networks", name, record)
        logger.info(
            "Recreated the network %s with %s=%s; %d container(s) back on it.",
            name,
            OWNER_LABEL,
            OWNER,
            len(record["members"]),
        )

    def _create_network(self, record: dict[str, Any]) -> Any:
        from docker.types import IPAMConfig, IPAMPool

        ipam = record["ipam"] or {}
        pools = [
            IPAMPool(
                subnet=p.get("Subnet"),
                iprange=p.get("IPRange"),
                gateway=p.get("Gateway"),
                aux_addresses=p.get("AuxiliaryAddresses"),
            )
            for p in ipam.get("Config") or []
        ]
        return self.client.networks.create(
            record["name"],
            driver=record["driver"],
            options=record["options"] or None,
            ipam=IPAMConfig(driver=ipam.get("Driver") or "default", pool_configs=pools, options=ipam.get("Options"))
            if pools
            else None,
            enable_ipv6=record["ipv6"],
            internal=record["internal"],
            attachable=record["attachable"],
            labels={**record["labels"], OWNER_LABEL: OWNER},
        )

    # -- volumes of worker containers ---------------------------------------

    def migrate_volumes(self) -> None:
        for plan in self.state.all("plans"):
            if not plan.get("done"):
                self._run_plan_logged(plan)
        for plan in self._new_plans():
            self._run_plan_logged(plan)

    def _run_plan_logged(self, plan: dict[str, Any]) -> None:
        try:
            self.run_plan(plan)
        except Exception as exc:  # noqa: BLE001 - logged, the other plans go on
            self.fail(f"{', '.join(c['Name'].lstrip('/') for c in plan['containers'])}: {exc}")

    def _new_plans(self) -> list[dict[str, Any]]:
        """Groups of worker containers that share unlabelled volumes, one plan each."""
        from docker.errors import NotFound

        workers = self.client.containers.list(all=True, filters={"label": f"{OWNER_LABEL}={OWNER}"})
        # A stored plan that did not finish already holds these, stopped by it;
        # a new plan would record them as stopped and bring them back stopped.
        held = {c["Id"] for p in self.state.all("plans") if not p.get("done") for c in p["containers"]}
        users: dict[str, set[str]] = {}
        attrs: dict[str, dict[str, Any]] = {}
        for c in workers:
            if c.id in held:
                continue
            for mount in (c.attrs or {}).get("Mounts") or []:
                if mount.get("Type") != "volume" or not mount.get("Name"):
                    continue
                try:
                    vol = self.client.volumes.get(mount["Name"])
                except NotFound:
                    continue
                if owned((vol.attrs or {}).get("Labels")):
                    continue
                users.setdefault(mount["Name"], set()).add(c.id)
                attrs[c.id] = c.attrs
        # Join containers that share a volume: they stop and come back together.
        groups: list[tuple[set[str], set[str]]] = []
        for vol, cids in users.items():
            merged = (set(cids), {vol})
            for group in [g for g in groups if g[0] & cids]:
                groups.remove(group)
                merged[0].update(group[0])
                merged[1].update(group[1])
            groups.append(merged)
        plans = []
        for cids, vols in groups:
            outsiders = self._outside_users(vols, cids)
            if outsiders:
                self.warn(
                    f"{', '.join(sorted(vols))} is also used by {', '.join(outsiders)}, which the worker did not "
                    "deploy, so it was left alone. The worker cannot redeploy the services on it until it is "
                    "moved by hand."
                )
                continue
            unusual = self._unusual_volumes(vols)
            if unusual:
                self.warn(
                    f"{', '.join(unusual)} uses a volume driver or driver options, so it was left alone: copying "
                    "it could write into the folder or device behind it. Move it by hand."
                )
                continue
            containers = sorted((attrs[cid] for cid in cids), key=lambda a: a["Name"])
            key = "+".join(a["Name"].lstrip("/") for a in containers)
            plan = {
                "key": key,
                "containers": containers,
                "running": {a["Id"]: bool((a.get("State") or {}).get("Running")) for a in containers},
                "volumes": sorted(vols),
                "done": False,
            }
            self.state.put("plans", key, plan)
            plans.append(plan)
        return plans

    def _outside_users(self, vols: set[str], cids: set[str]) -> list[str]:
        found = []
        for vol in vols:
            for c in self.client.containers.list(all=True, filters={"volume": vol}):
                if c.id not in cids:
                    found.append(c.name)
        return sorted(set(found))

    def _unusual_volumes(self, vols: set[str]) -> list[str]:
        found = []
        for vol in vols:
            attrs = self.client.volumes.get(vol).attrs or {}
            if (attrs.get("Driver") or "local") != "local" or attrs.get("Options"):
                found.append(vol)
        return found

    def _current(self, info: dict[str, Any]) -> Any | None:
        """The container the plan recorded, if it still exists (by id, not name)."""
        from docker.errors import NotFound

        try:
            return self.client.containers.get(info["Id"])
        except NotFound:
            return None

    def run_plan(self, plan: dict[str, Any]) -> None:
        names = [c["Name"].lstrip("/") for c in plan["containers"]]
        logger.info("Moving %s onto labelled volumes: %s", ", ".join(names), ", ".join(plan["volumes"]))
        for info in plan["containers"]:
            old = self._current(info)
            if old is not None:
                # No timeout: Docker uses the container's own (deploy_raw sets the catalog's).
                self.client.api.stop(old.id)
        try:
            for vol in plan["volumes"]:
                self.back_up(vol, names)
        except Exception:
            # Nothing is removed yet, so the earners go back to earning on their
            # own volumes. Their backups are now stale: the plan and its records
            # go, and the next run copies everything again.
            for info in plan["containers"]:
                old = self._current(info)
                if old is not None and plan["running"].get(info["Id"]):
                    self.client.api.start(old.id)
            for vol in plan["volumes"]:
                self.state.drop("volumes", vol)
            self.state.drop("plans", plan["key"])
            raise
        for info in plan["containers"]:
            old = self._current(info)
            if old is not None:
                old.remove(force=True)
        for vol in plan["volumes"]:
            self.restore(vol)
        for info in plan["containers"]:
            self.recreate(info, plan["running"].get(info["Id"], False))
        plan["done"] = True
        self.state.put("plans", plan["key"], plan)
        logger.info("%s back as before, on labelled volumes.", ", ".join(names))

    def back_up(self, vol: str, used_by: list[str]) -> None:
        from docker.errors import NotFound

        record = self.state.get("volumes", vol)
        if record and record.get("backed_up"):
            return
        attrs = self.client.volumes.get(vol).attrs or {}
        if owned(attrs.get("Labels")):
            raise MigrationError(f"{vol} already carries the label but no backup of it is recorded; not touching it")
        backup = backup_name(vol)
        try:
            self.client.volumes.get(backup)
        except NotFound:
            self.client.volumes.create(backup, driver="local", labels={BACKUP_LABEL: vol})
        logger.info("Copying %s into its backup %s", vol, backup)
        result = self.copy(vol, backup)
        record = {
            "volume": vol,
            "backup": backup,
            "used_by": used_by,
            "labels": attrs.get("Labels") or {},
            "digest": result,
            "backed_up": True,
            "restored": False,
        }
        self.state.put("volumes", vol, record)
        logger.info(
            "Backup %s holds the data of %s, used by %s (%d files, %d bytes, sha256 %s). It is never deleted "
            "by CashPilot.",
            backup,
            vol,
            ", ".join(used_by),
            result["files"],
            result["bytes"],
            result["digest"],
        )

    def restore(self, vol: str) -> None:
        from docker.errors import NotFound

        record = self.state.get("volumes", vol)
        if not record or not record.get("backed_up"):
            raise MigrationError(f"{vol} has no verified backup; not removing it")
        if record.get("restored"):
            return
        try:
            current = self.client.volumes.get(vol)
        except NotFound:
            current = None
        if current is not None and not owned((current.attrs or {}).get("Labels")):
            current.remove()
            current = None
        if current is None:
            self.client.volumes.create(vol, driver="local", labels={**record["labels"], OWNER_LABEL: OWNER})
        result = self.copy(record["backup"], vol)
        if result["digest"] != record["digest"]["digest"]:
            raise MigrationError(
                f"the backup {record['backup']} no longer matches what was copied from {vol}; "
                f"{vol} was not used. Both are kept."
            )
        record["restored"] = True
        self.state.put("volumes", vol, record)
        logger.info("%s carries the label now and holds the same data (sha256 %s).", vol, result["digest"])

    def recreate(self, info: dict[str, Any], running: bool) -> None:
        """Create the container again from its recorded inspect, under its name."""
        from docker.errors import NotFound

        name = info["Name"].lstrip("/")
        try:
            existing = self.client.containers.get(name)
        except NotFound:
            existing = None
        if existing is not None and existing.id == info["Id"]:
            raise MigrationError(f"{name} still exists as it was; it should have been removed")
        if existing is None:
            body = self.create_body(info)
            api = self.client.api
            created = api._result(
                api._post_json(api._url("/containers/create"), data=body, params={"name": name}), True
            )
            existing = self.client.containers.get(created["Id"])
            logger.info("Recreated %s", name)
        if running and existing.status != "running":
            existing.start()

    def create_body(self, info: dict[str, Any]) -> dict[str, Any]:
        config = dict(info.get("Config") or {})
        host = dict(info.get("HostConfig") or {})
        mode = str(host.get("NetworkMode") or "")
        # The same image, even if its tag moved since: by id when the tag points elsewhere now.
        image_id = info.get("Image") or ""
        try:
            if self.client.images.get(config.get("Image") or image_id).id != image_id:
                config["Image"] = image_id
        except Exception:  # noqa: BLE001 - the tag is gone: the id is what there is
            config["Image"] = image_id
        config.pop("MacAddress", None)
        if mode.startswith("container:"):
            # Docker refuses a hostname in another container's namespace.
            config.pop("Hostname", None)
            config.pop("Domainname", None)
        config["Labels"] = {**(config.get("Labels") or {}), OWNER_LABEL: OWNER}
        # An image VOLUME the container got an anonymous volume for: name it, or
        # the new container would get an empty one.
        binds = list(host.get("Binds") or [])
        named = {str(b).split(":", 1)[0] for b in binds} | {
            str(m.get("Source")) for m in host.get("Mounts") or [] if isinstance(m, dict)
        }
        for mount in info.get("Mounts") or []:
            if mount.get("Type") == "volume" and mount.get("Name") and mount["Name"] not in named:
                binds.append(f"{mount['Name']}:{mount['Destination']}{'' if mount.get('RW', True) else ':ro'}")
        host["Binds"] = binds or None
        endpoints: dict[str, Any] = {}
        if mode not in ("host", "none") and not mode.startswith("container:"):
            for net, ep in ((info.get("NetworkSettings") or {}).get("Networks") or {}).items():
                ep = ep or {}
                keep = {k: ep[k] for k in ("IPAMConfig", "Links", "DriverOpts", "MacAddress") if ep.get(k)}
                aliases = [a for a in ep.get("Aliases") or [] if a != info["Id"][:12]]
                if aliases:
                    keep["Aliases"] = aliases
                endpoints[net] = keep
        return {**config, "HostConfig": host, "NetworkingConfig": {"EndpointsConfig": endpoints}}


def _self_container(client: Any) -> Any:
    return client.containers.get(socket.gethostname())


def _pairs(raw: str) -> list[tuple[str, str]]:
    pairs = []
    for item in raw.split(","):
        old, sep, new = item.strip().partition("=")
        if sep and old and new:
            pairs.append((old, new))
    return pairs


def main() -> int:
    import docker

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout)
    # Stops wait for each container's own timeout (Storj asks 300 s).
    client = docker.DockerClient(base_url="unix:///var/run/docker.sock", version="auto", timeout=900)
    me = _self_container(client)
    project = (me.labels or {}).get("com.docker.compose.project", "")
    # The records hold each migrated container's settings, earner credentials
    # among them, in a folder on the host: root only, like a volume's contents.
    os.umask(0o077)
    root = Path("/state")
    root.chmod(0o700)
    state = State(root)
    migrator = Migrator(client, state, image=me.image.id, project=project)
    return migrator.run(_pairs(os.environ.get("CASHPILOT_MIGRATE_COMPOSE_VOLUMES", "")))


if __name__ == "__main__":
    sys.exit(main())
