#!/usr/bin/env bash
# run_weekly.sh
# Convenience wrapper for OS-level scheduling (cron/launchd on Mac/Linux).
# Runs the automation agent once and exits — the actual "weekly" part is
# the schedule you set up in cron, not this script. See README.md >
# "Scheduling" for the crontab line and Windows Task Scheduler equivalent.
#
# Edit the paths/values below to match your setup, then point cron at
# THIS script rather than at automation_runner.py directly — it handles
# activating the virtualenv and loading your Telegram credentials so your
# crontab entry stays a one-liner.

set -euo pipefail
cd "$(dirname "$0")/.."   # project root

# activate the virtualenv if you're using one (uncomment + adjust path)
# source .venv/bin/activate

# Telegram credentials — either hardcode here or leave commented and set
# them as real environment variables in your shell profile / cron env
# export TELEGRAM_TOKEN="123456789:AA..."
# export TELEGRAM_CHAT_ID="999888777"

python3 -m scripts.automation_runner \
  --watch-dir "data/incoming" \
  --configs-dir "configs" \
  --output-dir "output" \
  --once
