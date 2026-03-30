"""Validate collector registration and interface compliance."""

import inspect

from app.collectors import COLLECTOR_MAP
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
