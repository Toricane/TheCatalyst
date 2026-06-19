# API Resilience: Rate Limiting & Retry Logic

Technical reference for how The Catalyst handles LLM quotas and transient failures. Product-level summary lives in [AGENTS.md](../AGENTS.md#4-api-resilience-rate-limiting--retry-logic).

## Stack

- **Transport**: [LiteLLM](https://docs.litellm.ai/) via [`backend/llm_client.py`](../backend/llm_client.py)
- **Primary**: CLOD (`GPT OSS 120B` at `https://api.clod.io/v1`)
- **Fallback**: Gemini (`gemini-2.5-flash`) when CLOD is unavailable
- **Orchestration**: [`backend/catalyst_ai.py`](../backend/catalyst_ai.py) — `_make_api_call_with_retry()`
- **Quota queue**: [`backend/rate_limiter.py`](../backend/rate_limiter.py)

## Default rate limits

| Model | RPM | TPM | RPD | Notes |
|-------|-----|-----|-----|-------|
| `GPT OSS 120B` | 0 (disabled) | 0 (disabled) | 100 | CLOD free tier; RPM/TPM not published |
| `gemini-2.5-flash` | 10 | 250,000 | 250 | Google free-tier defaults |

Override via env: `GPT_OSS_120B_RPD`, `GEMINI_2_5_FLASH_RPM`, etc. (see [`backend/config.py`](../backend/config.py)).

When `rpm` or `tpm` is `0`, the limiter skips that dimension.

## Retry behavior

| Setting | Value |
|---------|-------|
| Max attempts | 4 |
| Base delay | 1.0s |
| Max delay | 60.0s |
| Jitter | ±10% |

**Retryable errors**: 502/503/504, overloaded, unavailable, connection errors.

**429 quota**: Parsed for `retry_after`; registers backoff on the rate limiter.

**Fallback**: After a retryable failure on the primary model, next attempt uses `ALT_MODEL_NAME` (Gemini). Rate-limit saturation can also preemptively switch models.

## Error flow

```
API call → success → record token usage
         → 429 → backoff + retry (or switch model)
         → 503-style → exponential backoff + retry (or switch to Gemini)
         → other → fail immediately
```

## Frontend gap

The backend queues requests transparently. The chat UI does not yet poll `/rate-limit-status` or show wait messages during long delays. See [`frontend/experimental/`](../frontend/experimental/) for a prototype rate-limit UI module.

## Testing

```bash
.\venv\Scripts\python.exe -m pytest tests/test_retry_logic.py tests/test_rate_limiter.py -q
```

Full suite (rate limiter tests take ~3 min due to real timer waits):

```bash
.\venv\Scripts\python.exe -m pytest tests/ -q
```
