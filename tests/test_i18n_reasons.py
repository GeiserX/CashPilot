"""Why a worker holds a node, or why a tunnel change is stuck, in the reader's language.

The worker writes these reasons with no page to take a language from. It sends
the English, as before, and beside it the message key and its arguments
(i18n.Reason, i18n.wire). The UI words them in its reader's language
(i18n.reword) and falls back to the English when the key is missing or unknown.
"""

from __future__ import annotations

import asyncio
import contextvars
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app import i18n, lan_fence, main, orchestrator
from tests.test_proxied_copy_alert import _Alerts, _copy, _entry, _past_grace, _stuck, _worker

ROOT = Path(__file__).resolve().parent.parent
SPANISH = {
    "reason.spec.image": "ejecuta {image}, no la imagen que fija el catálogo",
    "reason.tunnel.busy": "Otro cambio de este proxy está en marcha en este worker.",
    "reason.identity.mismatch": "su identidad es {current}, no {expected}",
}


@pytest.fixture
def spanish(tmp_path, monkeypatch):
    source = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))
    (tmp_path / "en.json").write_text(json.dumps(source), encoding="utf-8")
    stamped = {k: {"text": v, "source": i18n.source_hash(source[k])} for k, v in SPANISH.items()}
    (tmp_path / "es.json").write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "DIR", tmp_path)
    i18n.reload()
    yield
    i18n.reload()


@pytest.fixture(autouse=True)
def _clean_state(monkeypatch):
    monkeypatch.setattr(main, "_proxied_first_seen", {})
    monkeypatch.setattr(main, "_proxied_bell", {})
    monkeypatch.setattr(main, "_collector_alerts", [])
    monkeypatch.setattr(main, "_account_disabled", {})


def _in(locale, fn, *args):
    def run():
        i18n.use(locale)
        return fn(*args)

    return contextvars.Context().run(run)


class TestAReason:
    def test_it_is_its_english_and_carries_its_key_and_arguments(self):
        reason = i18n.Reason("reason.spec.image", image="demo/demo:2")
        assert reason == "it runs demo/demo:2, not the image the catalog pins"
        assert i18n.wire(reason) == {"code": "reason.spec.image", "params": {"image": "demo/demo:2"}}
        assert i18n.wire("plain text") is None

    def test_only_a_reason_key_makes_one(self):
        with pytest.raises(ValueError):
            i18n.Reason("app.close")

    def test_a_count_reads_as_before(self):
        one = i18n.Reason("reason.tunnel.half_moved", names="a", count=1)
        two = i18n.Reason("reason.tunnel.half_moved", names="a, b", count=2)
        assert one == "a is still half moved between tunnels, and the worker has not settled that yet."
        assert two == "a, b are still half moved between tunnels, and the worker has not settled that yet."
        assert i18n.Reason("reason.spec.udp_missing", port=40001, more=0, start=40001, end=40001) == (
            "it does not publish UDP 40001 of its range 40001:40001"
        )
        assert i18n.Reason("reason.spec.udp_missing", port=40001, more=4, start=40001, end=40005) == (
            "it does not publish UDP 40001 and 4 more of its range 40001:40005"
        )


class TestTheUIWordsIt:
    def test_in_the_readers_language(self, spanish):
        wired = {"code": "reason.spec.image", "params": {"image": "demo/demo:2"}}
        assert _in("es", i18n.reword, "English", wired) == "ejecuta demo/demo:2, no la imagen que fija el catálogo"
        assert _in("en", i18n.reword, "English", wired) == "it runs demo/demo:2, not the image the catalog pins"

    @pytest.mark.parametrize(
        "wired",
        [
            None,  # an older worker, or Desktop
            {"code": "app.close", "params": {}},  # not a reason: a worker names reasons only
            {"code": "reason.not.in.this.release", "params": {}},
            {"code": "reason.spec.image", "params": {}},  # an argument missing
            {"code": "reason.spec.image", "params": {"image": ["a"]}},
            {"code": "reason.spec.image", "params": {"image": True}},
            {"code": "reason.spec.image", "params": "image"},
        ],
    )
    def test_anything_else_keeps_the_workers_english(self, spanish, wired):
        assert _in("es", i18n.reword, "the worker's English", wired) == "the worker's English"


class TestTheHeartbeatCarriesIt:
    def test_a_held_node_sends_the_key_beside_its_english(self, monkeypatch):
        node = MagicMock()
        node.name = "cashpilot-mysterium"
        monkeypatch.setitem(lan_fence._state, "guard", {node.name: lan_fence.FAILED_DEPLOY})
        assert orchestrator._held_entry(node) == {"held": lan_fence.FAILED_DEPLOY}
        assert orchestrator._held_reason_entry(node) == {
            "held_reason": {"code": "reason.held.failed_deploy", "params": {}}
        }

    def test_a_held_node_without_a_key_sends_only_its_english(self, monkeypatch):
        node = MagicMock()
        node.name = "cashpilot-mysterium"
        monkeypatch.setitem(lan_fence._state, "guard", {node.name: "an older reason"})
        assert orchestrator._held_reason_entry(node) == {}

    def test_an_identity_record_read_back_carries_its_two_identities(self, tmp_path, monkeypatch):
        monkeypatch.setattr(orchestrator, "IDENTITY_DIR", str(tmp_path))
        monkeypatch.setattr(orchestrator, "_MISMATCH_HELD", {})
        reason = i18n.Reason("reason.identity.mismatch", current="0xnew", expected="0xold")
        # The record holds the English, as an older release wrote it too.
        (tmp_path / "cashpilot-mysterium").write_text(f"MISMATCH {reason}", encoding="utf-8")
        node = MagicMock()
        node.name = "cashpilot-mysterium"
        found = orchestrator.identity_problem(node)
        assert found == reason
        assert i18n.wire(found) == {
            "code": "reason.identity.mismatch",
            "params": {"current": "0xnew", "expected": "0xold"},
        }


def _held_worker(held, wired):
    container = {"name": "cashpilot-mysterium", "slug": "mysterium", "status": "exited", "held": held}
    if wired is not None:
        container["held_reason"] = wired
    return {
        "id": 1,
        "name": "alpha",
        "status": "online",
        "system_info": json.dumps({"docker_available": True}),
        "containers": json.dumps([container]),
    }


class TestTheUIReadsIt:
    def test_a_held_node_reads_in_the_readers_language(self, spanish):
        english = "it runs demo/demo:2, not the image the catalog pins"
        wired = {"code": "reason.spec.image", "params": {"image": "demo/demo:2"}}
        found = _in("es", lambda: asyncio.run(main._get_all_worker_containers([_held_worker(english, wired)])))
        assert found[0]["held"] == "ejecuta demo/demo:2, no la imagen que fija el catálogo"
        older = _in("es", lambda: asyncio.run(main._get_all_worker_containers([_held_worker(english, None)])))
        assert older[0]["held"] == english

    def test_a_stuck_tunnel_change_reads_in_the_owners_language(self, spanish):
        i18n.set_background("es")
        alerts = _Alerts([_copy("earnfm")])
        entry = _stuck(_entry("earnfm"), reason="Another change to this proxy is running on this worker.")
        entry["tunnel_change"]["reason_wire"] = {"code": "reason.tunnel.busy", "params": {}}

        def run():
            _past_grace(alerts, [_worker([entry])])

        contextvars.Context().run(run)
        assert "Otro cambio de este proxy está en marcha en este worker." in alerts.rows["cashpilot-tunnel-p3-next@1"]


@pytest.mark.parametrize("fn", ["get_status", "get_status_light"])
def test_both_status_paths_send_the_key_of_a_held_node(fn, monkeypatch):
    from tests.test_digest_pinned_image_name import PINNED, _container, _image

    node = _container(_image(digests=[PINNED]), cid="held-proxybase", slug="proxybase")
    monkeypatch.setitem(lan_fence._state, "guard", {node.name: lan_fence.RESTORE_UNFINISHED})
    client = MagicMock()
    client.containers.list.side_effect = [[node], [node]]
    with (
        patch.object(orchestrator, "_get_client", return_value=client),
        patch.object(orchestrator, "_collect_stats_bulk", return_value={}),
    ):
        [entry] = getattr(orchestrator, fn)()
    assert entry["held"] == lan_fence.RESTORE_UNFINISHED
    assert entry["held_reason"] == {"code": "reason.held.restore_unfinished", "params": {}}


def test_a_refused_start_words_its_reason_in_the_pages_language(tmp_path, monkeypatch):
    """The worker answers a Start in the language it is asked in, the reason included."""
    source = json.loads((ROOT / "app/i18n/en.json").read_text(encoding="utf-8"))
    spanish = {**SPANISH, "err.orchestrator.not_started": "{slug} no arrancó: {problem}."}
    (tmp_path / "en.json").write_text(json.dumps(source), encoding="utf-8")
    stamped = {k: {"text": v, "source": i18n.source_hash(source[k])} for k, v in spanish.items()}
    (tmp_path / "es.json").write_text(json.dumps(stamped, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(i18n, "DIR", tmp_path)
    i18n.reload()
    node = MagicMock()
    node.name = "cashpilot-mysterium"
    try:
        with (
            patch.object(orchestrator, "_get_client", return_value=MagicMock()),
            patch.object(lan_fence, "fence_problem", return_value=None),
            patch.object(lan_fence, "resolve_mode", return_value=lan_fence.MODE_ON),
            patch.object(orchestrator, "deploy_failed", return_value=set()),
            patch.object(
                orchestrator, "gated_spec_problem", return_value=i18n.Reason("reason.spec.image", image="x/y:2")
            ),
            pytest.raises(orchestrator.ContainerNetworkError) as refused,
        ):
            _in("es", orchestrator._require_startable, node, "mysterium")
    finally:
        i18n.reload()
    assert "ejecuta x/y:2, no la imagen que fija el catálogo" in str(refused.value)
