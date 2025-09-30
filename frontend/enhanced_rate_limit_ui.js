/**
 * Enhanced chat functionality with rate limiting awareness
 * This demonstrates what the frontend SHOULD do when rate limits cause delays
 */

// Rate limiting status tracking
let rateLimitStatus = {
    isWaiting: false,
    estimatedWait: 0,
    reason: null,
};

// Enhanced fetchJSON with rate limit awareness
async function fetchJSONWithRateLimit(url, options = {}) {
    const startTime = Date.now();

    try {
        const response = await fetch(url, {
            headers: { "Content-Type": "application/json" },
            ...options,
        });

        if (!response.ok) {
            let detail = response.statusText;
            try {
                const data = await response.json();
                detail = data.detail || JSON.stringify(data);
            } catch (err) {
                detail = `${response.status} ${response.statusText}`;
            }
            throw new Error(detail);
        }

        // Check for rate limit headers (if backend provides them)
        const rateLimitRemaining = response.headers.get(
            "X-RateLimit-Remaining"
        );
        const rateLimitReset = response.headers.get("X-RateLimit-Reset");

        if (rateLimitRemaining !== null && parseInt(rateLimitRemaining) < 2) {
            // Approaching rate limit
            updateRateLimitStatus({
                isWaiting: false,
                approaching: true,
                remaining: parseInt(rateLimitRemaining),
                resetTime: rateLimitReset,
            });
        }

        const responseTime = Date.now() - startTime;

        // If response took unusually long, assume rate limiting was involved
        if (responseTime > 5000) {
            showRateLimitNotification(responseTime);
        }

        return response.json();
    } catch (error) {
        throw error;
    }
}

// Enhanced typing indicator with rate limit context
function setTypingWithContext(isActive, context = null) {
    const typingIndicator = document.getElementById("typingIndicator");
    const statusText =
        document.getElementById("statusText") || createStatusText();

    if (isActive) {
        typingIndicator.classList.add("active");

        if (context?.rateLimited) {
            statusText.textContent = `⏳ Waiting for API quota (${context.estimatedWait}s remaining)...`;
            statusText.className = "status-text rate-limited";
        } else if (context?.thinking) {
            statusText.textContent = "🧠 The Catalyst is thinking deeply...";
            statusText.className = "status-text thinking";
        } else {
            statusText.textContent = "💭 The Catalyst is responding...";
            statusText.className = "status-text normal";
        }

        statusText.style.display = "block";
    } else {
        typingIndicator.classList.remove("active");
        statusText.style.display = "none";
    }
}

// Create status text element if it doesn't exist
function createStatusText() {
    const statusText = document.createElement("div");
    statusText.id = "statusText";
    statusText.className = "status-text";

    const typingIndicator = document.getElementById("typingIndicator");
    typingIndicator.parentNode.insertBefore(
        statusText,
        typingIndicator.nextSibling
    );

    return statusText;
}

// Show rate limit notification
function showRateLimitNotification(delayMs) {
    const notification = document.createElement("div");
    notification.className = "rate-limit-notification";
    notification.innerHTML = `
        <div class="notification-content">
            <span class="notification-icon">⏱️</span>
            <span class="notification-text">
                Response delayed ${Math.round(
                    delayMs / 1000
                )}s due to API rate limiting. 
                This helps ensure consistent service.
            </span>
        </div>
    `;

    document.body.appendChild(notification);

    // Auto-remove after 5 seconds
    setTimeout(() => {
        notification.remove();
    }, 5000);
}

// Enhanced send message with rate limit awareness
async function sendMessageWithRateLimit() {
    if (isSending) return;

    const text = messageInput.value.trim();
    if (!text) return;

    appendMessage("user", text);
    messageInput.value = "";
    autoResizeTextarea();
    setSending(true);

    try {
        // Start with normal typing indicator
        setTypingWithContext(true, { thinking: true });

        const startTime = Date.now();
        const payload = { message: text, session_type: activeSession };

        // Simulate checking for rate limit status from backend
        // In real implementation, this could be a separate endpoint
        const rateLimitCheck = await checkRateLimitStatus();

        if (rateLimitCheck.willWait > 3000) {
            // If we expect a significant delay, inform the user
            setTypingWithContext(true, {
                rateLimited: true,
                estimatedWait: Math.round(rateLimitCheck.willWait / 1000),
            });
        }

        const data = await fetchJSONWithRateLimit(`${API_BASE_URL}/chat`, {
            method: "POST",
            body: JSON.stringify(payload),
        });

        const responseTime = Date.now() - startTime;

        appendMessage("catalyst", data.response);

        if (data.memory_updated) {
            await refreshGoalDisplay();
        }

        // If response was delayed significantly, show why
        if (responseTime > 5000) {
            appendSystemMessage(
                `ℹ️ Response took ${Math.round(
                    responseTime / 1000
                )}s due to API rate limiting. ` +
                    `This ensures reliable service within usage quotas.`
            );
        }
    } catch (error) {
        appendMessage("catalyst", `<strong>System</strong>: ${error.message}`);
    } finally {
        setTypingWithContext(false);
        setSending(false);
        messageInput.focus();
    }
}

// Mock function - in real implementation, backend would provide this
async function checkRateLimitStatus() {
    try {
        const response = await fetch(`${API_BASE_URL}/rate-limit-status`);
        if (response.ok) {
            return await response.json();
        }
    } catch (error) {
        // Fallback: assume no delay
    }

    return { willWait: 0, quotaRemaining: 100 };
}

// Add system message (different styling from regular messages)
function appendSystemMessage(text) {
    const article = document.createElement("article");
    article.className = "message system";

    const body = document.createElement("div");
    body.className = "message-body";
    body.innerHTML = `<small>${text}</small>`;

    article.appendChild(body);
    chatFeed.appendChild(article);
    chatFeed.scrollTo({ top: chatFeed.scrollHeight, behavior: "smooth" });
}

// Export for potential use
if (typeof module !== "undefined" && module.exports) {
    module.exports = {
        fetchJSONWithRateLimit,
        setTypingWithContext,
        sendMessageWithRateLimit,
        showRateLimitNotification,
    };
}
