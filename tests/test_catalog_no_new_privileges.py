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
    _catalog_no_new_privileges_optout,
    _image_repository,
    _validate_deploy_spec,
)

MYST_IMAGE = "mysteriumnetwork/myst"


class TestCatalogDeclaration:
    def test_mysterium_opts_out(self):
        assert catalog.get_service("mysterium")["docker"]["no_new_privileges"] is False

    def test_it_is_the_only_service_that_does(self):
        """Every opt-out is a deliberate weakening; a second one should be noticed."""
        opted_out = [s["slug"] for s in catalog.get_services() if _catalog_no_new_privileges_optout(s["slug"])]
        assert opted_out == ["mysterium"]

    def test_the_optout_is_bound_to_the_catalog_image(self):
        assert _catalog_no_new_privileges_optout("mysterium") == MYST_IMAGE

    def test_no_service_opts_out_by_omission(self):
        """Absent means hardened. A typo'd key must not silently disable it."""
        for svc in catalog.get_services():
            docker = svc.get("docker") or {}
            if "no_new_privileges" not in docker:
                assert _catalog_no_new_privileges_optout(svc["slug"]) is None


class TestValidationScoping:
    def _spec(self, **kw):
        kw.setdefault("image", "x")
        return DeploySpec(**kw)

    def test_the_declaring_service_may_disable_it_for_its_own_image(self):
        _validate_deploy_spec(self._spec(image=MYST_IMAGE, no_new_privileges=False), "mysterium")

    def test_a_tag_or_digest_on_the_catalog_image_is_still_the_same_image(self):
        for ref in (f"{MYST_IMAGE}:latest", f"{MYST_IMAGE}@sha256:{'a' * 64}"):
            _validate_deploy_spec(self._spec(image=ref, no_new_privileges=False), "mysterium")

    def test_the_declared_slug_cannot_smuggle_a_different_image(self):
        """CodeRabbit #360: slug is caller-supplied, so on its own it authorises nothing."""
        with pytest.raises(HTTPException) as exc:
            _validate_deploy_spec(self._spec(image="attacker/evil", no_new_privileges=False), "mysterium")
        assert exc.value.status_code == 403

    def test_a_lookalike_repository_is_not_the_catalog_image(self):
        with pytest.raises(HTTPException) as exc:
            _validate_deploy_spec(self._spec(image="evil/mysteriumnetwork/myst", no_new_privileges=False), "mysterium")
        assert exc.value.status_code == 403

    def test_another_service_may_not(self):
        """The bug a global flag would create: one YAML unhardening all of them."""
        with pytest.raises(HTTPException) as exc:
            _validate_deploy_spec(self._spec(image=MYST_IMAGE, no_new_privileges=False), "honeygain")
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


class TestImageRepositoryParsing:
    def test_a_tag_is_stripped(self):
        assert _image_repository("owner/img:1.2") == "owner/img"

    def test_a_digest_is_stripped(self):
        assert _image_repository("owner/img@sha256:" + "b" * 64) == "owner/img"

    def test_a_registry_port_is_not_mistaken_for_a_tag(self):
        assert _image_repository("registry:5000/owner/img") == "registry:5000/owner/img"
