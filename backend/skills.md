# Backend Directory - Skills Playbook (`backend/skills.md`)

---

## System Documentation Index

| Task | Read |
|------|------|
| Routes, DB, prompts | This file |
| Global conventions | [skills.md](../skills.md) |
| AI persona & memory | [AGENTS.md](../AGENTS.md) |
| Rate limits & retry | [docs/RESILIENCE.md](../docs/RESILIENCE.md) |
| Frontend | [frontend/skills.md](../frontend/skills.md) |
| Tests | [tests/skills.md](../tests/skills.md) |

---

## Layout

| Module | Role |
|--------|------|
| `app.py` | FastAPI factory — lifespan, CORS, `register_routers()` |
| `routers/chat.py` | `/initialize`, `/initial-greeting`, `/chat` |
| `routers/conversations.py` | Conversation CRUD, export, message context |
| `routers/goals.py` | `GET/POST /goals`, `PUT /goals/{id}` — hierarchy CRUD, North Star promotion |
| `routers/memory.py` | LTM profile, logs, insights, stats (`compute_streak`) |
| `routers/system.py` | `/health`, `/rate-limit-status`, debug endpoints |
| `catalyst_ai.py` | Prompt assembly, LiteLLM calls, tool loop |
| `llm_client.py` | CLOD + Gemini via LiteLLM |
| `conversation.py` | Transcript loading, markdown export, context refs |
| `dependencies.py` | `get_db()` for FastAPI |
| `functions.py` | Registered AI tools |
| `memory_manager.py` | LTM getters, missed-session detection, `compute_streak`, `sync_ltm_north_star` |
| `rate_limiter.py` | Per-model quota queue |

---

## Rules

- **DB sessions**: Use `db: Session = Depends(get_db)` in routers. Do not create `SessionLocal()` in handlers.
- **Rate limiter**: Always `await rate_limiter.wait_for_request(model, estimated_tokens)` before LLM calls.
- **Prompts**: Base tone in `prompts/system_prompt.md`; session instructions in `catalyst_ai.get_session_instructions()`.
- **Time**: Use `local_now()` / `utc_now()` from `time_utils.py`.
- **New routes**: Add to the appropriate file under `routers/`, register in `routers/__init__.py`.
- **Goals**: `POST /initialize` returns **409** if active goals already exist. Use `POST /goals` for additional goals. North Star edits at rank 1 call `sync_ltm_north_star()` so LTM prose stays aligned with the `goals` table.
- **Streaks**: `GET /stats` derives streak from `daily_logs` via `compute_streak()` (consecutive days with at least one ritual completed). `update_session_tracking` persists the computed value to `session_tracking.streak_count`.

---

## Debugging

1. Check `CLOD_API_KEY` via `/health`.
2. Watch for SQLite lock errors — ensure commits in route handlers.
3. Empty model replies log `⚠️ Model returned empty response` — inspect retry/fallback in `catalyst_ai.py`.
4. Run `python -m pytest tests/ --ignore=tests/test_rate_limiter.py`.
