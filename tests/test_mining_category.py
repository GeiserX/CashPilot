"""The Mining category, the `collector.accrual` key and every list that names categories."""

from __future__ import annotations

import asyncio
import importlib.util
import os
import sys
from pathlib import Path
from unittest.mock import AsyncMock, patch

os.environ.setdefault("CASHPILOT_API_KEY", "test-fleet-key")

import pytest

from app import catalog, payout_registry

ROOT = Path(__file__).resolve().parents[1]
LIVE = "bc1q4efd2vns8qwawg3nt4xxzs9053shh0q3x0tuu9"


def _script(name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _entry(**extra) -> dict:
    data = {
        "name": "Pool",
        "slug": "pool",
        "category": "mining",
        "status": "beta",
        "description": "A pool",
        "docker": {"image": ""},
    }
    data.update(extra)
    return data


class TestTheCategory:
    def test_mining_is_a_valid_category(self):
        assert catalog._validate(_entry(), Path("pool.yml")) == []

    def test_an_unknown_category_is_still_refused(self):
        errors = catalog._validate(_entry(category="minning"), Path("pool.yml"))
        assert any("invalid category" in e for e in errors)

    def test_ocean_is_listed_under_mining(self):
        ocean = catalog.get_service("ocean")
        assert ocean and ocean["category"] == "mining"
        assert ocean["collector"]["accrual"] == "pool"
        assert ocean["payout"] == {
            **ocean["payout"],
            "model": "external",
            "chain": "bitcoin",
            "address_source": "collector",
        }


class TestTheAccrualKey:
    def test_pool_loads(self):
        assert catalog._validate(_entry(collector={"accrual": "pool"}), Path("pool.yml")) == []

    @pytest.mark.parametrize("value", ["wages", "", ["pool"], True])
    def test_any_other_value_is_refused(self, value):
        errors = catalog._validate(_entry(collector={"accrual": value}), Path("pool.yml"))
        assert any("collector.accrual" in e for e in errors), errors

    def test_absent_is_fine(self):
        assert catalog._validate(_entry(collector={"type": "api"}), Path("pool.yml")) == []


class TestTheReadmeLists:
    def test_ocean_is_in_the_mining_list_and_no_other(self):
        gen = _script("generate_readme_tables")
        lists = {
            kind: {s["slug"] for s in gen._selected(kind)} for kind in (gen.DOCKER, gen.EXTENSION, gen.GPU, gen.MINING)
        }
        assert "ocean" in lists[gen.MINING]
        assert all("ocean" not in lists[k] for k in (gen.DOCKER, gen.EXTENSION, gen.GPU))
        counts = gen.counts()
        assert counts["mining"] == len(lists[gen.MINING])
        assert counts["tracked"] == counts["extension"] + counts["gpu"] + counts["mining_pools"]

    def test_xmrig_counts_as_docker_while_pools_count_as_tracked(self):
        gen = _script("generate_readme_tables")
        miners = gen._selected(gen.MINING)
        docker_miners = {s["slug"] for s in miners if gen._is_dockerable(s)}
        assert "xmrig" in docker_miners
        assert not docker_miners & {"ocean", "supportxmr"}
        counts = gen.counts()
        assert counts["docker"] == len(gen._selected(gen.DOCKER)) + len(docker_miners)
        assert counts["mining_pools"] == len(miners) - len(docker_miners)

    def test_a_readme_without_the_mining_markers_fails(self):
        gen = _script("generate_readme_tables")
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        stripped = readme.replace("<!-- BEGIN GENERATED: mining-services -->", "")
        with pytest.raises(SystemExit, match="mining-services"):
            gen.render(stripped)


class TestTheDocsNav:
    def test_the_ocean_guide_is_in_the_nav_and_the_index(self):
        nav = _script("sync_docs_nav")
        services = nav.load_services()
        assert "guides/ocean.md" in nav.render_nav(services)
        index = nav.render_index(services)
        assert "## Mining" in index
        assert "| [OCEAN](ocean.md) | — | Tracked pool |" in index

    def test_a_category_with_no_title_stops_the_script(self, monkeypatch):
        nav = _script("sync_docs_nav")
        monkeypatch.setattr(nav, "CATEGORY_TITLES", [t for t in nav.CATEGORY_TITLES if t[0] != "mining"])
        monkeypatch.setattr(sys, "argv", ["sync_docs_nav.py", "--check"])
        with pytest.raises(SystemExit, match="mining"):
            nav.main()


class TestThePayoutAddressFromSettings:
    def _ocean_row(self, config):
        get_config = AsyncMock(side_effect=config) if isinstance(config, Exception) else AsyncMock(return_value=config)
        with (
            patch.object(payout_registry.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(payout_registry.database, "list_workers", AsyncMock(return_value=[])),
            patch.object(payout_registry.database, "get_deployment_spec", AsyncMock(return_value=None)),
            patch.object(payout_registry.database, "get_state_backups", AsyncMock(return_value={})),
            patch.object(payout_registry.database, "get_config", get_config),
        ):
            result = asyncio.run(payout_registry.registry())
        return next(r for r in result["entries"] if r["slug"] == "ocean")

    def test_a_saved_address_is_shown(self):
        row = self._ocean_row({"ocean_address": LIVE})
        assert row["address"] == LIVE
        assert row["addresses"] == [{"address": LIVE, "servers": []}]
        assert row["address_missing"] is False and row["address_unchecked"] is None

    def test_no_saved_address_is_not_set(self):
        row = self._ocean_row({})
        assert row["address"] is None and row["address_missing"] is True

    def test_unreadable_settings_are_not_checked_never_not_set(self):
        row = self._ocean_row(RuntimeError("db locked"))
        assert row["address"] is None
        assert row["address_missing"] is False
        assert row["address_unchecked"] == "settings"

    def test_unreadable_settings_leave_other_rows_alone(self):
        with (
            patch.object(payout_registry.database, "get_deployments", AsyncMock(return_value=[])),
            patch.object(payout_registry.database, "list_workers", AsyncMock(return_value=[])),
            patch.object(payout_registry.database, "get_deployment_spec", AsyncMock(return_value=None)),
            patch.object(payout_registry.database, "get_state_backups", AsyncMock(return_value={})),
            patch.object(payout_registry.database, "get_config", AsyncMock(side_effect=RuntimeError("db locked"))),
        ):
            result = asyncio.run(payout_registry.registry())
        storj = next(r for r in result["entries"] if r["slug"] == "storj")
        # An env-sourced address never comes from Settings, so its state is unchanged.
        assert storj["address_unchecked"] is None and storj["address_missing"] is True

    def test_the_entry_function_takes_the_address(self):
        service = catalog.get_service("ocean")
        row = payout_registry.entry(service, None, deployed=False, configured_address=f" {LIVE} ")
        assert row["address"] == LIVE and row["chain"] == "bitcoin"
        assert payout_registry.entry(service, None, deployed=False)["address_missing"] is True


class TestThePoolCoinIsPriced:
    def test_btc_has_its_coingecko_id(self):
        from app import exchange_rates

        assert exchange_rates.CRYPTO_IDS["BTC"] == "bitcoin"
        assert catalog.get_service("ocean")["payment"]["currency"] in exchange_rates.CRYPTO_IDS


class TestAPoolPayout:
    def test_a_drop_past_the_threshold_is_a_probable_payout_in_full(self):
        from app import payouts

        ocean = catalog.get_service("ocean")
        out = payouts.detect(0.01599128 + 0.0002, 0.0002, ocean, "BTC")
        assert out is not None and out["confirmed"] is False
        assert out["amount"] == 0.01599128
        assert "0.01048576" in out["reason"]

    def test_a_drop_below_the_threshold_is_not_a_payout(self):
        from app import payouts

        assert payouts.detect(0.006, 0.001, catalog.get_service("ocean"), "BTC") is None
