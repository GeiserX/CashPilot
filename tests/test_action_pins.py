"""The action-pin audit (from the fabricated `github-script` pin).

`collector-live-check.yml` shipped a 40-character SHA whose first sixteen
characters matched the real v7.0.1 commit and whose tail was invented, with a
comment naming a tag that was never released. GitHub resolves actions before
the first step, so the job failed in setup every night for six nights without
checking a single provider, and the workflow's own alarm -- a step inside that
job -- could not fire.

These tests are offline and inject the resolver, so the suite stays
deterministic: what is pinned here is the DECISION LOGIC, not GitHub's current
tag list. The live behaviour was verified separately against the real API,
including replaying the original broken file.
"""

import importlib.util
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location("check_action_pins", ROOT / "scripts" / "check_action_pins.py")
pins = importlib.util.module_from_spec(_spec)
# Register before exec, exactly as test_catalog_liveness.py must: the module's
# @dataclass resolves its string annotations (PEP 563) through sys.modules,
# which fails if the module is not there yet.
sys.modules["check_action_pins"] = pins
_spec.loader.exec_module(pins)

#: The real v7.0.1 commit, and the invented pin that shipped beside it. Kept
#: adjacent so the shared 16-character prefix -- the reason it looked plausible
#: to a reviewer -- is visible.
REAL_V701 = "60a0d83039c74a4aee543508d2ffcb1c3799cdea"
FABRICATED = "60a0d83039c74a4aa971cc2a0930ae7e2fe2c8bd"


def _write(tmp_path, body: str) -> pathlib.Path:
    (tmp_path / "wf.yml").write_text(body)
    return tmp_path


def _resolver(table):
    """A fake GitHub: (repo, ref) -> (sha, status). Anything absent is MISSING."""

    def resolve(repo, ref, token=None):
        return table.get((repo, ref), (None, pins.MISSING))

    return resolve


class TestParsing:
    def test_reads_repo_ref_and_version_comment(self, tmp_path):
        d = _write(tmp_path, f"      - uses: actions/github-script@{FABRICATED} # v7.0.4\n")
        (use,) = pins.parse_workflows(d)
        assert use.repo == "actions/github-script"
        assert use.ref == FABRICATED
        assert use.comment == "v7.0.4"
        assert use.is_sha

    def test_a_tag_ref_is_not_a_sha(self, tmp_path):
        d = _write(tmp_path, "      - uses: actions/checkout@v7\n")
        (use,) = pins.parse_workflows(d)
        assert use.ref == "v7"
        assert not use.is_sha

    def test_a_subpath_action_keeps_its_owner_repo(self, tmp_path):
        d = _write(tmp_path, "      - uses: owner/repo/sub/action@v1\n")
        (use,) = pins.parse_workflows(d)
        assert use.repo == "owner/repo"

    def test_prose_comments_are_not_version_claims(self, tmp_path):
        """A note beside a pin asserts nothing about which release it is, so
        checking it as a tag would invent a failure."""
        d = _write(tmp_path, "      - uses: actions/checkout@v7 # pinned deliberately\n")
        (use,) = pins.parse_workflows(d)
        assert use.comment is None

    @pytest.mark.parametrize(
        "line",
        [
            "      - uses: ./.github/actions/local\n",
            "      - uses: docker://alpine:3.20\n",
            "      # - uses: actions/checkout@v7\n",
        ],
    )
    def test_local_container_and_commented_refs_are_skipped(self, tmp_path, line):
        assert pins.parse_workflows(_write(tmp_path, line)) == []

    def test_line_numbers_point_at_the_offending_line(self, tmp_path):
        d = _write(tmp_path, "jobs:\n  x:\n    steps:\n      - uses: actions/checkout@v7\n")
        (use,) = pins.parse_workflows(d)
        assert use.line == 4


class TestVerdicts:
    def _use(self, ref, comment=None):
        return pins.Use(repo="actions/github-script", ref=ref, comment=comment, file="wf.yml", line=1)

    def test_a_fabricated_sha_is_a_problem(self, monkeypatch):
        """The regression: the pin that actually shipped."""
        monkeypatch.setattr(pins, "_resolve", _resolver({}))
        (finding,) = pins.audit([self._use(FABRICATED, "v7.0.4")], None)
        assert finding.status == pins.MISSING
        assert finding.is_problem

    def test_a_real_pin_with_a_truthful_comment_is_clean(self):
        """The control. If this reported a problem, every test above could be
        passing for a reason that has nothing to do with the rule."""

        def resolve(repo, ref, token=None):
            return (REAL_V701, pins.OK)

        import unittest.mock

        with unittest.mock.patch.object(pins, "_resolve", resolve):
            (finding,) = pins.audit([self._use(REAL_V701, "v7.0.1")], None)
        assert finding.status == pins.OK
        assert not finding.is_problem

    def test_a_comment_naming_a_tag_that_does_not_exist_is_a_problem(self, monkeypatch):
        """Exactly the shipped case's second half: v7.0.4 was never released."""
        monkeypatch.setattr(
            pins,
            "_resolve",
            _resolver({("actions/github-script", REAL_V701): (REAL_V701, pins.OK)}),
        )
        (finding,) = pins.audit([self._use(REAL_V701, "v7.0.4")], None)
        assert finding.status == pins.MISMATCH
        assert "no such tag" in finding.detail

    def test_a_comment_pointing_at_a_different_commit_is_a_problem(self, monkeypatch):
        """A lying version comment is how a reviewer is walked past a
        supply-chain change: the SHA is real, just not what it claims."""
        other = "3a2844b7e9c422d3c10d287c895573f7108da1b3"
        monkeypatch.setattr(
            pins,
            "_resolve",
            _resolver(
                {
                    ("actions/github-script", REAL_V701): (REAL_V701, pins.OK),
                    ("actions/github-script", "v9.0.0"): (other, pins.OK),
                }
            ),
        )
        (finding,) = pins.audit([self._use(REAL_V701, "v9.0.0")], None)
        assert finding.status == pins.MISMATCH
        assert other in finding.detail

    def test_a_tag_ref_is_not_comment_checked(self, monkeypatch):
        """`@v7 # v7` is not a pin claim -- the ref IS the version."""
        monkeypatch.setattr(pins, "_resolve", _resolver({("actions/github-script", "v7"): ("abc", pins.OK)}))
        (finding,) = pins.audit([self._use("v7", "v7.0.1")], None)
        assert finding.status == pins.OK


class TestUnknownIsNotAFailure:
    """A check that reddens on someone else's outage teaches people to ignore
    it -- and an ignored alarm is the same as no alarm, which is what this
    whole file exists to prevent."""

    def test_a_rate_limit_is_inconclusive_not_a_problem(self, monkeypatch):
        monkeypatch.setattr(pins, "_resolve", lambda repo, ref, token=None: (None, pins.UNKNOWN))
        (finding,) = pins.audit(
            [pins.Use(repo="actions/checkout", ref="v7", comment=None, file="wf.yml", line=1)], None
        )
        assert finding.status == pins.UNKNOWN
        assert not finding.is_problem

    def test_an_unresolvable_ref_is_still_a_problem_when_others_are_unknown(self, monkeypatch):
        """The control for the control: 'inconclusive' must not become a
        blanket amnesty that swallows a real 404."""
        table = {("actions/checkout", "v7"): (None, pins.UNKNOWN)}
        monkeypatch.setattr(pins, "_resolve", _resolver(table))
        findings = pins.audit(
            [
                pins.Use(repo="actions/checkout", ref="v7", comment=None, file="wf.yml", line=1),
                pins.Use(repo="actions/github-script", ref=FABRICATED, comment=None, file="wf.yml", line=2),
            ],
            None,
        )
        assert [f.is_problem for f in findings] == [False, True]


class TestAuditingNothingIsNotHealth:
    def test_a_missing_workflow_dir_exits_2(self, tmp_path, monkeypatch, capsys):
        monkeypatch.setattr("sys.argv", ["x", "--workflow-dir", str(tmp_path / "nope")])
        assert pins.main() == 2

    def test_a_directory_with_no_actions_exits_2(self, tmp_path, monkeypatch):
        (tmp_path / "empty.yml").write_text("jobs:\n  x:\n    steps: []\n")
        monkeypatch.setattr("sys.argv", ["x", "--workflow-dir", str(tmp_path)])
        assert pins.main() == 2, "auditing zero references must never look like a clean bill of health"


class TestTheShippedWorkflowsParse:
    def test_every_workflow_reference_is_readable(self):
        """Not a network test: it only proves the parser still finds this
        repo's own references, so a syntax change cannot silently reduce the
        audit to zero rows while the job stays green."""
        uses = pins.parse_workflows(ROOT / ".github" / "workflows")
        assert len(uses) > 20
        assert all(use.repo.count("/") == 1 for use in uses)


class TestAHalfCheckedPinIsNotVerified:
    """CodeRabbit's catch: the ref resolved, its version claim did not.

    Reporting that as OK would be this script telling exactly the kind of lie
    it exists to catch -- "verified" for something nobody verified. The pin
    that started all this was half-plausible in precisely this way: a real-
    looking SHA beside an unchecked version comment.
    """

    def _use(self):
        return pins.Use(repo="actions/github-script", ref=REAL_V701, comment="v7.0.1", file="wf.yml", line=1)

    def test_an_unresolvable_version_claim_is_unknown_not_ok(self, monkeypatch):
        def resolve(repo, ref, token=None):
            if ref == REAL_V701:
                return (REAL_V701, pins.OK)
            return (None, pins.UNKNOWN)  # the tag lookup got rate limited

        monkeypatch.setattr(pins, "_resolve", resolve)
        (finding,) = pins.audit([self._use()], None)
        assert finding.status == pins.UNKNOWN, "a half-checked pin must not be reported as verified"
        assert not finding.is_problem, "still inconclusive, so it must not redden the run"

    def test_the_control_a_fully_resolved_claim_is_ok(self, monkeypatch):
        """Without this, the assertion above could pass by calling everything
        unknown."""
        monkeypatch.setattr(pins, "_resolve", lambda repo, ref, token=None: (REAL_V701, pins.OK))
        (finding,) = pins.audit([self._use()], None)
        assert finding.status == pins.OK


class TestRealWorldCommentSpellings:
    """Both regressions came from running this against OTHER repos, where it
    reported two correct pins as fabricated. Neither shape exists in CashPilot,
    which is exactly why the happy path could not have caught them."""

    SETUP_BEAM = "54075bcc5e249e4758d363f27d099f55d843f124"

    def test_a_comment_without_the_v_prefix_still_resolves(self, monkeypatch):
        """erlef/setup-beam tags `v1.24.1`; the comment beside the pin says
        `1.24.1`. Resolving only what was written called a correct pin a lie."""
        monkeypatch.setattr(
            pins,
            "_resolve",
            _resolver(
                {
                    ("erlef/setup-beam", self.SETUP_BEAM): (self.SETUP_BEAM, pins.OK),
                    ("erlef/setup-beam", "v1.24.1"): (self.SETUP_BEAM, pins.OK),
                }
            ),
        )
        use = pins.Use(repo="erlef/setup-beam", ref=self.SETUP_BEAM, comment="1.24.1", file="wf.yml", line=1)
        (finding,) = pins.audit([use], None)
        assert finding.status == pins.OK, finding.detail

    def test_a_floating_major_tag_is_not_compared_by_sha(self, monkeypatch):
        """github/codeql-action's `v4` moves; a pin one release behind still
        IS a v4 release, so the comment is true and must not go red."""
        pinned, current_v4 = "8aad20d150bbac5944a9f9d289da16a4b0d87c1e", "5595ccaf912efad79be6eef63a5619ff05969be3"
        monkeypatch.setattr(
            pins,
            "_resolve",
            _resolver(
                {
                    ("github/codeql-action", pinned): (pinned, pins.OK),
                    ("github/codeql-action", "v4"): (current_v4, pins.OK),
                }
            ),
        )
        use = pins.Use(repo="github/codeql-action", ref=pinned, comment="v4", file="wf.yml", line=1)
        (finding,) = pins.audit([use], None)
        assert finding.status == pins.OK, finding.detail

    def test_but_a_floating_tag_that_does_not_exist_is_still_caught(self, monkeypatch):
        """The control: relaxing the SHA comparison must not relax existence."""
        pinned = "8aad20d150bbac5944a9f9d289da16a4b0d87c1e"
        monkeypatch.setattr(pins, "_resolve", _resolver({("github/codeql-action", pinned): (pinned, pins.OK)}))
        use = pins.Use(repo="github/codeql-action", ref=pinned, comment="v99", file="wf.yml", line=1)
        (finding,) = pins.audit([use], None)
        assert finding.status == pins.MISMATCH

    def test_a_full_semver_comment_is_still_compared_by_sha(self, monkeypatch):
        """The other control: vX.Y.Z names one immutable release, so the
        original bug's shape must still be caught."""
        other = "3a2844b7e9c422d3c10d287c895573f7108da1b3"
        monkeypatch.setattr(
            pins,
            "_resolve",
            _resolver(
                {
                    ("actions/github-script", REAL_V701): (REAL_V701, pins.OK),
                    ("actions/github-script", "v9.0.0"): (other, pins.OK),
                }
            ),
        )
        use = pins.Use(repo="actions/github-script", ref=REAL_V701, comment="v9.0.0", file="wf.yml", line=1)
        (finding,) = pins.audit([use], None)
        assert finding.status == pins.MISMATCH
