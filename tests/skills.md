# Tests Directory - Skills Playbook (`tests/skills.md`)

---

## 🧭 System Documentation Index & Handoffs

Before modifying any code, review this map to determine which reference file is relevant to your task:

* **Look at [tests/skills.md](skills.md) (This File)**:
  - When writing test fixtures, running pytests, or verifying changes before commit.
* **Look at [skills.md](../skills.md) (Root Playbook)**:
  - When starting a new chat session to ground yourself in general project guidelines.
  - When reviewing global conventions, project commands, or the **Self-Improving Skill** workflow.
* **Look at [AGENTS.md](../AGENTS.md)**:
  - When studying the internal AI mentor's persona, mindset stack, or communication modes.
  - When debugging LiteLLM integration or backend routes.
  - When reviewing SQLite schema fields, streaks updates, or memory synthesis logic.
* **Look at [backend/skills.md](../backend/skills.md)**:
  - When modifying FastAPI routes, database models, time utilities, or prompt builders.
* **Look at [frontend/skills.md](../frontend/skills.md)**:
  - When updating CSS, editing html templates, or integrating the rate limiter status UI.

---

## 1. Purpose

This directory contains automated unit and integration tests verifying API endpoint behavior, memory synthesis, function registry, and rate-limiting limits.

---

## 2. When to Edit This Directory

* **Edit here when**:
  - Writing test cases for a new backend feature, API route, or database helper.
  - Updating test mocks when the LiteLLM response structure changes.
  - Adding assertions to cover a newly discovered edge case.

* **Do NOT edit here when**:
  - Implementing the actual core application logic.
  - Refactoring frontend HTML/CSS mockups.

---

## 3. Important Files

- [`test_conversation_history.py`](test_conversation_history.py): Conversation CRUD, export, chat dedup (TestClient + in-memory DB).
- [`test_server.py`](test_server.py): Live integration against running server (skips if down).
- [`test_rate_limiter.py`](test_rate_limiter.py): Evaluates the RPM/TPM queue delays.
- [`test_retry_logic.py`](test_retry_logic.py): Tests the exponential backoff calculation and fallback model logic.
- [`test_memory_manager.py`](test_memory_manager.py): Missed-session windows, LTM section parsing.
- [`test_goals.py`](test_goals.py): Goals CRUD, North Star promotion, `compute_streak`, `/stats` streak wiring.
- [`test_functions.py`](test_functions.py): Database insertion and session tracking functions.

---

## 4. Testing Rules

- **Use Mocks for External APIs**: Never run tests that make live calls to CLOD or Gemini. Always mock `llm_client.acompletion` and check parameter invocations.
- **Isolate DB Sessions**: Use scoped, temporary SQLite sessions (e.g. SQLite `:memory:`) or clear test database records between assertions.
- **Do Not Disable Tests**: If a test fails, fix the code or update the test mock rather than commenting it out or deleting it.

---

## 5. Running & Validating Tests

Run tests from the project root using the virtual environment.

> [!IMPORTANT]
> The rate limiter test (`test_rate_limiter.py`) simulates active waiting delays and takes over 3 minutes to complete. **Do not run this test unless explicitly requested.** Always ignore it during routine code verification.

* **Run tests (excluding rate limiter)**:
  ```bash
  python -m pytest --ignore=tests/test_rate_limiter.py tests/
  ```

* **Run a single test file**:
  ```bash
  python -m pytest tests/test_retry_logic.py
  ```

* **Run a single test method**:
  ```bash
  python -m pytest tests/test_retry_logic.py -k "test_is_retryable_error"
  ```

* **Show Print Statements / Debug Output**:
  ```bash
  python -m pytest -s tests/
  ```
