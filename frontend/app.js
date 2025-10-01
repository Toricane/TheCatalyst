import createDOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.2.7/dist/purify.es.mjs";
import { marked } from "https://cdn.jsdelivr.net/npm/marked@12.0.2/lib/marked.esm.js";

const DOMPurify = createDOMPurify(window);

marked.setOptions({
    gfm: true,
    breaks: true,
    headerIds: false,
    mangle: false,
});

function renderMarkdown(text = "") {
    const normalized = String(text ?? "").replace(/\r\n/g, "\n");
    const parsed = marked.parse(normalized);
    return DOMPurify.sanitize(parsed);
}

const API_BASE_URL = (() => {
    const { origin } = window.location;
    return origin.includes("localhost") || origin.includes("127.0.0.1")
        ? "http://localhost:8000"
        : origin.replace(/\/$/, "");
})();

const chatFeed = document.getElementById("chatFeed");
const typingIndicator = document.getElementById("typingIndicator");
const goalDisplay = document.getElementById("goalDisplay");
const messageInput = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const previewButton = document.getElementById("previewButton");
const previewModal = document.getElementById("previewModal");
const previewContent = document.getElementById("previewContent");
const closePreviewBtn = document.getElementById("closePreviewBtn");
const editButton = document.getElementById("editButton");
const sendFromPreviewButton = document.getElementById("sendFromPreviewButton");
const sessionButtons = Array.from(document.querySelectorAll(".session-btn"));
const initModal = document.getElementById("initModal");
const initButton = document.getElementById("initButton");
const goalDescription = document.getElementById("goalDescription");
const goalMetric = document.getElementById("goalMetric");
const goalTimeline = document.getElementById("goalTimeline");

let activeSession = "general";
let isSending = false;

function determineSessionTypeByLocalTime() {
    const hour = new Date().getHours();
    if (hour >= 5 && hour < 12) return "morning";
    if (hour >= 18 && hour < 23) return "evening";
    return "general";
}

function setActiveSession(session) {
    const validSessions = new Set(["morning", "general", "evening"]);
    const nextSession = validSessions.has(session) ? session : "general";
    activeSession = nextSession;

    sessionButtons.forEach((btn) => {
        const isActive = btn.dataset.session === nextSession;
        btn.classList.toggle("active", isActive);
        btn.setAttribute("aria-pressed", isActive ? "true" : "false");
    });
}

function appendMessage(role, text, options = {}) {
    const article = document.createElement("article");
    article.className = `message ${role}`;

    const wrapper = document.createElement("div");
    wrapper.className = "message-wrapper";

    const { model } = options;

    if (model) {
        const meta = document.createElement("div");
        meta.className = "message-meta";
        meta.textContent = model;
        wrapper.appendChild(meta);
    }

    const body = document.createElement("div");
    body.className = "message-body";
    body.innerHTML = renderMarkdown(text);

    wrapper.appendChild(body);
    article.appendChild(wrapper);
    chatFeed.appendChild(article);
    chatFeed.scrollTo({ top: chatFeed.scrollHeight, behavior: "smooth" });
}

function setTyping(isActive) {
    typingIndicator.classList.toggle("active", isActive);
}

function setSending(state) {
    isSending = state;
    sendButton.disabled = state;
    messageInput.disabled = state;
    previewButton.disabled = state;
    setTyping(state);
}

async function fetchJSON(url, options = {}) {
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

    return response.json();
}

async function refreshGoalDisplay() {
    try {
        const data = await fetchJSON(`${API_BASE_URL}/goals`);
        if (data.total > 0 && data.north_star) {
            const { description, metric, timeline } = data.north_star;
            goalDisplay.textContent = `${description} • ${
                metric || "No metric"
            } • ${timeline || "No timeline"}`;
            if (initModal.open) initModal.close();
            return true;
        }
        goalDisplay.textContent = "No North Star set yet.";
        if (!initModal.open) initModal.showModal();
        return false;
    } catch (error) {
        goalDisplay.textContent = `Could not load goal (${error.message})`;
        return false;
    }
}

async function sendMessage() {
    if (isSending) return;

    const text = messageInput.value.trim();
    if (!text) return;

    appendMessage("user", text);
    messageInput.value = "";
    autoResizeTextarea(); // Reset height after clearing
    setSending(true);

    try {
        const payload = { message: text, session_type: activeSession };
        const data = await fetchJSON(`${API_BASE_URL}/chat`, {
            method: "POST",
            body: JSON.stringify(payload),
        });

        appendMessage("catalyst", data.response, {
            model: data.model,
        });

        if (data.memory_updated) {
            await refreshGoalDisplay();
        }
    } catch (error) {
        appendMessage("catalyst", `<strong>System</strong>: ${error.message}`);
    } finally {
        setSending(false);
        messageInput.focus();
    }
}

async function initializeCatalyst() {
    const description = goalDescription.value.trim();
    const metric = goalMetric.value.trim();
    const timeline = goalTimeline.value.trim();

    if (!description) {
        goalDescription.focus();
        return;
    }

    try {
        setSending(true);
        const data = await fetchJSON(`${API_BASE_URL}/initialize`, {
            method: "POST",
            body: JSON.stringify({ description, metric, timeline, rank: 1 }),
        });

        appendMessage("catalyst", data.response, {
            model: data.model,
        });
        initModal.close();
        await refreshGoalDisplay();
    } catch (error) {
        appendMessage(
            "catalyst",
            `<strong>Initialization failed:</strong> ${error.message}`
        );
    } finally {
        setSending(false);
    }
}

function handleSessionClick(event) {
    const button = event.currentTarget;
    setActiveSession(button.dataset.session);
}

function showPreview() {
    const text = messageInput.value.trim();
    if (!text) {
        previewContent.innerHTML =
            '<p style="color: #94a3b8; font-style: italic;">Nothing to preview yet...</p>';
    } else {
        previewContent.innerHTML = renderMarkdown(text);
    }
    previewModal.showModal();
}

function closePreview() {
    previewModal.close();
    messageInput.focus();
}

function autoResizeTextarea() {
    messageInput.style.height = "auto";
    const maxHeight = parseInt(getComputedStyle(messageInput).maxHeight);
    const newHeight = Math.min(messageInput.scrollHeight, maxHeight);
    messageInput.style.height = newHeight + "px";
}

function bindEvents() {
    sendButton.addEventListener("click", sendMessage);

    messageInput.addEventListener("keydown", (event) => {
        // Ctrl+Enter or Cmd+Enter to send
        if (event.key === "Enter" && (event.ctrlKey || event.metaKey)) {
            event.preventDefault();
            sendMessage();
        }
        // Enter alone just adds a new line (default behavior)
    });

    // Auto-resize textarea as user types
    messageInput.addEventListener("input", autoResizeTextarea);

    // Preview functionality
    previewButton.addEventListener("click", showPreview);
    closePreviewBtn.addEventListener("click", closePreview);
    editButton.addEventListener("click", closePreview);
    sendFromPreviewButton.addEventListener("click", () => {
        previewModal.close();
        sendMessage();
    });

    // Close preview modal when clicking outside
    previewModal.addEventListener("click", (event) => {
        if (event.target === previewModal) {
            closePreview();
        }
    });

    // Escape key to close preview
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && previewModal.open) {
            closePreview();
        }
    });

    sessionButtons.forEach((button) =>
        button.addEventListener("click", handleSessionClick)
    );

    initButton.addEventListener("click", (event) => {
        event.preventDefault();
        initializeCatalyst();
    });
}

async function generateInitialGreeting() {
    try {
        setSending(true);
        const data = await fetchJSON(`${API_BASE_URL}/initial-greeting`, {
            method: "POST",
            body: JSON.stringify({ session_type: activeSession }),
        });
        appendMessage("catalyst", data.response, {
            model: data.model,
        });
    } catch (error) {
        appendMessage("catalyst", `<strong>System</strong>: ${error.message}`);
    } finally {
        setSending(false);
    }
}

async function init() {
    setActiveSession(determineSessionTypeByLocalTime());
    bindEvents();
    autoResizeTextarea(); // Set initial height
    const hasGoal = await refreshGoalDisplay();
    if (!hasGoal) {
        appendMessage(
            "catalyst",
            "I don't see your North Star goal yet. Let's set it now so I can tailor our sessions."
        );
    } else {
        // User has a goal, generate a personalized initial greeting
        await generateInitialGreeting();
    }
    messageInput.focus();
}

window.addEventListener("DOMContentLoaded", init);
