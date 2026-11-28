# Nightly translation sync

When an English string or docs page changes on main, this job translates the change into the other 19 languages by the next morning. It runs every night at 03:30 on MacMini, as the LaunchAgent `local.cashpilot-i18n-sync`. It opens one ready PR per repo from the Amigadelasmigas fork, and a person merges it.

It covers the web UI (`app/i18n/`), the service catalog (`services/_i18n/`) and the docs (`docs/i18n/`) here, CashPilot-Desktop (`frontend/src/locales/`), CashPilot-android (`strings.xml` and the Play listing) and CashPilot-web (`src/i18n/`). For each repo, `sync.py` does this:

1. It fetches main and runs the repo's own i18n checks and a placeholder check. If one fails, it translates nothing and logs why.
2. It finds the translations whose stored source hash no longer matches the English, and the keys that a locale lacks. A locale that lacks more than 40 keys is a backlog for a translation lane, so the job leaves those keys alone. In the docs it finds the stale pages only.
3. It asks Claude (opus, through `nd run`) for those entries only. The prompt holds the glossary (`i18n/glossary.yml`), the old and the new English, and the current translations.
4. It runs the checks again. If they pass, it pushes `i18n-sync/<date>` with `git-amiga` and opens the PR with `gh-amiga`. If they fail, the branch stays unpushed in the clone, and the log says why.

It uses only the neutralbase and neutralstate Claude Code seats: `cc-neutralagent1` to `cc-neutralagent7`, `cc-neutralstack` and `cc-ns-admin`, `-diego`, `-lucas`, `-mateo` and `-sara` (`SEATS` in `sync.py`). Before the first repo it reads `nd usage json` and skips a seat that shows 0% weekly left, the status `rejected`, or rate-limited model windows, because such a seat fails at once. It starts with the seat that has the most weekly room. If no seat has room, it logs that and stops with exit code 0, and translates nothing. `I18N_SYNC_ACCOUNTS=a,b` narrows the list for a manual run; a seat outside `SEATS` is skipped.

The job never runs on GitHub's runners, and no Claude token goes into a GitHub secret. While a sync PR is open in a repo, the job skips that repo.

Install on MacMini, once:

```sh
R=/Volumes/Data/scratch/i18n-sync
mkdir -p $R && cp scripts/i18n-sync/run.sh $R/run.sh
cp scripts/i18n-sync/local.cashpilot-i18n-sync.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/local.cashpilot-i18n-sync.plist
```

`run.sh` takes the job's code from main before each run. Logs go to `$R/logs/i18n-sync.log`. To run it by hand: `bash $R/run.sh --dry-run`, or `--repo CashPilot-Desktop --base <branch> --base-remote amiga --no-push` to try a branch on the fork.
