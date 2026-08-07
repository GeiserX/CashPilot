"""Audit the catalog's referral links against the referral registry.

Referral links are revenue, and nothing used to check them: a link could lose
its code in a domain migration (ProxyBase kept earning $0 on a retired image
for months before anyone looked), or a service could sit in the catalog with a
bare URL while its provider ran a paying program (Bytebenefit spent ~5 months
wrongly dead AND bare -- every signup in that window was unattributed).

The registry is three-valued, because absent is not "no":

    referral.code       the referral code itself. Its presence means the
                        provider has a program AND a code exists; the checker
                        proves the code still appears in signup_url.
    referral.program    true  = provider verified to run a program
                              (with no code yet, that is an ACTION item)
                        false = provider verified NOT to run one
                              (a bare URL is correct, not a gap)
    (neither)           UNKNOWN: nobody has checked. Reported as the research
                        backlog, never failed -- an unresearched fact is not
                        an error, and failing on it would teach people to
                        write `program: false` without checking.

Exit codes: 1 on inconsistencies (always -- these are regressions), and with
--strict also on action items. Unknowns never fail in either mode.
"""

from __future__ import annotations

import argparse
import pathlib
import sys
from urllib.parse import parse_qsl, urlsplit

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]

#: Statuses whose signup links are shown to users, so gaps there cost revenue.
#: Consistency errors are checked for EVERY status: a dead service keeps its
#: code, so a resurrection (the Bytebenefit shape) comes back attributed.
EARNING_STATUSES = {"active", "beta"}


def load_services(services_dir: pathlib.Path) -> list[dict]:
    """Load every service YAML, refusing to silently skip a broken one.

    app.catalog drops invalid entries by design (the UI must boot around one
    bad file); an *audit* must not, because a file this loader skipped would
    simply vanish from the report and read as "nothing to fix". The glob never
    sees services/_schema.yml -- it lives one level above the category dirs.
    """
    services = []
    for path in sorted(services_dir.glob("*/*.yml")):
        try:
            data = yaml.safe_load(path.read_text())
        except yaml.YAMLError as exc:
            raise SystemExit(f"{path}: unparseable YAML: {exc}") from exc
        if not isinstance(data, dict):
            raise SystemExit(f"{path}: expected a mapping, got {type(data).__name__}")
        data["_file"] = str(path.relative_to(services_dir.parent))
        services.append(data)
    return services


def code_attributes_url(code: str, url: str) -> bool:
    """True when the code is ANCHORED in the URL, not merely a substring.

    `"grass" in "https://app.grass.io/register"` is a hostname coincidence,
    not attribution. The code counts only where a provider would read it: a
    query-parameter value (?ref=CODE), a bare query key (?CODE -- spide's
    shape), or a whole path segment (/i/CODE -- uprock, earnapp, honeygain).
    """
    parts = urlsplit(url)
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if code == value or (value == "" and code == key):
            return True
    return code in parts.path.split("/")


def audit(services: list[dict]) -> dict[str, list[str]]:
    """Returns findings grouped as errors / actions / unknowns."""
    errors: list[str] = []
    actions: list[str] = []
    unknowns: list[str] = []

    for svc in services:
        slug = svc.get("slug", svc.get("_file", "?"))
        ref = svc.get("referral")
        if ref is not None and not isinstance(ref, dict):
            errors.append(f"{slug}: referral must be a mapping, got {type(ref).__name__}")
            continue
        ref = ref or {}
        signup = ref.get("signup_url") or ""
        code = ref.get("code")
        program = ref.get("program")  # True / False / None -- three-valued

        # Anything else has fallen out of YAML's booleans ("no", "TODO", 1…).
        # It must not silently satisfy neither arm below and vanish from every
        # bucket -- a service that vanished from the report reads as fine.
        # Identity, not equality: `1 == True` in Python, so a membership test
        # would wave `program: 1` through as a boolean it never was.
        if not (program is True or program is False or program is None):
            errors.append(f"{slug}: referral.program must be true, false, or absent -- got {program!r}")
            continue

        if code is not None:
            if not str(code).strip():
                errors.append(
                    f"{slug}: referral.code is empty -- delete the key or record the real code; empty is not a value"
                )
            elif not signup:
                errors.append(f"{slug}: has a referral.code but no referral.signup_url to carry it")
            elif not code_attributes_url(str(code), signup):
                errors.append(
                    f"{slug}: referral.code {code!r} is not anchored in "
                    f"signup_url {signup!r} -- the link lost its attribution. "
                    f"If the provider migrated domains, leave code untouched "
                    f"and flag it in the PR: only the account holder can "
                    f"re-issue the link"
                )
            if program is False:
                errors.append(f"{slug}: has a referral.code but says program: false -- one of the two is wrong")

        if svc.get("status") in EARNING_STATUSES and code is None:
            if not signup:
                actions.append(f"{slug}: no referral.signup_url recorded -- users have nowhere to sign up from")
            elif program is True:
                actions.append(
                    f"{slug}: provider runs a referral program but no code is "
                    f"recorded -- sign up and add referral.code (lost revenue "
                    f"until then)"
                )
            elif program is None:
                unknowns.append(
                    f"{slug}: nobody has checked whether the provider runs a "
                    f"referral program -- research it, then record "
                    f"program: true/false"
                )

    return {"errors": errors, "actions": actions, "unknowns": unknowns}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strict",
        action="store_true",
        help="also fail on action items (known program, no code yet)",
    )
    parser.add_argument(
        "--services-dir",
        type=pathlib.Path,
        default=ROOT / "services",
        help="catalog root to audit (tests point this at fixtures)",
    )
    args = parser.parse_args()

    findings = audit(load_services(args.services_dir))

    for line in findings["errors"]:
        print(f"ERROR   {line}")
    for line in findings["actions"]:
        print(f"ACTION  {line}")
    for line in findings["unknowns"]:
        print(f"UNKNOWN {line}")

    print(
        f"\n{len(findings['errors'])} error(s), "
        f"{len(findings['actions'])} action item(s), "
        f"{len(findings['unknowns'])} unresearched"
    )

    if findings["errors"]:
        return 1
    if args.strict and findings["actions"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
