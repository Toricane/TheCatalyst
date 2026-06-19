# Frontend Directory - Skills Playbook (`frontend/skills.md`)

---

## 🧭 System Documentation Index & Handoffs

Before modifying any code, review this map to determine which reference file is relevant to your task:

* **Look at [frontend/skills.md](skills.md) (This File)**:
  - When updating CSS, editing html templates, modals, or markdown rendering.
  - When wiring header actions, goals editor, stats/settings panels, or rate-limit UI.
* **Look at [skills.md](../skills.md) (Root Playbook)**:
  - When starting a new chat session to ground yourself in general project guidelines.
  - When reviewing global conventions, project commands, or the **Self-Improving Skill** workflow.
* **Look at [AGENTS.md](../AGENTS.md)**:
  - When studying the internal AI mentor's persona, mindset stack, or communication modes.
  - When debugging LiteLLM / backend API behavior.
  - When reviewing SQLite schema fields, streaks updates, or memory synthesis logic.
* **Look at [backend/skills.md](../backend/skills.md)**:
  - When modifying FastAPI routes, database models, time utilities, or prompt builders.
* **Look at [tests/skills.md](../tests/skills.md)**:
  - When writing test fixtures, running pytests, or verifying changes before commit.

---

## 1. Purpose

This directory contains the user-facing HTML shell, CSS layouts, and Vanilla Javascript client for **The Catalyst** chat app.

---

## 2. When to Edit This Directory

* **Edit here when**:
  - Modifying styling, alignment, theme colors, or animation keyframes.
  - Adding or changing modals (Goals, Stats, Settings), panels, or markdown-rendered content.
  - Connecting button event listeners or API-fetching wrappers.

* **Do NOT edit here when**:
  - Fixing server-side API routing or goal/streak business logic.
  - Updating core prompt constraints or SQLite DB fields.

---

## 3. Important Files

- [`index.html`](index.html): Chat shell, modals (`#goalsModal`, `#statsModal`, `#settingsModal`).
- [`style.css`](style.css): Main UI styling. Shared `.markdown-content` typography for chat and panels.
- [`app.js`](app.js): State, chat rendering, goals/stats/settings modals, `fetchJSON` wrappers.
- [`experimental/`](experimental/): Rate-limit UI prototype for **chat** integration (not yet wired; Settings shows quota via `/rate-limit-status`).

---

## 4. UI Surfaces & Element IDs

| Surface | Trigger | Key IDs |
|---------|---------|---------|
| North Star badge | `#goalBadge` click | `#goalDisplay` |
| Goals modal | Badge, first-time auto-open, Settings → Edit goals | `#goalsModal`, `#goalsInitView`, `#goalsEditView`, `#goalsList`, `#initButton`, `#addGoalButton` |
| Stats modal | `#statsButton` | `#statsModal`, `#statsContent` |
| Settings modal | `#settingsButton` | `#settingsModal`, `#settingsContent` |
| Chat | — | `#chatFeed`, `#messageInput`, `#sendButton` |
| Debug context | Right-click catalyst message | `#systemContextModal`, `#systemContextContent` |

---

## 5. Markdown Rendering

User-facing prose uses **marked** + **DOMPurify** (CDN in `app.js`).

| Helper | Use |
|--------|-----|
| `markdownToHtml(text)` | Sanitized HTML string |
| `markdownBlock(text, extraClass)` | Wrapped `<div class="markdown-content …">` |
| `plainTextFromMarkdown(text)` | Strip formatting for compact UI (header badge) |

Apply `.markdown-content` (optionally `.compact`) to any container that displays wins, gratitude, LTM sections, insights, conversation previews, or chat bodies. Do **not** use `escapeHtml` for user-authored prose that should support markdown.

Cache-bust `app.js` / `style.css` query params in `index.html` when shipping breaking frontend changes.

---

## 6. Local Rules & Architecture

- **Vanilla CSS**: No Tailwind unless requested. Dark theme, glassmorphic cards, orange accents.
- **Quota UI**: Settings modal polls `/rate-limit-status`. Full chat integration remains in `experimental/`.
- **Strict Element IDs**: Keep header and modal controls ID-stable for tests and bindings.

---

## 7. Common Mistakes

- **Mistake**: Overriding element styles using inline CSS.
  - *Fix*: Declare classes inside `style.css` and toggle via `classList`.
- **Mistake**: Displaying LTM or log text with `escapeHtml` / `textContent` when markdown is expected.
  - *Fix*: Use `markdownBlock()` or `markdownToHtml()` with `.markdown-content`.
- **Mistake**: Calling CLOD or Gemini directly from the browser.
  - *Fix*: Use backend routes only via `fetchJSON`.

---

## 8. Debugging Playbook

1. **Developer Console** (`F12`): Syntax errors, failed fetches, stale cached `app.js`.
2. **Hard refresh**: `Ctrl+Shift+R` after HTML/JS changes (or bump `?v=` on script/link tags).
3. **Local ports**: Frontend `http://localhost:3000/frontend/`, API `http://localhost:8000` (via `python app.py`).
4. **Goals not loading**: Confirm `GET /goals` and that `#goalsModal` exists in served `index.html`.
