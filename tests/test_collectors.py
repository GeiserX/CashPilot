"""Validate collector registration and interface compliance."""

import inspect

from app.collectors import _COLLECTOR_ARGS, COLLECTOR_MAP, make_collectors
from app.collectors.base import BaseCollector, EarningsResult


def test_collector_map_not_empty():
    assert len(COLLECTOR_MAP) > 0


def test_all_collectors_are_base_subclasses():
    for slug, cls in COLLECTOR_MAP.items():
        assert issubclass(cls, BaseCollector), f"{slug}: {cls} is not a BaseCollector subclass"


def test_all_collectors_have_collect_method():
    for slug, cls in COLLECTOR_MAP.items():
        assert hasattr(cls, "collect"), f"{slug}: missing collect method"
        assert inspect.iscoroutinefunction(cls.collect), f"{slug}: collect must be async"


def test_all_collectors_have_platform():
    for slug, cls in COLLECTOR_MAP.items():
        assert hasattr(cls, "platform"), f"{slug}: missing platform attribute"
        assert cls.platform, f"{slug}: platform is empty"


def test_base_collector_interface():
    assert hasattr(BaseCollector, "platform")
    assert hasattr(BaseCollector, "collect")
    assert inspect.iscoroutinefunction(BaseCollector.collect)


def test_earnings_result_fields():
    result = EarningsResult(platform="test", balance=1.23)
    assert result.platform == "test"
    assert result.balance == 1.23
    assert result.currency == "USD"
    assert result.bytes_uploaded == 0
    assert result.error is None


def test_storj_api_url_is_optional():
    """Storj api_url must be marked optional so the built-in default works."""
    storj_args = _COLLECTOR_ARGS.get("storj", [])
    assert "?api_url" in storj_args, "storj api_url should be optional (prefixed with ?)"
    assert "api_url" not in storj_args, "storj api_url should not be mandatory"


def test_storj_collector_created_without_config():
    """make_collectors should create a StorjCollector with no api_url config."""
    deployments = [{"slug": "storj"}]
    collectors = make_collectors(deployments, config={})
    assert len(collectors) == 1
    assert collectors[0].platform == "storj"
    assert "localhost:14002" in collectors[0].api_url


def test_storj_collector_respects_custom_url():
    """make_collectors should pass custom api_url when provided."""
    deployments = [{"slug": "storj"}]
    collectors = make_collectors(deployments, config={"storj_api_url": "http://mynode:14002"})
    assert len(collectors) == 1
    assert collectors[0].api_url == "http://mynode:14002"
