#!/usr/bin/env python3
"""Every GitHub Action this repo uses must actually exist, and say so honestly.

A pinned SHA is unverifiable by eye, which is exactly how a fabricated one
survived here: `collector-live-check.yml` shipped

    actions/github-script@60a0d83039c74a4aa971cc2a0930ae7e2fe2c8bd # v7.0.4

where the SHA shares its first sixteen characters with the real v7.0.1 commit
and then diverges into nothing, and the tag named in the comment was never
released. GitHub resolves every action BEFORE the first step, so the job died
in "Set up job" every night for six nights, having never checked a provider --
and the workflow's own `if: failure()` alarm was a step inside that job, so it
never fired either. Nothing was reported. The pin was wrong in the same commit
that introduced the workflow, so the check had never once run.

Two failure modes, both checked here:

* the ref does not resolve at all -- a typo, a deleted tag, or an invented SHA;
* the ref resolves but its `# vX.Y.Z` comment names a tag that does not exist,
  or one that points at a DIFFERENT commit. A version comment is the only
  human-readable claim about a SHA, and a lying one is how a reviewer is
  talked past a supply-chain change.

Three-valued, like everything else here: a 404 is a finding, a rate limit or a
network failure is `unknown` and never fails the run. A check that reddens on
someone else's outage teaches people to ignore it -- and this file exists
precisely because an ignorable alarm is the same as no alarm.

    python scripts/check_action_pins.py            # audit .github/workflows
    python scripts/check_action_pins.py --offline  # parse only, no network
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parents[1]
API = "https://api.github.com"

#: `uses: owner/repo@ref` or `uses: owner/repo/sub/path@ref`, with an optional
#: trailing `# v1.2.3` comment. Local (`./…`) and container (`docker://…`)
#: actions are deliberately not matched: they resolve from the checkout or a
#: registry, not from a git ref, so there is no ref to verify.
_USES = re.compile(
    r"^\s*-?\s*uses:\s*(?P<repo>[A-Za-z0-9._-]+/[A-Za-z0-9._-]+)(?P<sub>(?:/[A-Za-z0-9._-]+)*)"
    r"@(?P<ref>[A-Za-z0-9._/-]+)\s*(?:#\s*(?P<comment>\S+))?"
)
_SHA = re.compile(r"^[0-9a-f]{40}$")
#: A comment naming a full MAJOR.MINOR.PATCH is claiming one immutable release,
#: so the pinned SHA must be that release. A bare `v4` or `v4.2` names a tag
#: that MOVES: github/codeql-action's `v4` currently points at v4.37.6, so a
#: pin one release behind is not a lying comment, it is just behind -- which is
#: Dependabot's business, not a red build. Verified against two live repos that
#: this check first reported wrongly.
_FULL_SEMVER = re.compile(r"^v?\d+\.\d+\.\d+")


def _tag_spellings(comment: str) -> list[str]:
    """Both `1.24.1` and `v1.24.1`, because projects differ.

    erlef/setup-beam tags `v1.24.1` while the comment beside the pin says
    `1.24.1`; resolving only what was written called a correct pin fabricated.
    """
    bare = comment.lstrip("v")
    seen: list[str] = []
    for candidate in (comment, f"v{bare}", bare):
        if candidate and candidate not in seen:
            seen.append(candidate)
    return seen


OK = "ok"
MISSING = "missing"
MISMATCH = "mismatch"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class Use:
    repo: str
    ref: str
    comment: str | None
    file: str
    line: int

    @property
    def is_sha(self) -> bool:
        return bool(_SHA.match(self.ref))


@dataclass
class Finding:
    use: Use
    status: str
    detail: str = ""

    @property
    def is_problem(self) -> bool:
        """UNKNOWN is deliberately not a problem: it means we could not tell."""
        return self.status in (MISSING, MISMATCH)


def parse_workflows(workflow_dir: pathlib.Path) -> list[Use]:
    """Every action reference in every workflow, in file order."""
    uses: list[Use] = []
    for path in sorted(workflow_dir.glob("*.y*ml")):
        rel = str(path.relative_to(ROOT)) if path.is_relative_to(ROOT) else str(path)
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            match = _USES.match(line)
            if not match:
                continue
            comment = match.group("comment")
            # Only a version-shaped comment is a claim worth checking; a prose
            # note next to a pin is not asserting which release it is.
            if comment and not re.match(r"^v?\d", comment):
                comment = None
            uses.append(
                Use(
                    repo=match.group("repo"),
                    ref=match.group("ref"),
                    comment=comment,
                    file=rel,
                    line=number,
                )
            )
    return uses


def _resolve(repo: str, ref: str, token: str | None) -> tuple[str | None, str]:
    """Return (commit sha, status) for a ref. Never raises."""
    request = urllib.request.Request(
        f"{API}/repos/{repo}/commits/{ref}",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "CashPilot-action-pin-check",
            **({"Authorization": f"Bearer {token}"} if token else {}),
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310 - fixed https host
            return json.load(response).get("sha"), OK
    except urllib.error.HTTPError as exc:
        if exc.code in (404, 422):
            return None, MISSING
        # 401/403/429 are usually a rate limit or a token problem, and 5xx is
        # GitHub having a bad afternoon. None of those say the action is gone.
        return None, UNKNOWN
    except (urllib.error.URLError, TimeoutError, ValueError, OSError):
        return None, UNKNOWN


def audit(uses: list[Use], token: str | None) -> list[Finding]:
    findings: list[Finding] = []
    cache: dict[tuple[str, str], tuple[str | None, str]] = {}

    def resolve(repo: str, ref: str) -> tuple[str | None, str]:
        if (repo, ref) not in cache:
            cache[(repo, ref)] = _resolve(repo, ref, token)
        return cache[(repo, ref)]

    for use in uses:
        sha, status = resolve(use.repo, use.ref)
        if status == MISSING:
            findings.append(
                Finding(use, MISSING, f"{use.repo}@{use.ref} does not exist (no such commit, tag or branch)")
            )
            continue
        if status == UNKNOWN:
            findings.append(Finding(use, UNKNOWN, "could not reach the GitHub API (rate limit or network)"))
            continue

        # The ref is real. If a SHA pin also CLAIMS a version, that claim is
        # the only thing a reviewer reads, so it has to be true.
        if use.is_sha and use.comment:
            tag_sha, tag_status = None, MISSING
            for spelling in _tag_spellings(use.comment):
                tag_sha, tag_status = resolve(use.repo, spelling)
                if tag_status != MISSING:
                    break
            if tag_status == MISSING:
                findings.append(Finding(use, MISMATCH, f"comment claims {use.comment}, but {use.repo} has no such tag"))
                continue
            if tag_status == OK and not _FULL_SEMVER.match(use.comment):
                # A floating tag. Its existence is all that can be checked --
                # comparing SHAs would flag every pin that is one release
                # behind the tag it names, which is not a false claim.
                findings.append(Finding(use, OK))
                continue
            if tag_status == UNKNOWN:
                # The ref resolved but its VERSION CLAIM did not, so this pin is
                # half-checked. Reporting it as OK would be this script telling
                # the same kind of lie it exists to catch: "verified" for
                # something nobody verified.
                findings.append(
                    Finding(
                        use, UNKNOWN, f"ref resolves, but {use.comment} could not be checked (rate limit or network)"
                    )
                )
                continue
            if tag_status == OK and tag_sha != use.ref:
                findings.append(
                    Finding(
                        use,
                        MISMATCH,
                        f"comment claims {use.comment}, which is {tag_sha}, not the pinned {use.ref}",
                    )
                )
                continue
        findings.append(Finding(use, OK))
    return findings


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--workflow-dir",
        type=pathlib.Path,
        default=ROOT / ".github" / "workflows",
        help="directory of workflow files to audit",
    )
    parser.add_argument("--offline", action="store_true", help="parse only; resolve nothing")
    args = parser.parse_args()

    if not args.workflow_dir.is_dir():
        # Auditing zero files must never look like a clean bill of health.
        print(f"workflow dir not found: {args.workflow_dir}", file=sys.stderr)
        return 2

    uses = parse_workflows(args.workflow_dir)
    if not uses:
        print(
            f"no action references found in {args.workflow_dir} — refusing to report that as healthy", file=sys.stderr
        )
        return 2

    if args.offline:
        print(f"{len(uses)} action reference(s) parsed; nothing resolved (--offline)")
        return 0

    findings = audit(uses, os.getenv("GITHUB_TOKEN") or os.getenv("GH_TOKEN"))
    problems = [f for f in findings if f.is_problem]
    unknown = [f for f in findings if f.status == UNKNOWN]

    for finding in problems:
        print(f"ERROR   {finding.use.file}:{finding.use.line}  {finding.detail}")
    for finding in unknown:
        print(f"UNKNOWN {finding.use.file}:{finding.use.line}  {finding.use.repo}@{finding.use.ref} — {finding.detail}")

    checked = len(findings) - len(unknown)
    print(f"\n{checked}/{len(findings)} reference(s) verified, {len(problems)} problem(s), {len(unknown)} inconclusive")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
