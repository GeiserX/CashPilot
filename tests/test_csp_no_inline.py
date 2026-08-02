"""No inline handlers, so the CSP can drop unsafe-inline (CashPilot-guw).

`script-src 'unsafe-inline'` means any markup an attacker gets injected
executes, and this UI renders provider-supplied strings. Removing it needs two
things at once: every inline event attribute gone (a nonce cannot cover those —
nonces apply to `<script>`, never to `onclick=`), and the remaining inline
`<script>` blocks carrying a per-response nonce.

These are the static guards. The behavioural half — that the buttons still fire
and no violation is raised — needs a real browser and lives in
`scripts/ui_check.sh`, because a parse can see neither.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = sorted((ROOT / "app" / "templates").glob("*.html"))
JS = sorted((ROOT / "app" / "static" / "js").glob("*.js"))

# Any of these as an ATTRIBUTE is an inline handler, which a nonce cannot cover.
INLINE_EVENT = re.compile(
    r"""<[^>]*\son(?:click|change|input|submit|keyup|keydown|keypress|focus|blur|load|error|"""
    r"""mouseover|mouseout|toggle)\s*=""",
    re.I,
)


class TestNoInlineEventHandlersRemain:
    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_no_template_carries_an_inline_handler(self, path):
        found = INLINE_EVENT.findall(path.read_text(encoding="utf-8"))
        assert not found, f"{path.name} still has inline event handlers: {found[:3]}"

    @pytest.mark.parametrize("path", JS, ids=lambda p: p.name)
    def test_no_rendered_markup_carries_an_inline_handler(self, path):
        """app.js builds HTML strings; an onclick= inside one is still inline."""
        source = path.read_text(encoding="utf-8")
        code = "\n".join(line for line in source.splitlines() if not line.strip().startswith("//"))
        found = INLINE_EVENT.findall(code)
        assert not found, f"{path.name} renders inline handlers: {found[:3]}"


class TestTheCspActuallyDroppedIt:
    def _source(self) -> str:
        return (ROOT / "app" / "main.py").read_text(encoding="utf-8")

    def test_script_src_no_longer_allows_unsafe_inline(self):
        script_src = re.search(r'"script-src[^"]*"', self._source())
        assert script_src, "script-src directive not found"
        assert "unsafe-inline" not in script_src.group(0)

    def test_script_src_carries_a_nonce(self):
        assert "nonce-{nonce}" in self._source()

    def test_a_fresh_nonce_is_generated_per_response(self):
        source = self._source()
        assert "secrets.token_urlsafe" in source
        assert "request.state.csp_nonce" in source

    def test_style_src_still_allows_inline_and_the_exception_is_explained(self):
        """Inline style= attributes remain; a style injection cannot execute."""
        source = self._source()
        style_src = re.search(r'"style-src[^"]*"', source)
        assert style_src and "unsafe-inline" in style_src.group(0)
        assert "style-src keeps 'unsafe-inline'" in source, "an exception left unexplained becomes permanent"


class TestEveryInlineScriptIsNonced:
    @pytest.mark.parametrize("path", TEMPLATES, ids=lambda p: p.name)
    def test_no_unnonced_inline_script_block(self, path):
        """An unnonced block is silently blocked and the page half-works."""
        text = path.read_text(encoding="utf-8")
        bare = re.findall(r"<script(?![^>]*(?:src=|nonce=))[^>]*>", text)
        assert not bare, f"{path.name} has an inline <script> with no nonce: {bare[:2]}"


class TestDelegationIsAvailableEverywhere:
    def test_the_delegated_listener_lives_in_its_own_file(self):
        """Inside app.js it never loaded on the standalone templates.

        The onboarding and login pages do not load app.js, so their buttons
        rendered perfectly and did nothing at all. Only a browser caught it.
        """
        assert (ROOT / "app" / "static" / "js" / "delegate.js").exists()

    @pytest.mark.parametrize("name", ["base.html", "onboarding.html", "auth.html"], ids=lambda n: n)
    def test_every_entry_template_loads_it(self, name):
        text = (ROOT / "app" / "templates" / name).read_text(encoding="utf-8")
        assert "delegate.js" in text, f"{name} renders data-action buttons but never loads the listener"

    def test_it_resolves_page_local_handlers_too(self):
        """A few controls belong to one template and are not on CP."""
        text = (ROOT / "app" / "static" / "js" / "delegate.js").read_text(encoding="utf-8")
        assert "window[name]" in text

    def test_it_reports_an_unknown_handler_instead_of_doing_nothing(self):
        """A silently dead button is the failure this refactor could introduce."""
        text = (ROOT / "app" / "static" / "js" / "delegate.js").read_text(encoding="utf-8")
        assert "console.error" in text

    def test_it_tolerates_app_js_being_absent(self):
        text = (ROOT / "app" / "static" / "js" / "delegate.js").read_text(encoding="utf-8")
        assert "typeof CP !== 'undefined'" in text


class TestEveryDeclaredActionExists:
    def test_no_data_action_names_a_handler_nobody_defined(self):
        actions: set[str] = set()
        for path in TEMPLATES + JS:
            actions |= set(
                re.findall(r'data-(?:action|then)="([A-Za-z_][A-Za-z0-9_]*)"', path.read_text(encoding="utf-8"))
            )
        assert actions, "no data-action attributes found at all — the migration did not happen"

        app_js = (ROOT / "app" / "static" / "js" / "app.js").read_text(encoding="utf-8")
        exported = set(re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*),\s*$", app_js, re.M))
        page_local: set[str] = set()
        for path in TEMPLATES:
            text = path.read_text(encoding="utf-8")
            page_local |= set(re.findall(r"function\s+([A-Za-z_][A-Za-z0-9_]*)\s*\(", text))
            page_local |= set(re.findall(r"window\.([A-Za-z_][A-Za-z0-9_]*)\s*=", text))

        missing = sorted(actions - exported - page_local)
        assert not missing, f"data-action names with no handler anywhere: {missing}"
