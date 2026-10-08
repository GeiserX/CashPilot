"""Containers on the isolated bridge get resolvers the bridge's rules allow.

Docker's embedded resolver forwards a container's lookups to the daemon's DNS
servers from inside the container's network. On one fleet host the daemon listed
Tailscale's 100.100.100.100 first, and the isolation rules reject 100.64.0.0/10
from cp-isolated, so every lookup from an isolated earner waited about 4 s for
the fall-through to 1.1.1.1: thousands of stalls a day and a dockerd log line
for each. The worker now gives the containers it puts on that bridge their own
resolvers, CASHPILOT_CONTAINER_DNS (default 1.1.1.1 and 9.9.9.9). Containers
elsewhere, and the host, keep the daemon's list.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app import orchestrator


def _client(old=None):
    client = MagicMock()
    net = MagicMock()
    net.attrs = {"Driver": "bridge"}
    client.networks.get.return_value = net
    if old is None:
        client.containers.get.side_effect = orchestrator.NotFound("nope")
    else:
        client.containers.get.return_value = old
    created = MagicMock()
    created.id = created.short_id = "new"
    client.containers.run.return_value = created
    return client


def _deploy(client, network_setting, network_mode=None, dns_setting="1.1.1.1,9.9.9.9"):
    with (
        patch.object(orchestrator, "_CONTAINER_NETWORK", network_setting),
        patch.object(orchestrator, "_CONTAINER_DNS", dns_setting),
        patch.object(orchestrator, "_get_client", return_value=client),
    ):
        orchestrator.deploy_raw(slug="honeygain", image="honeygain/honeygain", network_mode=network_mode)
    return client.containers.run.call_args.kwargs


class TestWhoGetsTheResolvers:
    def test_a_container_on_the_isolated_bridge_gets_them(self):
        kwargs = _deploy(_client(), "cashpilot-isolated")
        assert kwargs["network"] == "cashpilot-isolated"
        assert kwargs["dns"] == ["1.1.1.1", "9.9.9.9"]

    def test_the_operator_can_name_others(self):
        kwargs = _deploy(_client(), "cashpilot-isolated", dns_setting=" 9.9.9.9 , 2620:fe::fe ")
        assert kwargs["dns"] == ["9.9.9.9", "2620:fe::fe"]

    def test_empty_keeps_the_daemons_list(self):
        kwargs = _deploy(_client(), "cashpilot-isolated", dns_setting="")
        assert kwargs["dns"] is None

    def test_without_an_isolated_bridge_nothing_is_set(self):
        kwargs = _deploy(_client(), "")
        assert kwargs["dns"] is None

    @pytest.mark.parametrize("mode", ["host", "none"])
    def test_host_and_none_networking_keep_the_daemons_list(self, mode):
        kwargs = _deploy(_client(), "cashpilot-isolated", network_mode=mode)
        assert kwargs["network"] is None
        assert kwargs["dns"] is None


class TestABadSettingIsRefusedBeforeAnythingIsTouched:
    def test_a_name_instead_of_an_address(self):
        old = MagicMock()
        client = _client(old=old)
        with pytest.raises(orchestrator.ContainerNetworkError, match="CASHPILOT_CONTAINER_DNS"):
            _deploy(client, "cashpilot-isolated", dns_setting="1.1.1.1,dns.quad9.net")
        old.stop.assert_not_called()
        old.remove.assert_not_called()
        client.containers.run.assert_not_called()

    def test_ignored_when_no_container_joins_the_bridge(self):
        """A bad value cannot break a worker that does not isolate anything."""
        kwargs = _deploy(_client(), "", dns_setting="not-an-address")
        assert kwargs["dns"] is None
