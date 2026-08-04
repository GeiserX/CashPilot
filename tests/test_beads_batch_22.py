"""CashPilot-2oo: every wizard-deployed host registered as "cashpilot-{hostname}".

Five catalog entries declare ``default: "cashpilot-{hostname}"`` — honeygain,
traffmonetizer, proxybase and iproyal (twice). The deploy path substituted
``{hostname}``, but only while building the DEFAULTS, and the setup wizard
prefilled each input with the raw default. So the browser posted
``"HONEYGAIN_DEVICE_NAME": "cashpilot-{hostname}"`` back as a USER value, user
values are applied after (and therefore win over) defaults, and the literal
eight-character placeholder shipped as the device name.

Confirmed in the audit by reading the rendered step-3 inputs in a real browser
and the exact body ``_deployToWorkers`` would POST.

It matters beyond looking wrong: providers count devices BY NAME, so every host
deployed through the wizard registered under one identical name.

Fixed twice over, because either alone leaves a hole:

* the substitution now runs over the merged env, so a value that reaches the
  server still gets resolved — which is also the right reading of a string
  somebody typed by hand, since nobody means the literal "{hostname}";
* the wizard shows a template default as the input's PLACEHOLDER instead of its
  value, so an untouched field posts nothing and the server fills it in per
  worker.
"""

from __future__ import annotations

import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
APP_JS = ROOT / "app" / "static" / "js" / "app.js"


def without_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return "\n".join(re.sub(r"(^|\s)//.*$", "", line) for line in text.splitlines())


class TestThePlaceholderIsResolvedEvenWhenItArrivesAsAUserValue:
    def _env_after_merge(self, user_env, hostname="watchtower"):
        """Reproduce the exact merge the handler performs.

        Driving api_deploy end to end needs most of the app mocked; the merge is
        four lines and is the whole defect, so it is exercised directly against
        the real source rather than through a fake that could drift from it.
        """
        import inspect

        from app import main

        source = inspect.getsource(main.api_deploy)
        start = source.index("hn = body.hostname or HOSTNAME_PREFIX")
        end = source.index("\n", source.index("env = {k: v.replace", start))
        snippet = "\n".join(line[4:] if line.startswith("    ") else line for line in source[start:end].splitlines())
        scope = {
            "body": MagicMock(hostname=hostname, env=user_env),
            "HOSTNAME_PREFIX": "cashpilot",
            "docker_conf": {
                "env": [
                    {"key": "HONEYGAIN_DEVICE_NAME", "default": "cashpilot-{hostname}"},
                    {"key": "HONEYGAIN_EMAIL", "default": ""},
                ]
            },
        }
        exec(snippet, scope)  # noqa: S102 - the real source, not a reimplementation
        return scope["env"]

    def test_the_untouched_default_still_resolves(self):
        """The behaviour that already worked must keep working."""
        env = self._env_after_merge(None)
        assert env["HONEYGAIN_DEVICE_NAME"] == "cashpilot-watchtower"

    def test_a_posted_template_resolves_too(self):
        """The defect: the wizard posts the raw default back as a user value."""
        env = self._env_after_merge({"HONEYGAIN_DEVICE_NAME": "cashpilot-{hostname}"})
        assert env["HONEYGAIN_DEVICE_NAME"] == "cashpilot-watchtower", (
            "the literal placeholder still ships as the device name"
        )

    def test_a_real_user_value_is_left_alone(self):
        """The control: substitution must not rewrite a name someone chose."""
        env = self._env_after_merge({"HONEYGAIN_DEVICE_NAME": "my-nas"})
        assert env["HONEYGAIN_DEVICE_NAME"] == "my-nas"

    def test_two_hosts_get_two_names(self):
        """Providers count devices BY NAME; identical names is the real damage."""
        a = self._env_after_merge({"HONEYGAIN_DEVICE_NAME": "cashpilot-{hostname}"}, hostname="watchtower")
        b = self._env_after_merge({"HONEYGAIN_DEVICE_NAME": "cashpilot-{hostname}"}, hostname="geiserback")
        assert a["HONEYGAIN_DEVICE_NAME"] != b["HONEYGAIN_DEVICE_NAME"]

    def test_an_unrelated_value_is_untouched(self):
        env = self._env_after_merge({"HONEYGAIN_EMAIL": "someone@example.com"})
        assert env["HONEYGAIN_EMAIL"] == "someone@example.com"


class TestTheWizardDoesNotPrefillATemplate:
    def test_a_template_default_is_not_rendered_as_a_value(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "value=\"${escapeHtml(env.default || '')}\"" not in source, (
            "the wizard still prefills the raw default, so the template posts back as a user value"
        )

    def test_it_decides_by_looking_for_the_placeholder(self):
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "defaultIsTemplate" in source
        assert "includes('{hostname}')" in source

    def test_a_template_is_still_shown_as_a_hint(self):
        """Hiding it entirely would lose the only clue about the format."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "defaultIsTemplate ? String(env.default)" in source

    def test_an_ordinary_default_is_still_prefilled(self):
        """The control: this must not empty every field in the wizard."""
        source = without_comments(APP_JS.read_text(encoding="utf-8"))
        assert "defaultIsTemplate ? '' : (env.default || '')" in source


class TestTheCatalogStillContainsTheCaseThisIsAbout:
    def test_the_placeholder_is_still_used(self):
        """If the catalog is ever normalised, this fix stops being exercised."""
        users = [
            path.name
            for path in sorted(ROOT.joinpath("services").rglob("*.yml"))
            if "{hostname}" in path.read_text(encoding="utf-8")
        ]
        assert len(users) >= 3, f"only {users} still use the placeholder"

    @pytest.mark.parametrize("slug", ["honeygain", "traffmonetizer"])
    def test_the_named_services_declare_it(self, slug):
        for path in ROOT.joinpath("services").rglob(f"{slug}.yml"):
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            defaults = [v.get("default", "") for v in (data.get("docker") or {}).get("env", [])]
            assert any("{hostname}" in str(d) for d in defaults)
            return
        pytest.fail(f"{slug}.yml not found")
