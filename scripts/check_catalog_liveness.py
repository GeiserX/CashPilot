#!/usr/bin/env python3
"""Check that every catalog service's external references are still alive.

Catalog rot is this project's most common user-facing failure: a provider changes
its backend, drops its image or kills its referral programme, and the first person
to notice is a user whose service silently stopped earning. This script turns that
into a scheduled report instead.

For each ``services/**/*.yml`` it checks:

* ``website`` still answers
* ``referral.signup_url`` still answers **and still carries its referral code** --
  a dead or code-stripped referral link is direct lost revenue
* ``docker.image`` still resolves in its registry

Exit code is 0 unless the script itself could not run. A dead link is a *finding
to report*, not a build failure: a flaky provider must not turn the weekly run red,
because a job that is red every week is a job nobody reads.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

import httpx
import yaml

# Statuses
OK = "ok"
DEAD = "dead"
UNREACHABLE = "unreachable"
SKIPPED = "skipped"

# Some providers answer a bare HEAD with a guard rather than the page. These prove
# the host is alive, which is all this check claims to establish.
_ALIVE_BUT_GUARDED = frozenset({401, 403, 405, 429})

# A browser-ish UA: several providers 403 the default httpx agent outright.
_UA = "Mozilla/5.0 (compatible; CashPilot-catalog-check/1.0; +https://github.com/GeiserX/CashPilot)"


@dataclass
class Finding:
    slug: str
    kind: str  # "website" | "referral" | "image"
    target: str
    status: str
    detail: str = ""

    @property
    def is_problem(self) -> bool:
        """Actionable: the catalog itself is wrong and a human should change it.

        UNREACHABLE deliberately does NOT count. It means "we could not tell" —
        a provider having a bad afternoon, a registry rate-limit, a timeout. If
        those raised the problem count, the weekly issue would cry wolf most
        weeks and get ignored, which costs us the one week it is real. They are
        still reported, just in their own section.
        """
        return self.status == DEAD

    @property
    def is_inconclusive(self) -> bool:
        return self.status == UNREACHABLE


def classify_status(status_code: int) -> str:
    """Map an HTTP status onto liveness.

    5xx is deliberately *not* "dead": a provider having a bad afternoon is not a
    retired service, and calling it dead would churn the catalog on noise.
    """
    if 200 <= status_code < 300:
        return OK
    if status_code in _ALIVE_BUT_GUARDED:
        return OK
    if 300 <= status_code < 400:
        return OK  # redirect chains are followed; a bare 3xx here is still alive
    if 400 <= status_code < 500:
        return DEAD
    return UNREACHABLE


def referral_code_lost(original: str, final: str) -> bool:
    """True when a referral link redirected to a bare homepage, dropping its code.

    The classic symptom of a retired referral programme: ``…/signup?ref=CODE`` ends
    up at ``https://provider.com/``.

    This detects the *collapse*, which is NOT the same as proving the code was
    lost. A very common healthy pattern looks identical from outside: the site
    reads ``?ref=CODE``, stores it in the session, sets a cookie and 302s to a
    clean URL. ProxyLite does exactly that -- ``?r=CODE`` returns 302 + a
    PHPSESSID cookie while the bare homepage returns 200. Telling the two apart
    needs an account, so callers must report this as inconclusive, never as a
    confirmed dead link.
    """
    orig = urlparse(original)
    fin = urlparse(final)
    had_identity = bool(orig.query) or orig.path.strip("/")
    landed_bare = not fin.query and not fin.path.strip("/")
    return bool(had_identity and landed_bare)


def check_url(client: httpx.Client, url: str) -> tuple[str, str]:
    """Return (status, detail) for one URL."""
    if not url:
        return SKIPPED, "not set"
    try:
        try:
            resp = client.head(url)
        except httpx.TooManyRedirects:
            # Some sites redirect-loop on HEAD but serve GET fine (observed on a live
            # provider). Retry before calling a working site unreachable.
            resp = client.get(url)
        # Some servers simply refuse HEAD; retry once with GET before judging.
        if resp.status_code in (405, 501):
            resp = client.get(url)
        status = classify_status(resp.status_code)
        detail = f"HTTP {resp.status_code}"
        if status == OK and str(resp.url) != url:
            detail += f" -> {resp.url}"
        return status, detail
    except httpx.HTTPError as exc:
        return UNREACHABLE, type(exc).__name__


def check_image(image: str) -> tuple[str, str]:
    """Return (status, detail) for a Docker image reference."""
    if not image:
        return SKIPPED, "no image (not Docker-deployable)"
    try:
        proc = subprocess.run(  # noqa: S603
            ["docker", "manifest", "inspect", "--", image],  # noqa: S607
            capture_output=True,
            text=True,
            timeout=90,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return UNREACHABLE, f"could not run docker: {exc}"
    if proc.returncode == 0:
        return OK, "manifest found"
    stderr = (proc.stderr or "").strip()
    # A rate-limited or auth-gated registry says nothing about whether the image
    # still exists — reporting that as "dead" would send us deleting live services.
    if any(marker in stderr.lower() for marker in ("toomanyrequests", "rate limit", "unauthorized", "denied")):
        return UNREACHABLE, "registry rate-limited or auth-gated"
    lines = stderr.splitlines()
    return DEAD, lines[-1][:160] if lines else "manifest not found"


def load_services(services_dir: Path) -> tuple[list[dict], list[Finding]]:
    """Load every service YAML, sorted by slug.

    Returns the services AND a finding per file that could not be read. A file
    that fails to parse was previously only a stderr warning, so a catalog with
    a broken YAML silently checked fewer services and still reported "All good"
    — the one case where the report is confidently wrong. An unparseable
    catalog file is a real defect, so it is surfaced as a problem.
    """
    services = []
    errors: list[Finding] = []
    for path in sorted(services_dir.rglob("*.y*ml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text())
        except (yaml.YAMLError, OSError) as exc:
            # Flattened: a YAML error spans several lines, and a raw newline
            # inside a markdown table cell breaks the rest of the table.
            reason = " ".join(str(exc).split())
            errors.append(Finding(path.stem, "catalog", str(path), DEAD, f"could not parse: {reason[:160]}"))
            continue
        if isinstance(data, dict) and data.get("slug"):
            services.append(data)
        else:
            errors.append(Finding(path.stem, "catalog", str(path), DEAD, "no slug — not a valid service definition"))
    return sorted(services, key=lambda s: s["slug"]), errors


def check_service(client: httpx.Client, svc: dict, *, check_images: bool) -> list[Finding]:
    slug = svc["slug"]
    findings: list[Finding] = []

    # Services the catalog already marks as gone are expected to be dead; checking
    # them would just generate noise the maintainer has already acted on.
    if svc.get("status") in ("dead", "dropped"):
        return [Finding(slug, "website", svc.get("website", ""), SKIPPED, f"status: {svc['status']}")]

    website = svc.get("website", "") or ""
    status, detail = check_url(client, website)
    findings.append(Finding(slug, "website", website, status, detail))

    signup = ((svc.get("referral") or {}).get("signup_url")) or ""
    if signup:
        status, detail = check_url(client, signup)
        if status == OK:
            try:
                final = str(client.head(signup).url)
                if referral_code_lost(signup, final):
                    # Inconclusive, not dead: a site that captures the code into
                    # the session and redirects to a clean URL is indistinguishable
                    # from one that dropped it. Verified against ProxyLite, where
                    # this exact shape is a WORKING referral link.
                    status, detail = (
                        UNREACHABLE,
                        f"referral code not visible after redirect -> {final} (verify manually)",
                    )
            except httpx.HTTPError:
                pass
        findings.append(Finding(slug, "referral", signup, status, detail))

    if check_images:
        image = ((svc.get("docker") or {}).get("image")) or ""
        status, detail = check_image(image)
        findings.append(Finding(slug, "image", image, status, detail))

    return findings


# One legend, rendered by every report shape so the two can never drift apart.
_LEGEND = "_`unreachable` means we could not tell -- a transient provider outage, a registry rate-limit, or a referral link that redirected somewhere its code is no longer visible (which is also what a working session-capture link looks like). Reported, but not counted as a problem. `dead` means the reference answered with a client error, or a catalog file could not be read._"


def build_report(findings: list[Finding]) -> str:
    problems = [f for f in findings if f.is_problem]
    unknown = [f for f in findings if f.is_inconclusive]
    checked = len({f.slug for f in findings})
    lines = ["# Catalog liveness report", ""]

    def _unknown_section() -> list[str]:
        if not unknown:
            return []
        out = [
            "## Could not verify (not necessarily broken)",
            "",
            "| Service | What | Detail | Target |",
            "|---|---|---|---|",
        ]
        out += [f"| `{f.slug}` | {f.kind} | {f.detail} | {f.target} |" for f in unknown]
        return out + [""]

    if not problems:
        lines += [f"All good — {checked} services checked, no dead references."]
        if unknown:
            lines += ["", f"{len(unknown)} check(s) were inconclusive and are listed below.", ""]
            lines += _unknown_section()
            # The legend belongs here too: an all-inconclusive run is exactly when
            # a reader needs to know that "unreachable" is not "broken".
            lines += [_LEGEND]
        return "\n".join(lines)

    lines += [f"**{len(problems)} problem(s)** across {checked} services checked.", ""]

    broken_yaml = [f for f in problems if f.kind == "catalog"]
    if broken_yaml:
        # First: if the catalog itself won't parse, every other number here is
        # computed over an incomplete set and can't be trusted.
        lines += ["## Catalog files that could not be read", "", "| File | Detail |", "|---|---|"]
        lines += [f"| `{f.target}` | {f.detail} |" for f in broken_yaml]
        lines += [""]

    referral = [f for f in problems if f.kind == "referral"]
    if referral:
        # Called out first and explicitly: these are lost signups, not just broken links.
        lines += ["## Referral links (lost revenue)", "", "| Service | Status | Detail | URL |", "|---|---|---|---|"]
        lines += [f"| `{f.slug}` | {f.status} | {f.detail} | {f.target} |" for f in referral]
        lines += [""]

    rest = [f for f in problems if f.kind not in ("referral", "catalog")]
    if rest:
        lines += [
            "## Websites and images",
            "",
            "| Service | What | Status | Detail | Target |",
            "|---|---|---|---|---|",
        ]
        lines += [f"| `{f.slug}` | {f.kind} | {f.status} | {f.detail} | {f.target} |" for f in rest]
        lines += [""]

    lines += _unknown_section()

    lines += [_LEGEND]
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--services-dir", default="services", type=Path)
    parser.add_argument("--timeout", default=20.0, type=float)
    parser.add_argument("--skip-images", action="store_true", help="skip registry checks (no docker available)")
    parser.add_argument("--output", type=Path, help="also write the report here")
    args = parser.parse_args()

    if not args.services_dir.is_dir():
        print(f"services dir not found: {args.services_dir}", file=sys.stderr)
        return 2

    services, parse_errors = load_services(args.services_dir)
    if not services:
        print("no services found — refusing to report an empty catalog as healthy", file=sys.stderr)
        return 2

    findings: list[Finding] = list(parse_errors)
    headers = {"User-Agent": _UA}
    with httpx.Client(follow_redirects=True, timeout=args.timeout, headers=headers) as client:
        for svc in services:
            findings.extend(check_service(client, svc, check_images=not args.skip_images))

    report = build_report(findings)
    print(report)
    if args.output:
        args.output.write_text(report)
    if summary := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(summary, "a") as fh:
            fh.write(report + "\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
