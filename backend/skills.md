# Backend Directory - Skills Playbook (`backend/skills.md`)

---

## 🧭 System Documentation Index & Handoffs

Before modifying any code, review this map to determine which reference file is relevant to your task:

* **Look at [backend/skills.md](skills.md) (This File)**:
  - When modifying FastAPI routes, database models, time utilities, or prompt builders.
* **Look at [skills.md](../skills.md) (Root Playbook)**:
  - When starting a new chat session to ground yourself in general project guidelines.
  - When reviewing global conventions, project commands, or the **Self-Improving Skill** workflow.
* **Look at [AGENTS.md](../AGENTS.md)**:
  - When studying the internal AI mentor's persona, mindset stack, or communication modes.
  - When debugging how the backend interacts with the Gemini API or executes tools.
  - When reviewing SQLite schema fields, streaks updates, or memory synthesis logic.
* **Look at [frontend/skills.md](../frontend/skills.md)**:
  - When updating CSS, editing html templates, or integrating the rate limiter status UI.
* **Look at [tests/skills.md](../tests/skills.md)**:
  - When writing test fixtures, running pytests, or verifying changes before commit.

---

## 1. Purpose

This directory contains the FastAPI backend, SQLAlchemy database integration, SQLite models, memory management utilities, and Gemini API connectors.

---

## 2. When to Edit This Directory

* **Edit here when**:
  - Changing API endpoints or adding route paths.
  - Modifying database schemas or ORM structures.
  - Adjusting Gemini prompt composition, retry logic, or rate-limiter windows.
  - Modifying memory extraction methods.

* **Do NOT edit here when**:
  - Making changes to the HTML layout or CSS styles.
  - Editing client-side AJAX requests or frontend event loops (unless API contracts change).

---

## 3. Important Files

- [`app.py`](app.py): API routes. Uses `Session` Dependency injection (`get_session`).
- [`catalyst_ai.py`](catalyst_ai.py): High-level AI response handler, prompts builder, and tool callers.
- [`rate_limiter.py`](rate_limiter.py): Class managing rate limits based on token size estimates.
- [`models.py`](models.py): ORM schemas (`Goal`, `DailyLog`, `LTMProfile`, `Conversation`, `SessionTracking`).

---

## 4. Local Rules & Architecture

- **Session Lifecycle**: Database sessions are injected via FastAPI dependencies: `db: Session = Depends(get_session)`. Do not instantiate `SessionLocal()` directly in endpoint handlers.
- **Asynchronous Safe Calls**: Use `await` for rate-limiter holds: `await rate_limiter.wait_for_request(model, estimated_tokens)`.
- **System Prompt Integrity**: Base instructions reside in `prompts/system_prompt.md`. Do not hardcode tone controls inside `backend/catalyst_ai.py`. Use `_build_system_prompt` to bundle inputs dynamically.

---

## 5. Common Mistakes

- **Mistake**: Forgetting to handle empty replies or tool callback issues.
  - *Fix*: The backend uses `_retry_once_if_empty` and handles iterative tool executions (up to 3 loops) in `generate_catalyst_response`. Maintain this structure.
- **Mistake**: Using naive `datetime.now()` instead of timezone-aware datetimes.
  - *Fix*: Use `local_now()` and `utc_now()` from `backend/time_utils.py` to keep SQLite timestamp consistency.

---

## 6. Debugging Playbook

1. **Verify API Key**: Check if `GEMINI_API_KEY` is loaded by inspecting environment variables or visiting the `/health` endpoint.
2. **Watch SQLite Lock Errors**: Ensure database queries commit or rollback cleanly inside endpoints.
3. **Verify API Responses**: If Gemini returns a blank or unexpected JSON structure:
   - Inspect the logs for `⚠️ Gemini returned empty response`.
   - Run the custom unit tests (`python test_functions.py` or similar helper tests) to see raw payloads.
