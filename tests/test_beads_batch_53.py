"""The claim modal reported "Service not found" for services that plainly exist.

``openClaimModal`` looks the service up in ``/api/earnings/breakdown``, which is
built from the **earnings table**. A service that has never produced a reading is
simply absent from it, and the modal rendered that absence as *Service not
found* — which is false. It is in the catalog, on the dashboard, deployed and
running.

Measured on the reference fleet: **5 of 18 tracked services** hit this —
``anyone-protocol``, ``proxybase``, ``proxylite``, ``titan``, ``uprock``.

Three different facts hide behind one empty result:

* not in the catalog at all — the only case that earns the old wording;
* tracked, has a collector, no readings yet — add credentials, or wait;
* tracked, no collector exists — no credential will ever help, and it may still
  be earning on the provider's own dashboard.

The behaviour lives in ``scripts/claim_modal_check.mjs``, which runs the real
function against stubbed responses. What is pinned here is the wiring that a
harness cannot see: that the failure path calls the helper at all, and that the
harness runs in CI.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"
HARNESS = ROOT / "scripts" / "claim_modal_check.mjs"


class TestTheModalNoLongerLies:
    def _open_claim_body(self):
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("async function openClaimModal(")
        return js[start : start + 1400]

    def test_the_old_wording_is_gone_from_the_failure_path(self):
        assert "Service not found." not in self._open_claim_body()

    def test_it_delegates_to_the_explaining_helper(self):
        assert "renderNoEarningsYet(platform, title, body)" in self._open_claim_body()

    def test_the_helper_exists_and_is_async(self):
        js = APP_JS.read_text(encoding="utf-8")
        assert "async function renderNoEarningsYet(" in js

    def test_it_consults_the_catalog_rather_than_guessing(self):
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("async function renderNoEarningsYet(")
        body = js[start : start + 1800]
        assert "/api/services/available" in body
        assert "has_collector" in body

    def test_a_failed_lookup_is_not_reported_as_a_missing_service(self):
        """Three answers, plus "I could not check" — which is a fourth."""
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("async function renderNoEarningsYet(")
        body = js[start : start + 1800]
        assert "Could not check this service" in body

    def test_the_error_detail_is_escaped(self):
        js = APP_JS.read_text(encoding="utf-8")
        start = js.index("async function renderNoEarningsYet(")
        body = js[start : start + 1800]
        assert "escapeHtml(err.message" in body


class TestTheHarnessRunsInCI:
    def test_the_script_exists(self):
        assert HARNESS.is_file()

    def test_the_workflow_runs_it(self):
        doc = yaml.safe_load((ROOT / ".github" / "workflows" / "test.yml").read_text(encoding="utf-8"))
        commands = " ".join(
            str(step.get("run", "")) for job in doc["jobs"].values() for step in (job.get("steps") or [])
        )
        assert "node scripts/claim_modal_check.mjs" in commands

    def test_it_is_browser_free(self):
        text = HARNESS.read_text(encoding="utf-8")
        assert "9222" not in text and "puppeteer" not in text.lower()

    def test_it_keeps_the_async_keyword_when_extracting(self):
        """Slicing from `function` alone yields a body with a bare `await`.

        That is a SyntaxError, and it means the extraction silently changed what
        was under test — which happened while writing this.
        """
        assert "asyncPrefix" in HARNESS.read_text(encoding="utf-8")
