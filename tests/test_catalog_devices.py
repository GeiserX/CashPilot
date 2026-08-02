"""Catalog device support (CashPilot-6rv).

A service could declare `cap_add` but not a device, and Mysterium needs
`/dev/net/tun` to carry wireguard/dvpn traffic. Deployed without it the node
starts, registers, advertises itself to the network — and earns nothing. It
looks healthy from every angle CashPilot could see, which is why it took a
provider email to surface.

A device is a direct line to the kernel, so most of what follows tests the
refusals rather than the happy path.
"""

from __future__ import annotations

import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402

from app import catalog  # noqa: E402
from app.worker_api import (  # noqa: E402
    _ALLOWED_DEVICES,
    DeploySpec,
    _catalog_allowed_devices,
    _validate_deploy_spec,
)


class TestCatalogDeclaration:
    def test_mysterium_declares_the_tun_device(self):
        assert catalog.get_service("mysterium")["docker"]["devices"] == ["/dev/net/tun"]

    def test_every_declared_device_is_on_the_allow_list(self):
        """The catalog must not be able to widen the ceiling on its own."""
        for svc in catalog.get_services():
            for dev in (svc.get("docker") or {}).get("devices") or []:
                assert dev.split(":")[0] in _ALLOWED_DEVICES, (
                    f"{svc['slug']} declares {dev!r}, which is not on the worker allow-list. "
                    "Adding one is a deliberate maintainer decision in app/worker_api.py."
                )


class TestPerSlugScoping:
    def test_a_service_gets_only_what_its_own_yaml_declares(self):
        assert _catalog_allowed_devices("mysterium") == {"/dev/net/tun"}

    def test_another_service_does_not_inherit_it(self):
        """The bug a union would create: one YAML widening it for all 50."""
        assert _catalog_allowed_devices("honeygain") == set()

    def test_an_unknown_slug_is_denied_not_defaulted(self):
        assert _catalog_allowed_devices("no-such-service") == set()


class TestValidationRefuses:
    def _spec(self, **kw):
        return DeploySpec(image="x", **kw)

    def test_the_declared_device_is_accepted(self):
        _validate_deploy_spec(self._spec(devices=["/dev/net/tun"]), slug="mysterium")

    def test_a_device_the_service_did_not_declare_is_refused(self):
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _validate_deploy_spec(self._spec(devices=["/dev/net/tun"]), slug="honeygain")
        assert exc.value.status_code == 403
        assert "Blocked devices" in exc.value.detail

    @pytest.mark.parametrize(
        "device",
        ["/dev/mem", "/dev/kmsg", "/dev/sda", "/dev/mapper/control", "/dev/kvm", "/dev/../dev/mem"],
    )
    def test_dangerous_devices_are_refused_even_for_a_service_that_has_one(self, device):
        """The allow-list is a ceiling, not a starting point."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _validate_deploy_spec(self._spec(devices=[device]), slug="mysterium")
        assert exc.value.status_code == 403

    def test_a_host_path_remap_cannot_smuggle_a_device_in(self):
        """`/dev/mem:/dev/net/tun` must be judged on the HOST path."""
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc:
            _validate_deploy_spec(self._spec(devices=["/dev/mem:/dev/net/tun"]), slug="mysterium")
        assert exc.value.status_code == 403
        assert "/dev/mem" in exc.value.detail

    def test_no_devices_requested_is_always_fine(self):
        _validate_deploy_spec(self._spec(), slug="honeygain")


class TestItReachesDocker:
    def test_the_deploy_spec_carries_the_catalog_devices(self):
        """A declaration nothing forwards would protect nobody."""
        import inspect

        from app import orchestrator

        assert "devices" in inspect.signature(orchestrator.deploy_raw).parameters
        source = inspect.getsource(orchestrator.deploy_raw)
        assert "devices=devices" in source, "deploy_raw must pass devices to containers.run"
