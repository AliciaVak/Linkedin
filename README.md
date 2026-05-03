# LinkedIn Connection Agent

An AI-powered LinkedIn connection agent. Claude acts as the brain — it searches target companies, decides whether people match your criteria using language understanding, and sends connection requests. All browser automation runs through your real Chrome session to avoid LinkedIn bot detection.

---

## How it works

```
You / Scheduler
      ↓
Orchestrator (Claude claude-sonnet-4-6)
      ↓  reasons + calls tools
 ┌────┴─────────────────────────────────┐
 │  SearchSkill    → find people        │
 │  ConnectSkill   → send requests      │
 │  ReportingSkill → stats + CSV email  │
 │  SchedulerSkill → manage schedule    │
 └──────────────────────────────────────┘
      ↓
 Chrome (your real browser via CDP)
 SQLite (connection history)
```

Claude decides who matches your criteria using language understanding — "VP of Sales" and "Vice President, Sales" both match "VP Sales". You can also talk to it directly in chat mode.

---

## Setup

### 1. Install dependencies

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env`:

| Variable | Required | Description |
|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | Your Anthropic API key |
| `CONNECTION_HOUR` | optional | Hour to run daily (default: `8`) |
| `CONNECTION_MINUTE` | optional | Minute to run daily (default: `0`) |
| `TIMEZONE` | optional | Timezone string (default: `Asia/Jerusalem`) |
| `SMTP_HOST` | optional | SMTP server for email reports |
| `SMTP_PORT` | optional | SMTP port (default: `587`) |
| `SMTP_USER` | optional | SMTP login email |
| `SMTP_PASSWORD` | optional | SMTP password or app password |
| `REPORT_EMAIL` | optional | Where to send the daily CSV report |

> For Gmail, generate an App Password at [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords).

### 3. Configure your targets

Edit `criteria.json`:

```json
{
  "daily_limit": 10,
  "job_titles": ["VP Sales", "CRO", "Chief Revenue Officer", "Head of Sales"],
  "companies": ["Guidde", "Braintrust", "ClickHouse"],
  "company_slugs": {
    "Guidde": "guidde",
    "Braintrust": "braintrust-data",
    "ClickHouse": "clickhouseinc"
  }
}
```

| Field | Description |
|---|---|
| `daily_limit` | Max connections to send per day |
| `job_titles` | Target roles — Claude matches flexibly (e.g. "VP of Sales" matches "VP Sales") |
| `companies` | Target company names |
| `company_slugs` | LinkedIn URL slugs per company — avoids guessing. Find at `linkedin.com/company/<slug>` or export from Apollo |

### 4. Launch Chrome with remote debugging

The agent connects to **your real Chrome** to avoid LinkedIn bot detection. Run this once and keep it open:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir=/tmp/chrome-linkedin
```

Log into LinkedIn in that Chrome window.

---

## Running

```bash
source .venv/bin/activate

# Start the daily scheduler (fires automatically at configured time)
python3 main.py

# Talk to the agent interactively
python3 main.py chat

# Trigger one run immediately and exit
python3 main.py run
```

---

## Chat mode

In chat mode you can talk to the agent naturally:

```
You: search VP Sales at Guidde
You: connect with Graham Rowe
You: how many connections did we make today?
You: set schedule to 9am
You: pause for 3 days
You: run the pipeline now
You: which companies are exhausted?
```

Claude will use the appropriate tools, evaluate results using its own judgment, and report back. Type `reset` to clear conversation history, `quit` to exit.

---

## Project structure

```
criteria.json           ← your target companies and job titles
connections.db          ← SQLite history (auto-created)
exports/                ← daily CSV exports (auto-created)

skills/
  browser_manager.py    ← owns the Chrome CDP connection (shared across skills)
  search_skill.py       ← search_people tool
  connect_skill.py      ← connect_with_person / connect_with_people tools
  reporting_skill.py    ← get_connection_status + CSV export/email
  scheduler_skill.py    ← set/pause/cancel/get schedule + run_now
  _playwright.py        ← raw Playwright browser mechanics

agent/
  orchestrator.py       ← Claude tool-use loop, conversation history

db/
  connections_db.py     ← SQLite wrapper (history, exhausted companies)

integrations/
  email_sender.py       ← SMTP email sender
```

---

## Adding new skills

1. Create `skills/my_skill.py` extending `BaseSkill`
2. Implement `get_tools()`, `handle()`, and optionally `cleanup()`
3. Add it to `_build_orchestrator()` in `main.py`

Claude automatically gains access to the new tools — no other changes needed.
