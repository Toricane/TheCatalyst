# Frontend Directory - Skills Playbook (`frontend/skills.md`)

---

## 🧭 System Documentation Index & Handoffs

Before modifying any code, review this map to determine which reference file is relevant to your task:

* **Look at [frontend/skills.md](skills.md) (This File)**:
  - When updating CSS, editing html templates, or integrating the rate limiter status UI.
* **Look at [skills.md](../skills.md) (Root Playbook)**:
  - When starting a new chat session to ground yourself in general project guidelines.
  - When reviewing global conventions, project commands, or the **Self-Improving Skill** workflow.
* **Look at [AGENTS.md](../AGENTS.md)**:
  - When studying the internal AI mentor's persona, mindset stack, or communication modes.
  - When debugging how the backend interacts with the Gemini API or executes tools.
  - When reviewing SQLite schema fields, streaks updates, or memory synthesis logic.
* **Look at [backend/skills.md](../backend/skills.md)**:
  - When modifying FastAPI routes, database models, time utilities, or prompt builders.
* **Look at [tests/skills.md](../tests/skills.md)**:
  - When writing test fixtures, running pytests, or verifying changes before commit.

---

## 1. Purpose

This directory contains the user-facing HTML shell, CSS layouts, and Vanilla Javascript client script for **The Catalyst** chat app.

---

## 2. When to Edit This Directory

* **Edit here when**:
  - Modifying the styling, alignment, theme colors, or animation keyframes.
  - Adding UI widgets, feedback prompts, status bars, or streaks counters.
  - Connecting button event listeners or API-fetching wrappers.

* **Do NOT edit here when**:
  - Fixing server-side API routing.
  - Updating core prompt constraints or SQLite DB fields.

---

## 3. Important Files

- [`index.html`](index.html): Chat structure and container nodes.
- [`style.css`](style.css): Main UI styling sheet. Contains dark mode and typography defaults.
- [`app.js`](app.js): Application state machine, chat rendering logic, and fetch wrappers.
- [`enhanced_rate_limit_ui.js`](enhanced_rate_limit_ui.js): Pre-coded components to show rate limit status. Use this to replace standard `fetchJSON` when performing user experience upgrades.

---

## 4. Local Rules & Architecture

- **Vanilla CSS Flexible Layouts**: Avoid introducing CSS utility libraries like Tailwind unless explicitly requested. Maintain consistency with the existing color palette (dark theme, glassmorphic card overlays, neon-orange flame details).
- **Quota Warnings Integration**: The frontend is not fully integrated with `enhanced_rate_limit_ui.js`. When implementing features:
  - Replace `fetchJSON` calls with `fetchJSONWithRateLimit` to handle delays dynamically.
  - Use `setTypingWithContext` to display the specific stage (thinking, quota wait, retrying) instead of generic typing indicators.
- **Strict Element IDs**: Ensure all input widgets and event buttons have unique IDs to prevent selenium/browser test breakage.

---

## 5. Common Mistakes

- **Mistake**: Overriding element styles using inline CSS.
  - *Fix*: Declare classes inside `style.css` and toggle them via classList in Javascript.
- **Mistake**: Making API requests directly instead of going through backend endpoint wrappers.
  - *Fix*: Always request backend routes `/chat`, `/goals`, or `/initialize`. Never make external requests directly to Gemini from client javascript.

---

## 6. Debugging Playbook

1. **Check Developer Console**: Open browser inspect tools (`F12`) to identify syntax errors, blocked HTTP calls, or failed fetch promises.
2. **Local Port Check**: Ensure frontend is served locally (`python -m http.server 3000` or via `app.py` wrapper) to prevent CORS errors during api calls.
3. **Verify State Updates**: If streaks, goals, or historical logs don't update after conversation:
   - Check if the backend response returned success.
   - Inspect local state variables in `app.js` (e.g. `currentGoal`, `sessionHistory`).
