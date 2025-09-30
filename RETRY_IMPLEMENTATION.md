# Retry Logic Implementation for API Overload Errors

## Overview

This implementation adds robust retry logic to handle 503 "model is overloaded" errors from the Gemini API. The system now automatically retries failed requests with exponential backoff and falls back to an alternative model when needed.

## Features Implemented

### 1. **Intelligent Error Detection**

-   Automatically detects retryable errors (503, overloaded, unavailable)
-   Distinguishes between temporary and permanent failures
-   Only retries appropriate error types to avoid wasting resources

### 2. **Exponential Backoff with Jitter**

-   Base delay: 1 second, doubles with each retry
-   Maximum delay: 60 seconds to prevent excessive waiting
-   Random jitter (±10%) to avoid thundering herd problems
-   Formula: `delay = min(base_delay * (2^attempt), max_delay) + jitter`

### 3. **Model Fallback Strategy**

-   Primary model: `gemini-2.5-pro` (more capable, higher load)
-   Fallback model: `gemini-2.5-flash` (faster, more available)
-   Automatically switches to fallback model on final retry attempts

### 4. **Comprehensive Coverage**

-   Applied to initial AI generation calls
-   Applied to follow-up calls after function execution
-   Consistent behavior across all API interactions

### 5. **Rate Limit Integration**

-   Every attempt (including retries) reserves quota via the async rate limiter
-   New `get_wait_time` helper checks availability without committing quota
-   Retries automatically switch to the fallback model when the primary is saturated
-   Failed attempts release their reservations immediately to avoid quota leakage

## Error Handling Flow

```
API Call → Error? → Retryable? → Wait & Retry → Success?
    ↓           ↓        ↓           ↓           ↓
   Success     ↓       No          Yes         Yes → Continue
    ↓          ↓        ↓           ↓           ↓
 Continue    Yes      Fail      Try Again    No → Final Attempt?
                                  ↓           ↓
                               Success      Yes → Switch Model & Retry
                                  ↓           ↓
                               Continue    No → Fail with 503
```

## Configuration

### Retry Parameters

```python
MAX_RETRIES = 3          # Maximum retry attempts
BASE_DELAY = 1.0         # Base delay in seconds
MAX_DELAY = 60.0         # Maximum delay cap
JITTER_RANGE = 0.1       # ±10% randomization
```

### Models

```python
MODEL_NAME = "gemini-2.5-pro"        # Primary model
ALT_MODEL_NAME = "gemini-2.5-flash"  # Fallback model
```

## Implementation Details

### Core Functions

1. **`_is_retryable_error(error)`**

    - Checks if an error should trigger a retry
    - Looks for keywords: "503", "overloaded", "unavailable", "try again later"
    - Case-insensitive string matching

2. **`_calculate_retry_delay(attempt)`**

    - Calculates exponential backoff with jitter
    - Ensures delays stay within reasonable bounds
    - Adds randomization to prevent synchronized retries

3. **`_make_api_call_with_retry()`**

    - Orchestrates the entire retry process
    - Reserves rate-limit quota for every attempt (including retries)
    - Releases reservations for failed calls and records actual usage on success
    - Handles model fallback when the primary model is rate limited or overloaded
    - Provides detailed logging for debugging and monitoring

4. **`RateLimiter.get_wait_time()`**
    - Computes how long a request would need to wait without mutating state
    - Enables smart model selection before committing a request
    - Keeps retry logic responsive by preferring whichever model is immediately available

### Integration Points

-   **Initial API Call**: In `generate_catalyst_response()` for first user message
-   **Follow-up Calls**: After function executions when AI needs to respond
-   **Test Functions**: Ensures consistency across all API interactions

## User Experience Improvements

### Before Implementation

```
❌ Error 503: Model overloaded → Immediate failure
```

### After Implementation

```
⚠️  Initial call failed (attempt 1/3): Model overloaded
⏳ Waiting 1.2s before retry...
🔄 Retry attempt 2/3 for initial call (using gemini-2.5-pro)
⚠️  Initial call failed (attempt 2/3): Model overloaded
⏳ Waiting 2.1s before retry...
🔄 Retry attempt 3/3 for initial call (using gemini-2.5-flash)
✅ Initial call succeeded on attempt 3
```

## Error Messages

### Success After Retry

-   Logs successful recovery with attempt number
-   Transparent to end users (they just see the response)

### Complete Failure

```json
{
    "error": {
        "code": 503,
        "message": "AI service temporarily unavailable after 3 attempts. Last error: The model is overloaded. Please try again later.",
        "status": "UNAVAILABLE"
    }
}
```

## Performance Considerations

### Benefits

-   **Resilience**: System continues working during high load periods
-   **User Experience**: Seamless operation instead of error messages
-   **Load Distribution**: Jitter prevents synchronized retry storms

### Trade-offs

-   **Latency**: Adds delay during overload situations (but prevents total failure)
-   **Resource Usage**: Multiple attempts use more computational resources
-   **Complexity**: More complex error handling logic

## Monitoring & Debugging

### Log Messages

-   `🔄 Retry attempt X/Y for Z call (using model)`
-   `⚠️ Z call failed (attempt X/Y): error message`
-   `⏳ Waiting Xs before retry...`
-   `✅ Z call succeeded on attempt X`
-   `❌ All retry attempts failed for Z call`

### Key Metrics to Monitor

-   Retry attempt frequency
-   Success rate after retries
-   Model fallback usage
-   Average response times during overload

## Testing

Run the test suite to verify retry behavior:

```bash
python test_retry_logic.py
```

The test covers:

-   Error detection accuracy
-   Retry delay calculations
-   Exponential backoff progression
-   Jitter randomization

## Future Enhancements

### Potential Improvements

1. **Circuit Breaker**: Skip retries if service is consistently down
2. **Adaptive Timeouts**: Adjust retry behavior based on historical performance
3. **Queue Management**: Implement request queuing during overload
4. **Health Monitoring**: Track API health and adjust retry strategies
5. **Metrics Collection**: Detailed retry analytics and reporting

### Configuration Options

Consider making retry parameters configurable via environment variables:

```
RETRY_MAX_ATTEMPTS=3
RETRY_BASE_DELAY=1.0
RETRY_MAX_DELAY=60.0
RETRY_JITTER_RANGE=0.1
```

## Conclusion

This implementation provides robust error handling for API overload scenarios while maintaining excellent user experience. The system gracefully handles temporary service unavailability and automatically recovers without user intervention.

The retry logic is:

-   **Smart**: Only retries appropriate errors
-   **Efficient**: Uses exponential backoff with jitter
-   **Resilient**: Falls back to alternative models
-   **Transparent**: Minimal impact on user experience
-   **Observable**: Provides clear logging for debugging
