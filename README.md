# The Catalyst

A personalized AI mentor with living memory, designed to push you toward your North Star goal. The Catalyst learns from every conversation, adapts to your personality, and provides tailored guidance.

### Documentation

| Doc | Purpose |
|-----|---------|
| [AGENTS.md](AGENTS.md) | AI architecture, memory system, tools, resilience |
| [skills.md](skills.md) | Root agent playbook and dev commands |
| [docs/RESILIENCE.md](docs/RESILIENCE.md) | Rate limiting, retry, and fallback details |
| [docs/ROADMAP.md](docs/ROADMAP.md) | Planned features |
| [backend/skills.md](backend/skills.md) | Backend conventions |
| [frontend/skills.md](frontend/skills.md) | Frontend conventions |
| [tests/skills.md](tests/skills.md) | Testing conventions |

## Features

- **Adaptive AI mentor** — Tough Coach, Wise Strategist, and Guardian modes
- **Living memory** — Short-term conversation context + long-term profile synthesis
- **Daily rituals** — Morning ignition and evening reflection sessions
- **Goal tracking** — North Star + sub-goal hierarchy; edit via Goals modal (`POST/PUT /goals`)
- **Momentum stats** — Streaks, ritual calendar, energy/focus trends, wins, and insights (Stats modal)
- **Settings** — Read-only mentor memory (LTM) and API quota status
- **Markdown UI** — Chat, panels, and LTM sections render markdown via `marked` + DOMPurify
- **Function calling** — AI tools update memory, logs, and session streaks
- **Resilient LLM layer** — CLOD primary (`GPT OSS 120B`), Gemini fallback via LiteLLM

## Setup

### Prerequisites

- Python 3.11+
- [CLOD API key](https://clod.io) (primary)
- Optional: [Gemini API key](https://aistudio.google.com/app/apikey) for fallback only

### Quick start

```bash
git clone <your-repo-url>
cd TheCatalyst
python -m venv venv

# Windows
.\venv\Scripts\Activate.ps1
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # or cp on Unix
```

Edit `.env` — set `CLOD_API_KEY` at minimum.

**Run everything** (backend + frontend):

```bash
python app.py
```

**Backend only:**

```bash
uvicorn backend.app:app --reload --host 0.0.0.0 --port 8000
```

## Project structure

```
TheCatalyst/
├── app.py                    # Entry: uvicorn + local frontend server
├── setup.py                  # First-run helper
├── requirements.txt
├── pytest.ini
├── docs/
│   ├── RESILIENCE.md         # Rate limits & retry reference
│   └── ROADMAP.md            # Future work
├── scripts/
│   ├── demo_rate_limiting.py
│   └── demo_retry_logic.py
├── backend/
│   ├── app.py                # FastAPI factory (CORS, lifespan)
│   ├── routers/              # Route modules by domain
│   │   ├── chat.py           # /initialize, /chat, /initial-greeting
│   │   ├── conversations.py
│   │   ├── goals.py
│   │   ├── memory.py         # profile, logs, insights, stats
│   │   └── system.py         # /health, /rate-limit-status
│   ├── catalyst_ai.py        # Prompts, tool loop, retry
│   ├── llm_client.py         # LiteLLM → CLOD / Gemini
│   ├── conversation.py       # Transcript & context helpers
│   ├── config.py
│   ├── database.py
│   ├── functions.py          # Tool registry
│   ├── memory_manager.py
│   ├── models.py
│   ├── rate_limiter.py
│   ├── schemas.py
│   └── time_utils.py
├── frontend/
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── experimental/         # Unintegrated UI prototypes
├── prompts/
│   └── system_prompt.md
├── tests/
└── data/                     # SQLite (gitignored)
```

## Database backups

On every `python app.py` start, the live SQLite file is copied to `data/backups/` (newest 5 kept).

```bash
python app.py backup                  # manual backup without starting servers
python app.py restore --list          # list backups (newest first)
python app.py restore --latest        # restore most recent backup
python app.py restore --index 2       # restore by list index
python app.py restore --file PATH     # restore a specific file
python app.py restore --latest --yes  # skip confirmation
```

Stop the running server before restoring.

## Configuration

```bash
CLOD_API_KEY=your_clod_api_key
GEMINI_API_KEY=your_gemini_key          # optional fallback
MODEL_NAME=GPT OSS 120B
ALT_MODEL_NAME=gemini-2.5-flash
SHOW_THINKING=false
```

Rate limit overrides: `GPT_OSS_120B_RPD=100`, `GEMINI_2_5_FLASH_RPM=10`, etc. See [docs/RESILIENCE.md](docs/RESILIENCE.md).

## API endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/` | Status and model name |
| POST | `/initialize` | First-time North Star setup (409 if goals already exist) |
| POST | `/initial-greeting` | Session greeting |
| POST | `/chat` | Main chat |
| GET | `/goals` | Active goal hierarchy (`north_star` = rank 1) |
| POST | `/goals` | Add a sub-goal (`rank` default 2) |
| PUT | `/goals/{id}` | Update description, metric, timeline, rank, or `is_active` |
| GET | `/memory/profile` | LTM snapshot |
| GET | `/logs/recent?days=30` | Daily log rows for trends |
| GET | `/insights?limit=10` | Stored insights |
| GET | `/stats` | Streak, sessions, 30-day completion and energy/focus averages |
| GET | `/health` | System health |
| GET | `/rate-limit-status` | Per-model quota status for UI |

## Testing

```bash
.\venv\Scripts\python.exe -m pytest tests/ --ignore=tests/test_rate_limiter.py -q
```

Full suite including rate limiter (~3 min): omit `--ignore`.

## Troubleshooting

- **Connection error** — Check `CLOD_API_KEY` in `.env`
- **Fallback to Gemini** — Set `GEMINI_API_KEY` if CLOD is down
- **Reset database** — Delete `data/catalyst.db`

---

_"The Catalyst isn't just software — it's your partner in transformation."_
