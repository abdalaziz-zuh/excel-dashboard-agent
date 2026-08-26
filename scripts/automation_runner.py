"""
automation_runner.py
CLI for the automation agent. Two modes:

    python -m scripts.automation_runner --watch-dir data/incoming --once
        Processes every .xlsx currently in watch-dir once, then exits.
        Good for testing and for cron-style scheduled runs.

    python -m scripts.automation_runner --watch-dir data/incoming
        Runs continuously, processing new .xlsx files as they're dropped in
        (via watchdog). Ctrl+C to stop.

State tracking: processed files are recorded in <watch-dir>/.processed.json
(same pattern as seen_jobs.json in the job-search-automation project) so a
restart doesn't reprocess everything, and a file with no matching saved
template is moved to <watch-dir>/needs_review/ instead of silently skipped
forever.
"""

import argparse
import json
import os
import shutil
import time
from pathlib import Path

from src.excel_parser import profile_excel
from src.agents import automation_agent
from src.orchestrator import run_pipeline
from src.exporter import export_html


def _load_state(watch_dir: Path) -> dict:
    state_file = watch_dir / ".processed.json"
    if state_file.exists():
        return json.loads(state_file.read_text())
    return {"processed": []}


def _save_state(watch_dir: Path, state: dict):
    (watch_dir / ".processed.json").write_text(json.dumps(state, indent=2))


def process_one_file(file_path: Path, configs_dir: str, output_dir: Path) -> dict:
    profile = profile_excel(str(file_path))
    match = automation_agent.find_matching_config(profile, configs_dir)

    if not match:
        return {"status": "no_match", "file": file_path.name}

    remapped = automation_agent.remap_config(match["config"], match["mapping"])
    if not remapped["selected_attributes"]:
        return {"status": "no_match", "file": file_path.name, "reason": "all columns dropped by schema drift"}

    result = run_pipeline(
        profile,
        remapped["selected_attributes"],
        remapped["chart_overrides"],
        remapped["design_skill_id"],
        remapped["pairs"],
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / f"{file_path.stem}_dashboard.html"
    export_html(result, result["profile"], str(out_path), title=f"{match['config']['template_name']} — {file_path.stem}")

    return {
        "status": "processed",
        "file": file_path.name,
        "template": match["config"]["template_name"],
        "match_type": match["match_type"],
        "coverage": round(match["coverage"], 2),
        "dropped_columns": remapped["dropped_columns"],
        "qa_score": result["final_score"],
        "output": str(out_path),
    }


def run_once(watch_dir: str, configs_dir: str, output_dir: str) -> dict:
    """Returns {"processed": [...], "no_match": [...], "errors": [...]} so the
    caller (CLI or a future scheduler) can decide what to do with the summary
    — e.g. send a Telegram notification only when something actually happened."""
    watch_path = Path(watch_dir)
    output_path = Path(output_dir)
    needs_review = watch_path / "needs_review"
    state = _load_state(watch_path)

    summary = {"processed": [], "no_match": [], "errors": []}

    xlsx_files = [f for f in watch_path.glob("*.xlsx") if f.name not in state["processed"]]
    if not xlsx_files:
        print("No new files to process.")
        return summary

    for f in xlsx_files:
        print(f"Processing {f.name}...")
        try:
            result = process_one_file(f, configs_dir, output_path)
        except Exception as e:
            print(f"  ERROR: {e}")
            summary["errors"].append({"file": f.name, "error": str(e)})
            continue

        if result["status"] == "no_match":
            needs_review.mkdir(exist_ok=True)
            shutil.move(str(f), needs_review / f.name)
            print(f"  No matching template — moved to needs_review/ ({result.get('reason', 'no schema match')})")
            summary["no_match"].append(result)
        else:
            print(f"  Matched template '{result['template']}' ({result['match_type']}, "
                  f"{result['coverage']*100:.0f}% coverage) — QA score {result['qa_score']}/100")
            if result["dropped_columns"]:
                print(f"  Dropped columns (not found in new file): {result['dropped_columns']}")
            print(f"  Saved: {result['output']}")
            summary["processed"].append(result)

        state["processed"].append(f.name)
        _save_state(watch_path, state)

    return summary


def _build_notification_text(summary: dict) -> str:
    lines = [f"*Signal automation run* — {time.strftime('%Y-%m-%d %H:%M')}"]
    if summary["processed"]:
        lines.append(f"\n✅ *{len(summary['processed'])} processed:*")
        for r in summary["processed"]:
            lines.append(f"  • {r['file']} → {r['template']} (score {r['qa_score']}/100)")
    if summary["no_match"]:
        lines.append(f"\n⚠️ *{len(summary['no_match'])} needs review:*")
        for r in summary["no_match"]:
            lines.append(f"  • {r['file']}")
    if summary["errors"]:
        lines.append(f"\n❌ *{len(summary['errors'])} error(s):*")
        for r in summary["errors"]:
            lines.append(f"  • {r['file']}: {r['error']}")
    return "\n".join(lines)


def maybe_notify(summary: dict, telegram_token: str | None, telegram_chat_id: str | None, api_base: str | None = None):
    """Only sends a message when something actually happened — an empty
    cycle (nothing new in the folder) stays silent so a scheduled run
    doesn't spam the chat every time it finds nothing."""
    if not telegram_token or not telegram_chat_id:
        return
    if not (summary["processed"] or summary["no_match"] or summary["errors"]):
        return
    try:
        from src.notifier import send_telegram_message, API_BASE
        send_telegram_message(telegram_token, telegram_chat_id, _build_notification_text(summary), api_base or API_BASE)
        print("Telegram notification sent.")
    except Exception as e:
        print(f"Telegram notification failed (run itself still succeeded): {e}")


def run_watch(watch_dir: str, configs_dir: str, output_dir: str, poll_seconds: int = 5,
              telegram_token: str | None = None, telegram_chat_id: str | None = None):
    print(f"Watching {watch_dir} for new .xlsx files (Ctrl+C to stop)...")
    try:
        while True:
            summary = run_once(watch_dir, configs_dir, output_dir)
            maybe_notify(summary, telegram_token, telegram_chat_id)
            time.sleep(poll_seconds)
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Automation agent — auto-apply saved dashboard templates to new Excel files.")
    parser.add_argument("--watch-dir", required=True, help="Folder to watch for new .xlsx files")
    parser.add_argument("--configs-dir", default="configs", help="Folder where saved templates (from the app's 'Save as template' button) live")
    parser.add_argument("--output-dir", default="output", help="Folder to write generated dashboard HTML files to")
    parser.add_argument("--once", action="store_true", help="Process current files once and exit, instead of watching continuously")
    parser.add_argument("--poll-seconds", type=int, default=5, help="Polling interval in watch mode")
    parser.add_argument("--telegram-token", default=os.environ.get("TELEGRAM_TOKEN"), help="Bot token from @BotFather (or set TELEGRAM_TOKEN env var)")
    parser.add_argument("--telegram-chat-id", default=os.environ.get("TELEGRAM_CHAT_ID"), help="Your chat id (or set TELEGRAM_CHAT_ID env var) — see src/notifier.py for how to find it")
    args = parser.parse_args()

    if args.once:
        summary = run_once(args.watch_dir, args.configs_dir, args.output_dir)
        maybe_notify(summary, args.telegram_token, args.telegram_chat_id)
    else:
        run_watch(args.watch_dir, args.configs_dir, args.output_dir, args.poll_seconds,
                   args.telegram_token, args.telegram_chat_id)
