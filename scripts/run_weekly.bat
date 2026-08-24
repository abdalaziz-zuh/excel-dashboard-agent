@echo off
REM run_weekly.bat
REM Convenience wrapper for Windows Task Scheduler. See README.md >
REM "Scheduling" for how to point a scheduled task at this file.
REM Edit the paths below to match your setup.

cd /d "%~dp0\.."

REM activate the virtualenv if you're using one (uncomment + adjust path)
REM call .venv\Scripts\activate.bat

REM Telegram credentials — either set here or as real Windows environment variables
REM set TELEGRAM_TOKEN=123456789:AA...
REM set TELEGRAM_CHAT_ID=999888777

python -m scripts.automation_runner --watch-dir "data\incoming" --configs-dir "configs" --output-dir "output" --once
