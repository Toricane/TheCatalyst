# Roadmap

Delivered capabilities are documented in [AGENTS.md](../AGENTS.md) and [README.md](../README.md). Items below are planned next steps.

## Phase A — Frontend UX

- [ ] Integrate rate-limit status UI into the main chat view (prototype in `frontend/experimental/`)
- [ ] Floating API quota dashboard (poll `/rate-limit-status`)

## Phase B — Features

- [ ] Voice interaction (WebRTC)
- [ ] Multi-goal hierarchies and sub-tasks
- [ ] Productivity integrations (calendar, task apps)
- [ ] Analytics dashboard (streaks, energy/focus trends)

## Phase C — Platform

- [ ] CI pipeline (pytest on push)
- [ ] Optional CLOD usage sync via platform API (`/teams/{id}/daily-request-count`)
