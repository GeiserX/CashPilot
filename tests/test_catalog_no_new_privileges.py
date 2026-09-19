"""Catalog opt-out from no-new-privileges.

Containers run with `no-new-privileges:true`, which blocks setuid escalation.
Mysterium cannot live with it: the node brings up its wireguard interface by
shelling out to `sudo ip address replace dev myst0 10.182.0.1/24`, and
no_new_privs permanently prevents sudo from elevating. Every session then dies
at setup while the node still registers, publishes proposals and reports itself
healthy — indistinguishable from the missing-TUN failure, and invisible to
`docker exec`, which starts a fresh process that does not inherit the bit.

So the opt-out is per slug and declared by the service's own YAML. Most of what
follows tests that nothing else can claim it.
"""

from __future__ import annotations

import os

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest  # noqa: E402
from fastapi import HTTPException  # noqa: E402

from app import catalog  # noqa: E402
from app.worker_api import (  # noqa: E402
    DeploySpec,
    _catalog_no_new_privileges_optout_slugs,
    _validate_deploy_spec,
)


class TestCatalogDeclaration:
    def test_mysterium_opts_out(self):
        assert catalog.get_service("mysterium")["docker"]["no_new_privileges"] is False

    def test_it_is_the_only_service_that_does(self):
        """Every opt-out is a deliberate weakening; a second one should be noticed."""
        assert _catalog_no_new_privileges_optout_slugs() == {"mysterium"}

    def test_no_service_opts_out_by_omission(self):
        """Absent means hardened. A typo'd key must not silently disable it."""
        for svc in catalog.get_services():
            docker = svc.get("docker") or {}
            if "no_new_privileges" not in docker:
                assert svc["slug"] not in _catalog_no_new_privileges_optout_slugs()


class TestValidationScoping:
    def _spec(self, **kw):
        return DeploySpec(image="x", **kw)

    def test_the_declaring_service_may_disable_it(self):
        _validate_deploy_spec(self._spec(no_new_privileges=False), "mysterium")

    def test_another_service_may_not(self):
        """The bug a global flag would create: one YAML unhardening all of them."""
        with pytest.raises(HTTPException) as exc:
            _validate_deploy_spec(self._spec(no_new_privileges=False), "honeygain")
        assert exc.value.status_code == 403

    def test_an_unknown_slug_is_denied_not_defaulted(self):
        with pytest.raises(HTTPException) as exc:
            _validate_deploy_spec(self._spec(no_new_privileges=False), "no-such-service")
        assert exc.value.status_code == 403

    def test_the_hardened_default_is_accepted_everywhere(self):
        for slug in ("mysterium", "honeygain", "no-such-service"):
            _validate_deploy_spec(self._spec(), slug)


class TestSpecDefault:
    def test_a_spec_that_says_nothing_is_hardened(self):
        assert DeploySpec(image="x").no_new_privileges is True
