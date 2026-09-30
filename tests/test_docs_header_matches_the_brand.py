"""The docs header must look like the product's own mark.

Two things were off on https://geiserx.github.io/CashPilot/ :

* the plane in the header logo was ``#FFFFFF``. The top of the sun gradient is
  ``#FFD54F``, so a white plane on it is very nearly invisible — it read as a
  smudge rather than an aircraft. banner.svg has always drawn it as a dark
  silhouette (``#000010`` at 0.65), and that is the official mark;
* the "CashPilot" wordmark rendered in plain white, set apart from the mark, so
  the two read as an icon and some unrelated text. The banner sets them as one
  lockup with the wordmark in the pink gradient ``#f43f5e`` -> ``#fb7185``.

Verified in a real headless browser at the header's actual size, not inferred
from the source: the plane is the one detail small enough that "it is dark in
the file" and "you can see it at 24px" are different claims.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LOGO = ROOT / "docs" / "images" / "logo.svg"
BANNER = ROOT / "docs" / "images" / "banner.svg"
THEME_CSS = ROOT / "docs" / "stylesheets" / "theme.css"

# The banner's own values, which are what "official" means here.
OFFICIAL_PLANE_FILL = "#000010"
OFFICIAL_PINK_FROM = "#f43f5e"
OFFICIAL_PINK_TO = "#fb7185"


def _plane_fill(svg_text: str) -> str | None:
    """The fill on the aircraft group (``<g id="plane">``), wherever it sits in the file."""
    match = re.search(r'<g\b[^>]*\bid="plane"[^>]*>', svg_text, re.S)
    if match is None:
        return None
    fill = re.search(r'\bfill="([^"]+)"', match.group(0))
    return fill.group(1).lower() if fill else None


class TestThePlaneIsTheOfficialSilhouette:
    def test_the_header_logo_plane_is_not_white(self):
        fill = _plane_fill(LOGO.read_text(encoding="utf-8"))
        assert fill is not None, "no aircraft path found in docs/images/logo.svg"
        assert fill not in ("#fff", "#ffffff", "white"), (
            "the plane is white again — on the #FFD54F top of the sun gradient it disappears"
        )

    def test_it_is_the_same_colour_the_banner_uses(self):
        assert _plane_fill(LOGO.read_text(encoding="utf-8")) == OFFICIAL_PLANE_FILL.lower()

    def test_the_banner_still_defines_that_colour(self):
        """If the banner is restyled, this test should be updated with it."""
        assert _plane_fill(BANNER.read_text(encoding="utf-8")) == OFFICIAL_PLANE_FILL.lower()

    def test_the_two_marks_agree(self):
        """The point of the fix: one aircraft colour across the brand."""
        assert _plane_fill(LOGO.read_text(encoding="utf-8")) == _plane_fill(BANNER.read_text(encoding="utf-8"))

    def test_the_sun_gradient_is_unchanged(self):
        """The control: this must not have been "fixed" by darkening the sun."""
        text = LOGO.read_text(encoding="utf-8")
        assert "#FFD54F" in text and "#FF9800" in text

    def test_the_favicon_has_a_plate_and_the_logo_does_not(self):
        """The tab needs a plate so the warm disc reads on a light or dark strip;
        the header sits on the banner sky already, where a plate would be a box."""
        icon = (ROOT / "docs" / "images" / "icon.svg").read_text(encoding="utf-8")
        assert 'rx="56"' in icon and 'fill="#0d0025"' in icon
        assert "rx=" not in LOGO.read_text(encoding="utf-8")


# Every place the mark is drawn. The favicon, icon and logo are standalone
# files; the templates inline the same SVG so the header needs no extra request.
MARKS = [
    ROOT / "app" / "static" / "favicon.svg",
    ROOT / "docs" / "images" / "icon.svg",
    LOGO,
    ROOT / "app" / "templates" / "auth.html",
    ROOT / "app" / "templates" / "base.html",
    ROOT / "app" / "templates" / "onboarding.html",
]


def _plane_paths(svg_text: str) -> list[str]:
    """The path data inside the aircraft group."""
    block = re.search(r'<g\b[^>]*\bid="plane"[^>]*>(.*?)</g>', svg_text, re.S)
    return re.findall(r'\bd="([^"]+)"', block.group(1)) if block else []


@pytest.mark.parametrize("mark", MARKS, ids=lambda p: str(p.relative_to(ROOT)))
def test_every_mark_flies_the_banner_jet(mark):
    """One aircraft across the brand: the business jet the banner draws."""
    jet = _plane_paths(BANNER.read_text(encoding="utf-8"))
    assert len(jet) == 5, "banner.svg no longer has the five-part business jet"
    text = mark.read_text(encoding="utf-8")
    # One jet per sun: onboarding.html inlines the mark three times.
    suns = text.count('mask="url(#cpBands)"')
    assert suns >= 1, f"{mark.name} has no sun disc"
    wrong = [d for d in jet if text.count(d) != suns]
    assert not wrong, f"{mark.name} does not draw the banner's business jet on every sun"
    assert "M0,-46" not in text, f"{mark.name} still draws the old plane"


class TestTheWordmarkMatchesTheBanner:
    def _css(self):
        return THEME_CSS.read_text(encoding="utf-8")

    @pytest.mark.parametrize("colour", [OFFICIAL_PINK_FROM, OFFICIAL_PINK_TO])
    def test_it_uses_the_banner_pink(self, colour):
        assert colour in self._css(), f"the header wordmark does not use the banner's {colour}"

    def test_those_are_the_colours_the_banner_declares(self):
        """Pinned to the banner, so a rebrand there fails here rather than drifting."""
        banner = BANNER.read_text(encoding="utf-8")
        assert OFFICIAL_PINK_FROM in banner and OFFICIAL_PINK_TO in banner

    def test_only_the_site_name_is_painted(self):
        """Material swaps in the PAGE title on scroll using the same class.

        Styling every .md-header__topic would turn each page's heading pink in
        the header, which is not what the banner does.
        """
        css = self._css()
        assert ".md-header__topic:first-child .md-ellipsis" in css
        assert re.search(r"^\.md-header__topic \.md-ellipsis", css, re.M) is None

    def test_the_gradient_is_actually_clipped_to_the_text(self):
        """Without background-clip the rule paints a pink box, not pink letters."""
        css = self._css()
        assert "background-clip: text" in css
        assert "color: transparent" in css

    def test_the_mark_and_the_wordmark_are_one_lockup(self):
        """They sat far enough apart to read as unrelated elements."""
        css = self._css()
        assert ".md-header__button.md-logo" in css
        assert ".md-header__title" in css


class TestTheDocsStillBuild:
    def test_mkdocs_points_at_this_logo_and_stylesheet(self):
        """A perfect logo the site does not load is not a fix."""
        config = (ROOT / "mkdocs.yml").read_text(encoding="utf-8")
        assert "logo: images/logo.svg" in config
        assert "favicon: images/icon.svg" in config
        assert "stylesheets/theme.css" in config
