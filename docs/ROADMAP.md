# Roadmap

Delivered capabilities are documented in [AGENTS.md](../AGENTS.md) and [README.md](../README.md). Items below are planned next steps.

## Phase A — Frontend UX

- [ ] Integrate rate-limit status UI into the main chat view (prototype in `frontend/experimental/`)
- [x] API quota meters in Settings modal (polls `/rate-limit-status`)
- [ ] Floating API quota dashboard in chat (persistent widget)

## Phase B — Features

- [ ] Voice interaction (WebRTC)
- [x] Multi-goal hierarchies (basic: North Star + sub-goals via Goals modal; no drag-reorder or sub-tasks)
- [ ] Productivity integrations (calendar, task apps)
- [x] Analytics dashboard (Stats modal: streaks, ritual calendar, energy/focus, wins, gratitude, insights)

## Phase C — Platform

- [ ] CI pipeline (pytest on push)
- [ ] Optional CLOD usage sync via platform API (`/teams/{id}/daily-request-count`)
