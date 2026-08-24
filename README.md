# AI-Powered Dashboard Generator

Upload an Excel file → get a dashboard built, reviewed, and fixed by three
cooperating agents, plus a plain-language report on what to look at.

## Architecture

```
Excel upload
    │
    ▼
excel_parser.py  ──► infers a SEMANTIC type per column (not just pandas dtype):
                      numeric_continuous / numeric_discrete / datetime /
                      categorical_low / categorical_high / boolean / text

    │
    ▼
┌─────────────────────────── build ↔ check loop ───────────────────────────┐
│                                                                            │
│  Agent 1 — design_agent.py ("Builder")                                    │
│    • picks a chart type per attribute (rule-based default from            │
│      chart_rules.py, or the user's manual override)                       │
│    • picks a design skill (theme) from src/design_skills/*.json,          │
│      rotating away from the last one used so repeat runs don't look       │
│      identical                                                            │
│                                                                            │
│         ▼                                                                 │
│  Agent 2 — qa_agent.py ("Reviewer")                                       │
│    • scores the spec 0-100 against an explicit rubric: chart-type         │
│      correctness, category overload (e.g. pie with 50 slices), missing    │
│      titles, high-null columns                                            │
│    • returns a structured issue list, not a vague opinion                 │
│                                                                            │
│         │ score < 90 and iterations < 4                                   │
│         ▼                                                                 │
│  Agent 1.fix_issues() patches the flagged tiles → back to Agent 2         │
│                                                                            │
└─────────────────────────── stops when: score ≥ 90, OR 4 iterations ──────┘
    │
    ▼
Agent 3 — report_agent.py ("Reporter")
    • summarizes what was auto-fixed and what's still unresolved
    • surfaces real data-quality insights (nulls, likely-ID columns,
      value ranges) — via Groq LLM if GROQ_API_KEY is set, otherwise a
      template fallback so the app still works with zero API cost
    │
    ▼
app.py (Streamlit) renders the charts + report
```

## Why chart-type correctness is NOT an LLM call

Whether a pie chart fits a column with 200 unique values is a solved,
deterministic question — it doesn't need an LLM's opinion, and an LLM can
give a different answer each run. `chart_rules.py` encodes this as a
lookup table instead, which makes the QA score reproducible and lets the
build↔check loop actually converge instead of oscillating.

The LLM (Groq, optional) is reserved for genuinely subjective work: writing
plain-language data-insight callouts in the final report.

## Loop safety nets

- **Hard cap**: `MAX_ITERATIONS = 4` in `orchestrator.py` — no infinite loop.
- **Best-so-far tracking**: if a fix pass makes the score *worse* (Agent 1
  breaks something new while fixing something else), the orchestrator keeps
  the best-scoring version seen across all iterations rather than shipping
  a regression.

## Running it

```bash
pip install -r requirements.txt
export GROQ_API_KEY=your_key_here   # optional — app works without it
streamlit run app.py
```

## What's built

- **Agent 1 (Builder)** — `src/agents/design_agent.py`
- **Agent 2 (Reviewer)** — `src/agents/qa_agent.py`
- **Agent 3 (Reporter)** — `src/agents/report_agent.py`
- **Automation agent (Repeater)** — `src/agents/automation_agent.py` + `scripts/automation_runner.py`
  - Save any built dashboard as a named template (schema + selections) from
    the app's "Save as template" button.
  - `python -m scripts.automation_runner --watch-dir <folder> --once`
    applies the matching template to every new `.xlsx` dropped in that
    folder — exact schema match first, fuzzy name+type matching as a
    fallback for renamed/reordered columns, dropped-column reporting when
    schema drift removes something. Files with no matching template land
    in `<folder>/needs_review/` instead of being silently skipped.
  - Drop `--once` to run continuously (polls every 5s, Ctrl+C to stop).
  - Output: a self-contained `*_dashboard.html` per file (`src/exporter.py`)
    — no server needed to view it.

## Telegram notifications

The automation agent can message you a summary (processed / needs-review /
errors) after each run — stays silent when there's nothing new, so a
scheduled run doesn't spam you.

1. In Telegram, message **@BotFather**, send `/newbot`, follow the prompts.
   You'll get a token like `123456789:AAH...`.
2. Message your new bot anything at all (a bot can't message you first),
   then open `https://api.telegram.org/bot<TOKEN>/getUpdates` in a browser
   — your chat id is the number in `"chat":{"id": ...}`.
3. Run with:
   ```bash
   python -m scripts.automation_runner --watch-dir data/incoming --once \
     --telegram-token 123456789:AAH... --telegram-chat-id 999888777
   ```
   or set `TELEGRAM_TOKEN` / `TELEGRAM_CHAT_ID` as environment variables
   and drop the flags.

## Scheduling

`automation_runner.py --once` processes what's currently in the folder and
exits — it does NOT stay running in the background. For a real "check
every week" setup, let your OS's scheduler run it, rather than leaving a
Python process running for a week (fragile: laptop sleeps, process dies
silently, nobody notices).

**Mac/Linux (cron):** edit `scripts/run_weekly.sh` with your paths and
Telegram credentials, then:
```bash
crontab -e
# add this line to run every Monday at 9am:
0 9 * * 1 /full/path/to/excel-dashboard-agent/scripts/run_weekly.sh >> /tmp/dashboard-agent.log 2>&1
```

**Windows (Task Scheduler):** edit `scripts/run_weekly.bat` with your
paths, then Task Scheduler → Create Task → Trigger: Weekly → Action:
Start a program → point it at `run_weekly.bat`.

Either way, `--once` is what makes this safe to schedule — each run does
exactly one pass and exits cleanly.

## What's next

- Real Groq calls for design-skill selection (currently rule-based
  rotation — fine for the MVP, a good next upgrade).
- Deploy to Streamlit Community Cloud for a live link.
