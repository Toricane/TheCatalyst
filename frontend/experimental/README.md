# Experimental UI

Prototype modules not yet wired into the main chat UI.

- `enhanced_rate_limit_ui.js` — polls `/rate-limit-status` and shows wait messaging
- `rate_limit_styles.css` — styles for the above

To integrate: import the script in `index.html` and call its hooks from `app.js` during chat requests. See [docs/RESILIENCE.md](../../docs/RESILIENCE.md).
