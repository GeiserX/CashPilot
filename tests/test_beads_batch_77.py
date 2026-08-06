"""CashPilot-ixjx: the suite refuses to run against a contaminated tree.

These repos are two-way rsynced against a hub that keeps files the local side
deleted (no ``--delete``, deliberately). A branch checkout removes a file; the
next sync copies it back as an UNTRACKED stray, and the tree then holds a
mixture of two branches.

THE FAILING CASE IS THE LUCKY ONE. When it bit on 2026-08-06, five tests failed
loudly — but an earlier run on the same branch had reported **4096 passed**
while silently including another branch's tests. A green suite measuring the
wrong tree announces nothing, and nobody re-checks a pass.

The classification these tests pin down:

    untracked + has commit history  -> a stray, refuse to run
    untracked + no history          -> ordinary new work, ignore
    outside app|tests|scripts|services -> not our business either way

The middle case matters most: every new test file is untracked before it is
committed, so a guard that blocked on those would be turned off within a day.
"""

from __future__ import annotations

import pytest

from tests import conftest as ct


@pytest.fixture
def fake_git(monkeypatch):
    """Drive the real find_stray_files() against scripted git output.

    Patching ``_git`` rather than building a temp repository keeps the CLASSIFY
    logic under test — which is where the bugs live — instead of testing git.
    """

    def install(status: str, with_history: set[str]):
        def _fake(*args: str):
            if args[0] == "status":
                return status
            if args[0] == "rev-list":
                path = args[-1]
                return "9490fc3\n" if path in with_history else ""
            return ""

        monkeypatch.setattr(ct, "_git", _fake)

    return install


class TestWhatCountsAsAStray:
    def test_an_untracked_file_with_history_is_a_stray(self, fake_git):
        fake_git("?? app/federation.py\n", {"app/federation.py"})
        assert ct.find_stray_files() == ["app/federation.py"]

    def test_an_untracked_file_with_NO_history_is_ordinary_new_work(self, fake_git):
        """The case that decides whether anyone leaves this guard enabled: a new
        test file is untracked until it is committed."""
        fake_git("?? tests/test_brand_new.py\n", set())
        assert ct.find_stray_files() == []

    def test_a_modified_tracked_file_is_not_a_stray(self, fake_git):
        """Only '??' lines. A modified file is your own work in progress."""
        fake_git(" M app/main.py\n", {"app/main.py"})
        assert ct.find_stray_files() == []

    def test_a_staged_file_is_not_a_stray(self, fake_git):
        fake_git("A  app/new_thing.py\n", {"app/new_thing.py"})
        assert ct.find_stray_files() == []

    @pytest.mark.parametrize("path", ["NOTES.md", "docs/scratch.md", ".env.local"])
    def test_files_outside_the_result_bearing_dirs_are_ignored(self, fake_git, path):
        """A stray note cannot change what the suite measures."""
        fake_git(f"?? {path}\n", {path})
        assert ct.find_stray_files() == []

    @pytest.mark.parametrize("path", ["app/x.py", "tests/x.py", "scripts/x.mjs", "services/bandwidth/x.yml"])
    def test_every_result_bearing_directory_is_covered(self, fake_git, path):
        fake_git(f"?? {path}\n", {path})
        assert ct.find_stray_files() == [path]

    def test_a_quoted_path_is_unquoted(self, fake_git):
        """git quotes paths containing spaces; an un-stripped quote would never
        match the history lookup and the stray would slip through."""
        fake_git('?? "app/with space.py"\n', {"app/with space.py"})
        assert ct.find_stray_files() == ["app/with space.py"]

    def test_several_strays_are_all_reported(self, fake_git):
        fake_git("?? app/a.py\n?? tests/b.py\n?? NOTES.md\n", {"app/a.py", "tests/b.py", "NOTES.md"})
        assert ct.find_stray_files() == ["app/a.py", "tests/b.py"]


class TestTheGuardNeverBlocksTheSuiteByAccident:
    def test_it_returns_nothing_when_git_is_unavailable(self, monkeypatch):
        """Not a repository, no git binary, a timeout -- the guard must never be
        the reason a suite cannot run, only a reason it refuses to lie."""
        monkeypatch.setattr(ct, "_git", lambda *a: None)
        assert ct.find_stray_files() == []

    def test_a_clean_tree_yields_nothing(self, fake_git):
        """CONTROL. If find_stray_files() always returned [], every assertion in
        the class above would pass for the wrong reason."""
        fake_git("", set())
        assert ct.find_stray_files() == []

    def test_control_the_detector_can_actually_return_something(self, fake_git):
        fake_git("?? app/federation.py\n", {"app/federation.py"})
        assert ct.find_stray_files(), "the detector never fires; the clean-tree test proves nothing"
