#!/bin/bash
# The launchd entry of the nightly translation sync (local.cashpilot-i18n-sync.plist).
# It takes the job's code from CashPilot main, so a merged change to scripts/i18n-sync/
# runs the next night. Before the first merge it runs the copy already in job/.
set -uo pipefail
ROOT=${I18N_SYNC_ROOT:-/Volumes/Data/scratch/i18n-sync}
export I18N_SYNC_ROOT=$ROOT
export PATH="$ROOT/venv/bin:$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
unset GITHUB_TOKEN GH_TOKEN
mkdir -p "$ROOT/logs" "$ROOT/repos" "$ROOT/job"
echo "=== $(date '+%F %T') run.sh start"

CP="$ROOT/repos/CashPilot"
[ -d "$CP" ] || git clone -q https://github.com/GeiserX/CashPilot.git "$CP"
git -C "$CP" remote get-url amiga >/dev/null 2>&1 || git -C "$CP" remote add amiga https://github.com/Amigadelasmigas/CashPilot.git
if git -C "$CP" fetch -q origin main && git -C "$CP" cat-file -e origin/main:scripts/i18n-sync/sync.py 2>/dev/null; then
  rm -rf "$ROOT/job.new" && mkdir -p "$ROOT/job.new"
  git -C "$CP" archive origin/main scripts/i18n-sync scripts/i18n_check.py i18n/glossary.yml | tar -x -C "$ROOT/job.new" &&
    rm -rf "$ROOT/job" && mv "$ROOT/job.new" "$ROOT/job"
fi

# Python-Markdown for the docs check's heading ids, at the version Zensical pins.
# .ready marks a finished install, so a failed one is tried again the next night.
if [ ! -f "$ROOT/venv/.ready" ]; then
  if python3 -m venv "$ROOT/venv" && "$ROOT/venv/bin/pip" install -q -r "$CP/docs/requirements-docs.txt"; then
    touch "$ROOT/venv/.ready"
  else
    echo "=== $(date '+%F %T') run.sh: installing the docs dependencies failed; nothing ran"
    exit 1
  fi
fi

"$ROOT/venv/bin/python3" -I "$ROOT/job/scripts/i18n-sync/sync.py" "$@"
rc=$?
echo "=== $(date '+%F %T') run.sh end rc=$rc"
exit $rc
