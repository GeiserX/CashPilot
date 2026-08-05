"""CashPilot-cle: the fleet reported CPU and memory — the two least useful numbers.

What actually decides whether a passive-income service can earn on a machine is
**disk** and **GPU**, and the worker reported neither. Measured on the live
fleet before this: ``system_info`` carried ``os``, ``arch``, ``hostname``,
``docker_available``, ``version``, ``egress_ip``, ``egress_network_type`` — and
nothing else.

* **Disk.** Storj is paid for data it *stores*, so free space is earning
  capacity. A node that quietly fills up stops growing and nothing said so.
* **GPU.** Salad, Nosana, io.net and Vast.ai only earn with a real GPU. Today a
  GPU service that runs but earns nothing — because the device was never passed
  into the container — looks exactly like one that is working. That is the
  Mysterium ``/dev/net/tun`` failure again: healthy-looking and worth nothing.

**The three-valued part is the whole design.** Inside a container with no device
passed through, the absence of ``nvidia-smi`` proves nothing about the host. And
the probes are Linux-specific, so on macOS they prove nothing at all — the first
version of this reported "no GPU" on a Mac, which was caught by running it.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest


class TestDiskIsReportedOrHonestlyUnknown:
    def test_it_reports_free_and_total_on_a_readable_path(self, tmp_path):
        from app import worker_api

        with patch.object(worker_api, "_WORKER_ID_FILE", tmp_path / ".worker_id"):
            usage = worker_api._disk_usage()
        assert usage is not None
        assert usage["total_bytes"] > 0
        assert 0 <= usage["free_bytes"] <= usage["total_bytes"]
        assert usage["path"] == str(tmp_path)

    def test_an_unreadable_path_reports_unknown_not_zero(self):
        """0 free would read as a full disk; 0 total as no disk. Both are lies."""
        from app import worker_api

        with patch.object(worker_api.shutil, "disk_usage", side_effect=OSError("gone")):
            assert worker_api._disk_usage() is None


class TestGpuNeverClaimsMoreThanItKnows:
    def _gpu(self, *, system, in_container=False, nvidia=None, nvidia_out="", render_nodes=False):
        from app import worker_api

        def fake_exists(self):
            return in_container if str(self) == "/.dockerenv" else False

        def fake_is_dir(self):
            return render_nodes and str(self) == "/dev/dri"

        def fake_glob(self, pattern):
            return [Path("/dev/dri/renderD128")] if render_nodes else []

        class _Run:
            returncode = 0
            stdout = nvidia_out

        with (
            patch.object(worker_api.platform, "system", return_value=system),
            patch.object(worker_api.shutil, "which", return_value=nvidia),
            patch.object(worker_api.subprocess, "run", return_value=_Run()),
            patch.object(Path, "exists", fake_exists),
            patch.object(Path, "is_dir", fake_is_dir),
            patch.object(Path, "glob", fake_glob),
        ):
            return worker_api._gpu_info()

    def test_a_named_device_is_reported(self):
        gpu = self._gpu(system="Linux", nvidia="/usr/bin/nvidia-smi", nvidia_out="NVIDIA GeForce RTX 4090\n")
        assert gpu["available"] is True
        assert gpu["devices"] == ["NVIDIA GeForce RTX 4090"]
        assert gpu["detected_by"] == "nvidia-smi"

    def test_a_render_node_counts_as_a_gpu(self):
        """Integrated or AMD: enough to say yes, not enough to name it."""
        gpu = self._gpu(system="Linux", render_nodes=True)
        assert gpu["available"] is True
        assert gpu["detected_by"] == "drm"

    def test_a_bare_linux_host_with_nothing_is_a_real_no(self):
        """The ONE case where False is honest."""
        gpu = self._gpu(system="Linux")
        assert gpu["available"] is False

    def test_inside_a_container_with_nothing_visible_is_UNKNOWN(self):
        """The case that matters: a GPU service earning nothing looks fine."""
        gpu = self._gpu(system="Linux", in_container=True)
        assert gpu["available"] is None, "claimed the host has no GPU when it may have an unused one"
        assert "not passed through" in gpu["reason"]

    @pytest.mark.parametrize("system", ["Darwin", "Windows"])
    def test_a_non_linux_host_is_UNKNOWN_not_no(self, system):
        """nvidia-smi and /dev/dri are Linux-specific; every Mac has a GPU.

        The first version of this returned False on macOS. Running it caught
        that — reading it would not have.
        """
        gpu = self._gpu(system=system)
        assert gpu["available"] is None
        assert system in gpu["reason"]

    def test_unknown_is_never_rendered_as_false_anywhere(self):
        """None and False are different answers and must stay distinguishable."""
        for kwargs in ({"system": "Darwin"}, {"system": "Linux", "in_container": True}):
            assert self._gpu(**kwargs)["available"] is not False


class TestTheHeartbeatCarriesThem:
    def test_system_info_includes_both(self):
        import ast
        import inspect

        from app import worker_api

        source = inspect.getsource(worker_api)
        start = source.index('"system_info": {')
        block = source[start : start + 1400]
        assert '"disk"' in block
        assert '"gpu"' in block
        # Off the event loop: disk_usage and a subprocess both block.
        assert "asyncio.to_thread(_disk_usage)" in block
        assert "asyncio.to_thread(_gpu_info)" in block
        ast.parse(source)


class TestTheShippedComposeDoesNotBreakGpuLessHosts:
    """Docker refuses to start when a listed device is missing.

    Verified on a real host: ``docker run --device /dev/does-not-exist`` fails,
    while ``--device /dev/dri`` on a machine that has one works. So a hard
    ``devices:`` entry in the shipped compose would break every user without a
    GPU — it is documented and commented out instead.
    """

    import pathlib

    ROOT = pathlib.Path(__file__).resolve().parents[1]

    @pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.fleet.yml"])
    def test_the_device_is_not_hard_required(self, name):
        import yaml

        doc = yaml.safe_load((self.ROOT / name).read_text(encoding="utf-8"))
        worker = doc["services"]["cashpilot-worker"]
        assert "devices" not in worker, (
            f"{name} hard-requires a device; Docker refuses to start when it is missing, "
            "so this breaks every host without a GPU"
        )

    @pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.fleet.yml"])
    def test_but_it_is_documented_in_place(self, name):
        """Commented out is only helpful if it says why and when to enable it."""
        text = (self.ROOT / name).read_text(encoding="utf-8")
        assert "/dev/dri:/dev/dri" in text, f"{name} gives no hint that GPU passthrough is possible"
        assert "does not exist" in text or "no GPU" in text

    def test_the_docs_explain_the_nvidia_path_too(self):
        """Whitespace-normalised: markdown hard-wraps, and "NVIDIA Container
        Toolkit" was split across two lines, so a contiguous substring check
        missed it. Third time this trap has bitten in this session."""
        assert "NVIDIA Container Toolkit" in self._docs()
        assert "GPU passthrough" in self._docs()

    def _docs(self):
        import re

        raw = (self.ROOT / "docs" / "configuration.md").read_text(encoding="utf-8")
        return re.sub(r"\s+", " ", raw)


class TestTheNvidiaPathDoesNotStopAtTheToolkit:
    """CodeRabbit caught a real gap: the toolkit is the prerequisite, not the
    allocation.

    Installing the NVIDIA Container Toolkit does **not** hand the GPU to a
    Compose service — the service has to request it. Saying only "install the
    toolkit" therefore left a reader with a card the worker still cannot see,
    which is exactly the silent-earns-nothing failure this whole feature exists
    to surface.

    Both request forms were validated against Compose v2.40.3 on a real host,
    and both were run on a machine with **no** NVIDIA card, where both exit 1
    (``could not select device driver``). That is why they are commented out
    alongside ``/dev/dri`` rather than enabled — the same reasoning, established
    by running it rather than assuming it.
    """

    import pathlib

    ROOT = pathlib.Path(__file__).resolve().parents[1]
    COMPOSE = ["docker-compose.yml", "docker-compose.fleet.yml"]

    def _docs(self):
        import re

        return re.sub(r"\s+", " ", (self.ROOT / "docs" / "configuration.md").read_text(encoding="utf-8"))

    def test_the_docs_say_the_toolkit_alone_is_not_enough(self):
        """The precise misconception, denied in words."""
        text = self._docs()
        assert "does not" in text.lower() or "not enough" in text.lower()
        assert "prerequisite" in text.lower(), "nothing tells the reader the toolkit is only step one"

    def test_the_docs_give_a_working_request(self):
        text = self._docs()
        assert "gpus: all" in text, "the shorthand form is missing"
        assert "driver: nvidia" in text, "the explicit reservation form is missing"
        assert "capabilities: [gpu]" in text

    def test_the_docs_warn_it_also_breaks_a_gpu_less_host(self):
        """Verified by running it; without this a reader enables it blindly."""
        assert "could not select device driver" in self._docs()

    @pytest.mark.parametrize("name", COMPOSE)
    def test_the_compose_files_carry_the_same_hint(self, name):
        text = (self.ROOT / name).read_text(encoding="utf-8")
        assert "gpus: all" in text, f"{name} documents /dev/dri but not the NVIDIA request"
        assert "driver: nvidia" in text

    @pytest.mark.parametrize("name", COMPOSE)
    def test_the_nvidia_request_is_not_actually_enabled(self, name):
        """It fails on a GPU-less host, so it must stay commented like /dev/dri.

        Parsed as YAML rather than grepped: a commented block is invisible to
        the parser, so if either key became live this fails.
        """
        import yaml

        worker = yaml.safe_load((self.ROOT / name).read_text(encoding="utf-8"))["services"]["cashpilot-worker"]
        assert "gpus" not in worker, f"{name} requests a GPU unconditionally; GPU-less hosts fail to start"
        reservations = (worker.get("deploy") or {}).get("resources", {}).get("reservations", {})
        assert "devices" not in reservations, f"{name} reserves a GPU device unconditionally"

    @pytest.mark.parametrize("name", COMPOSE)
    def test_it_tells_the_reader_not_to_set_both(self, name):
        """Two ways to ask for the same thing invites setting both."""
        assert "do not set both" in (self.ROOT / name).read_text(encoding="utf-8").lower()


class TestTheCommentedYamlIsActuallyValidYaml:
    """A commented example nobody can uncomment is worse than none.

    Uncommenting is the whole point of shipping it inert, so the block has to
    parse *and* land at the right indentation once the ``# `` prefixes come off.
    Nothing else in CI would ever catch a typo inside a comment.
    """

    import pathlib

    ROOT = pathlib.Path(__file__).resolve().parents[1]

    @pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.fleet.yml"])
    @pytest.mark.parametrize("marker", ["gpus: all", "devices:\n      #   - /dev/dri:/dev/dri"])
    def test_uncommenting_a_block_yields_parseable_yaml(self, name, marker):
        import textwrap

        import yaml

        text = (self.ROOT / name).read_text(encoding="utf-8")
        first = marker.splitlines()[0]
        line = next(ln for ln in text.splitlines() if first in ln and ln.lstrip().startswith("#"))
        block = []
        for ln in text.splitlines()[text.splitlines().index(line) :]:
            stripped = ln.strip()
            if not stripped.startswith("#") or stripped == "#":
                break
            block.append(ln.replace("# ", "", 1))
        uncommented = textwrap.dedent("\n".join(block))
        parsed = yaml.safe_load(uncommented)
        assert isinstance(parsed, dict) and parsed, f"{name}: {first!r} does not uncomment to valid YAML"

    @pytest.mark.parametrize("name", ["docker-compose.yml", "docker-compose.fleet.yml"])
    def test_the_reservation_block_uncomments_to_the_documented_shape(self, name):
        import textwrap

        import yaml

        text = (self.ROOT / name).read_text(encoding="utf-8")
        lines = text.splitlines()
        start = next(i for i, ln in enumerate(lines) if ln.strip().startswith("#") and "deploy:" in ln)
        block = []
        for ln in lines[start:]:
            stripped = ln.strip()
            if not stripped.startswith("#") or stripped == "#":
                break
            block.append(ln.replace("# ", "", 1))
        parsed = yaml.safe_load(textwrap.dedent("\n".join(block)))
        device = parsed["deploy"]["resources"]["reservations"]["devices"][0]
        assert device["driver"] == "nvidia"
        assert device["capabilities"] == ["gpu"]


class TestTheDeviceCeilingIsDocumentedWhereItIsEnforced:
    """CLAUDE.md said "the catalog cannot declare devices yet". It can, and does.

    The claim was true before the Mysterium TUN fix and was never updated, so the
    file agents read first told them a shipped capability did not exist —
    ``services/bandwidth/mysterium.yml`` declares ``/dev/net/tun`` and
    ``app/main.py`` passes it through to the worker. A stale instruction is worse
    than a missing one: it is followed.

    Checked while closing out the GPU work, where the same question came up for
    the compute services. Their answer is different — every one of them ships an
    empty ``docker.image``, so none is deployable and none can request anything.

    These assertions read the ceiling out of the CODE and require the docs to
    agree, rather than checking each for a string it can satisfy alone.
    """

    import pathlib

    ROOT = pathlib.Path(__file__).resolve().parents[1]

    def _ceiling(self):
        from app.worker_api import _ALLOWED_DEVICES

        return set(_ALLOWED_DEVICES)

    def test_the_security_doc_names_every_device_the_code_permits(self):
        text = (self.ROOT / "docs" / "security-defaults.md").read_text(encoding="utf-8")
        missing = {d for d in self._ceiling() if d not in text}
        assert not missing, f"the ceiling was widened to include {missing} and security-defaults.md never said so"

    def test_the_security_doc_does_not_promise_a_narrower_ceiling(self):
        """The inverse drift: a device removed from the code but left in prose."""
        import re

        text = (self.ROOT / "docs" / "security-defaults.md").read_text(encoding="utf-8")
        claimed = set(re.findall(r"`(/dev/[a-z0-9/_-]+)`", text))
        assert claimed <= self._ceiling(), f"the doc advertises {claimed - self._ceiling()}, which deploys would refuse"

    def test_claude_md_no_longer_denies_the_capability(self):
        text = (self.ROOT / "CLAUDE.md").read_text(encoding="utf-8")
        assert "catalog cannot declare devices" not in text, "the stale claim is back"

    def test_the_capability_it_now_describes_is_real(self):
        """Do not simply delete the false sentence — prove the true one."""
        import yaml

        docker = yaml.safe_load((self.ROOT / "services" / "bandwidth" / "mysterium.yml").read_text(encoding="utf-8"))[
            "docker"
        ]
        assert "/dev/net/tun" in (docker.get("devices") or []), "CLAUDE.md now claims a declaration that is absent"

    def test_the_deploy_path_actually_forwards_it(self):
        """Declared-but-ignored would make the corrected CLAUDE.md wrong too."""
        main = (self.ROOT / "app" / "main.py").read_text(encoding="utf-8")
        assert '"devices": docker_conf.get("devices") or None' in main

    def test_no_gpu_service_is_deployable_so_none_can_request_a_device(self):
        """The premise of a follow-up, checked rather than assumed.

        The worry was that the GPU services would hit the Mysterium bug —
        deployed without their device, healthy, earning nothing. They cannot:
        every compute service is extension/app-only with an empty image.
        """
        import pathlib

        import yaml

        for path in sorted(pathlib.Path(self.ROOT / "services" / "compute").glob("*.yml")):
            if path.name.startswith("_"):
                continue
            docker = yaml.safe_load(path.read_text(encoding="utf-8")).get("docker") or {}
            image = (docker.get("image") or "").strip()
            if image:
                assert docker.get("devices") is not None, (
                    f"{path.name} became deployable without declaring its device; "
                    "if it needs a GPU it will start, look healthy and earn nothing"
                )
