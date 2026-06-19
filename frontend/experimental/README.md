Prototype modules for **in-chat** rate-limit UX (not yet wired into the main chat flow).

- `enhanced_rate_limit_ui.js` — polls `/rate-limit-status` and shows wait messaging
- `rate_limit_styles.css` — styles for the above

**Note:** The Settings modal in the main UI already polls `/rate-limit-status` for daily quota meters. This folder is for live chat feedback (typing indicator, toasts) during `/chat` requests.

To integrate: import the script in `index.html` and call its hooks from `app.js` during chat requests. See [docs/RESILIENCE.md](../../docs/RESILIENCE.md).
