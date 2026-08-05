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
