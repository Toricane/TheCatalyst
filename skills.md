# The Catalyst - Skills Playbook (`skills.md`)

This is the project-level instruction manual (playbook) for AI coding agents (e.g., Cursor, Gemini, Claude) working on **The Catalyst**. It defines the architecture, folder layout, commands, safety constraints, and coding rules.

---

## 🧭 System Documentation Index & Handoffs

Before modifying any code, review this map to determine which reference file is relevant to your task:

* **Look at [skills.md](skills.md) (This File)**:
  - When starting a new chat session to ground yourself in general project guidelines.
  - When reviewing global conventions, project commands, or the **Self-Improving Skill** workflow.
* **Look at [AGENTS.md](AGENTS.md)**:
  - When studying the internal AI mentor's persona, mindset stack, or communication modes.
  - When debugging how the backend interacts with LiteLLM (CLOD/Gemini) or executes tools.
  - When reviewing SQLite schema fields, streaks updates, or memory synthesis logic.
* **Look at [backend/skills.md](backend/skills.md)**:
  - When modifying FastAPI routes, database models, time utilities, or prompt builders.
* **Look at [frontend/skills.md](frontend/skills.md)**:
  - When updating CSS, editing html templates, or integrating the rate limiter status UI.
* **Look at [docs/RESILIENCE.md](docs/RESILIENCE.md)**:
  - When changing rate limits, retry behavior, or fallback logic.
* **Look at [docs/ROADMAP.md](docs/ROADMAP.md)**:
  - When scoping future features.
* **Look at [tests/skills.md](tests/skills.md)**:
  - When writing test fixtures, running pytests, or verifying changes before commit.

---

## 1. Project Overview

**The Catalyst** is an adaptive, personalized growth mentor application. It conducts structured morning and evening chat sessions, maintains an evolving long-term personality profile of the user, logs daily highlights (wins, challenges, gratitude), and helps keep focus on a single North Star goal.

---

## 2. Tech Stack

- **Backend**: Python 3.13, FastAPI, Uvicorn, SQLAlchemy (SQLite database).
- **Frontend**: HTML5, Vanilla CSS, Vanilla Javascript (ES6).
- **AI Engine**: LiteLLM — CLOD primary (`GPT OSS 120B` at `api.clod.io/v1`), Gemini fallback.
- **Testing**: Pytest.

---

## 3. Folder Structure Map

- [`backend/`](backend/): FastAPI application.
  - [`backend/app.py`](backend/app.py): App factory (CORS, lifespan, router registration).
  - [`backend/routers/`](backend/routers/): Route modules (`chat`, `conversations`, `goals`, `memory`, `system`).
  - [`backend/catalyst_ai.py`](backend/catalyst_ai.py): LiteLLM orchestration, prompts, tool loop, retry.
  - [`backend/llm_client.py`](backend/llm_client.py): CLOD / Gemini routing.
  - [`backend/conversation.py`](backend/conversation.py): Transcript, export, and context helpers.
  - [`backend/dependencies.py`](backend/dependencies.py): FastAPI `get_db`.
  - [`backend/database.py`](backend/database.py): SQLite engine and sessions.
  - [`backend/functions.py`](backend/functions.py): Tool registry.
  - [`backend/memory_manager.py`](backend/memory_manager.py): LTM queries and missed-session logic.
  - [`backend/rate_limiter.py`](backend/rate_limiter.py): Async quota limiter.
- [`frontend/`](frontend/): Static chat UI (`index.html`, `app.js`, `style.css`).
  - [`frontend/experimental/`](frontend/experimental/): Unintegrated rate-limit UI prototype.
- [`prompts/system_prompt.md`](prompts/system_prompt.md): Base agent persona (loaded at runtime).
- [`docs/`](docs/): Technical references (`RESILIENCE.md`, `ROADMAP.md`).
- [`scripts/`](scripts/): Dev demos (rate limiting, retry classification).
- [`tests/`](tests/): Pytest suite.

---

## 4. Development & Running Commands

Always use the Python virtual environment (`venv`) to run commands.

### Environment Activation

* **Windows (PowerShell)**:
  ```powershell
  .\venv\Scripts\Activate.ps1
  ```
* **macOS / Linux**:
  ```bash
  source venv/bin/activate
  ```

### Development Commands

* **Install Dependencies**:
  ```bash
  pip install -r requirements.txt
  ```
* **Run App (Backend & Frontend Server)**:
  ```bash
  python app.py
  ```
* **Run Tests**:
  ```bash
  python -m pytest tests/
  ```

---

## 5. Coding & Editing Rules

- **Make Small, Focused Changes**: Never perform large, cosmetic refactors unless requested. Focus directly on the bug or feature.
- **Verify Existing Utilities**: Check `backend/memory_manager.py` or `backend/time_utils.py` before creating new helper functions.
- **Preserve Existing Style**: Keep PEP-8 naming conventions in Python and ES6 rules in Javascript. Do not strip comments.
- **Do Not Add Dependencies**: Avoid adding packages to `requirements.txt` unless absolutely necessary and approved by the user.

---

## 6. Dangerous Areas (Handle with Care)

- **Database Schema Changes**: Modifying `backend/models.py` requires care, as SQLite migrations are handled manually.
- **API Keys**: NEVER commit raw credentials or `.env` configurations. Use `.env.example` as a template.
- **API Rate Limiting Code**: The rate limiter is state-sensitive and timing-critical. Modifying `backend/rate_limiter.py` can cause app hangs or API blocks.

---

## 7. Debugging Playbook

When something fails:
1. **Identify the Layer**: Frontend UI, FastAPI route (`backend/routers/`), LiteLLM client, or SQLite.
2. **Examine Logs**: Run the app locally and watch terminal stdout/stderr or verify pytest traceback.
3. **Isolate Code**: Reproduce the error with the smallest possible test script.
4. **Fix Root Cause**: Resolve the bug without adding layers of bypass logic.
5. **Verify and Document**: Run the test suite (`python -m pytest`) and record the fix under "Recent Lessons" in `skills.md` if relevant.

---

## 8. Self-Improvement Rule

Whenever you solve a bug, implement a new feature, or receive a stylistic correction from the user, update the relevant `skills.md` file (either root-level or directory-level). 
- State the lesson clearly.
- Explain *why* it matters and *where* it applies.
- Keep rules actionable and concrete.

---

## 9. Recent Lessons

- **Lesson**: Virtual Environment Isolation.
  - **Why it matters**: Installing packages globally leads to dependency drift.
  - **Where it applies**: All local execution should be run from within `venv`.
