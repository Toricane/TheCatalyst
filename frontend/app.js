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

const SESSION_LABELS = {
    morning: "Morning",
    evening: "Evening",
    general: "General",
    catch_up: "Catch-up",
    initialization: "Initialization",
};

const timestampFormatter = new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
});

const chatFeed = document.getElementById("chatFeed");
const typingIndicator = document.getElementById("typingIndicator");
const goalDisplay = document.getElementById("goalDisplay");
const conversationList = document.getElementById("conversationList");
const conversationEmpty = document.getElementById("conversationEmpty");
const conversationSummary = document.getElementById("conversationSummary");
const conversationContextMenu = document.getElementById(
    "conversationContextMenu"
);

const newConversationButton = document.getElementById("newConversationButton");
const sidebarToggle = document.getElementById("sidebarToggle");
const sidebar = document.getElementById("sidebar");
const messageInput = document.getElementById("messageInput");
const sendButton = document.getElementById("sendButton");
const previewToggle = document.getElementById("previewToggle");
const inputPreviewPanel = document.getElementById("inputPreviewPanel");
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
let pendingInitialGreeting = null;
let isReadOnlyConversation = false;
let activeConversationId = null;
let latestConversationId = null;
let conversationsMeta = [];
const conversationCache = new Map();
let latestConversationDraft = "";
let contextMenuTargetId = null;
let contextMenuTargetElement = null;

function determineSessionTypeByLocalTime() {
    const hour = new Date().getHours();
    if (hour >= 4 && hour < 10) return "morning";
    if (hour >= 20 && hour < 24) return "evening";
    return "general";
}

function formatSessionLabel(value) {
    if (!value) return "Conversation";
    return SESSION_LABELS[value] || value;
}

function formatTimestamp(value) {
    if (!value) return "";
    try {
        const date = value instanceof Date ? value : new Date(value);
        if (Number.isNaN(date.getTime())) return String(value);
        return timestampFormatter.format(date);
    } catch (error) {
        return String(value);
    }
}

function formatConversationTitle(meta) {
    if (!meta) return "Conversation";
    const primaryLabel = formatSessionLabel(meta.session_types?.[0]);
    return primaryLabel;
}

function setConversationSummary(meta) {
    if (!meta) {
        conversationSummary.textContent = "";
        conversationSummary.hidden = true;
        return;
    }
    const parts = [];
    if (meta.updated_at) {
        parts.push(`Last activity ${formatTimestamp(meta.updated_at)}`);
    }
    if (meta.message_count) {
        const count = meta.message_count;
        parts.push(`${count} message${count === 1 ? "" : "s"}`);
    }
    conversationSummary.textContent = parts.join(" • ");
    conversationSummary.hidden = parts.length === 0;
}

function closeConversationContextMenu() {
    if (conversationContextMenu && !conversationContextMenu.hidden) {
        conversationContextMenu.hidden = true;
        conversationContextMenu.setAttribute("aria-hidden", "true");
        conversationContextMenu.style.removeProperty("left");
        conversationContextMenu.style.removeProperty("top");
    }
    if (contextMenuTargetElement) {
        contextMenuTargetElement.classList.remove("menu-open");
        contextMenuTargetElement = null;
    }
    contextMenuTargetId = null;
}

function openConversationContextMenu(x, y, conversationId, triggerElement) {
    if (!conversationContextMenu || !conversationId) return;

    if (
        contextMenuTargetElement &&
        contextMenuTargetElement !== triggerElement
    ) {
        contextMenuTargetElement.classList.remove("menu-open");
    }

    contextMenuTargetElement = triggerElement || null;
    if (contextMenuTargetElement) {
        contextMenuTargetElement.classList.add("menu-open");
    }

    contextMenuTargetId = conversationId;
    conversationContextMenu.hidden = false;
    conversationContextMenu.setAttribute("aria-hidden", "false");

    conversationContextMenu.style.left = "0px";
    conversationContextMenu.style.top = "0px";

    const rect = conversationContextMenu.getBoundingClientRect();
    const menuWidth = rect.width || 0;
    const menuHeight = rect.height || 0;
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    const margin = 8;

    const posX = Math.min(
        Math.max(x, margin),
        Math.max(margin, viewportWidth - menuWidth - margin)
    );
    const posY = Math.min(
        Math.max(y, margin),
        Math.max(margin, viewportHeight - menuHeight - margin)
    );

    conversationContextMenu.style.left = `${posX}px`;
    conversationContextMenu.style.top = `${posY}px`;

    const focusable = conversationContextMenu.querySelector("button");
    if (focusable) {
        focusable.focus();
    }
}

async function deleteConversationRequest(conversationId) {
    const response = await fetch(
        `${API_BASE_URL}/conversations/${conversationId}`,
        { method: "DELETE" }
    );

    if (!response.ok) {
        let detail = response.statusText;
        try {
            const data = await response.json();
            detail = data.detail || JSON.stringify(data);
        } catch (error) {
            detail = `${response.status} ${response.statusText}`;
        }
        throw new Error(detail);
    }
}

async function handleDeleteConversation(conversationId) {
    if (!conversationId) return;

    const meta = getConversationMeta(conversationId);
    const title = meta ? formatConversationTitle(meta) : "this conversation";
    const truncatedPreview = meta?.preview
        ? meta.preview.slice(0, 120) + (meta.preview.length > 120 ? "…" : "")
        : "";
    const previewSnippet = truncatedPreview
        ? `\n\nPreview: ${truncatedPreview}`
        : "";

    closeConversationContextMenu();
    const confirmed = window.confirm(
        `Delete "${title}"? This will permanently remove the conversation.${previewSnippet}`
    );
    if (!confirmed) return;

    try {
        if (activeConversationId === conversationId) {
            activeConversationId = null;
        }
        if (latestConversationId === conversationId) {
            latestConversationId = null;
        }
        conversationCache.delete(conversationId);
        await deleteConversationRequest(conversationId);
        await loadConversations();
    } catch (error) {
        appendMessage(
            "catalyst",
            `<strong>Delete failed:</strong> ${error.message}`
        );
    }
}

function handleConversationContextMenu(event) {
    if (!conversationContextMenu) return;
    const item = event.target.closest(".conversation-item");
    if (!item) return;
    event.preventDefault();
    const { conversationId } = item.dataset;
    if (!conversationId) return;
    closeConversationContextMenu();
    openConversationContextMenu(
        event.clientX,
        event.clientY,
        conversationId,
        item
    );
}

function handleConversationListKeydown(event) {
    const item = event.target.closest(".conversation-item");
    if (!item) return;

    if (event.key === "Delete") {
        event.preventDefault();
        handleDeleteConversation(item.dataset.conversationId);
        return;
    }

    if (
        event.key === "ContextMenu" ||
        (event.shiftKey && event.key === "F10")
    ) {
        event.preventDefault();
        const rect = item.getBoundingClientRect();
        const centerX = rect.left + rect.width / 2;
        const centerY = rect.top + rect.height / 2;
        closeConversationContextMenu();
        openConversationContextMenu(
            centerX,
            centerY,
            item.dataset.conversationId,
            item
        );
    }
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
    const avatar = document.createElement("div");
    avatar.className = "message-avatar";

    const avatarIcon = {
        user: "👤",
        catalyst: "🤖",
        assistant: "🤖",
        system: "🛰️",
        tool: "🛠️",
    };
    avatar.textContent = avatarIcon[role] || "💬";

    const content = document.createElement("div");
    content.className = "message-content";

    const { model, timestamp, sessionType, skipScroll = false } = options;
    const metaParts = [];

    if (model) metaParts.push(model);
    if (timestamp) metaParts.push(formatTimestamp(timestamp));
    if (sessionType) metaParts.push(formatSessionLabel(sessionType));

    if (metaParts.length > 0) {
        const meta = document.createElement("div");
        meta.className = "message-meta";
        meta.textContent = metaParts.join(" • ");
        content.appendChild(meta);
    }

    const body = document.createElement("div");
    body.className = "message-body";
    body.innerHTML = renderMarkdown(text);

    content.appendChild(body);
    article.appendChild(avatar);
    article.appendChild(content);
    chatFeed.appendChild(article);

    if (skipScroll) {
        chatFeed.scrollTop = chatFeed.scrollHeight;
    } else {
        chatFeed.scrollTo({ top: chatFeed.scrollHeight, behavior: "smooth" });
    }
}

function clearChatFeed() {
    chatFeed.innerHTML = "";
}

function renderConversationMessages(messages = []) {
    clearChatFeed();
    messages.forEach((message) => {
        if (!message?.content) return;
        const role = message.role === "assistant" ? "catalyst" : message.role;
        appendMessage(role, message.content, {
            model: message.model,
            timestamp: message.timestamp,
            sessionType: message.session_type,
            skipScroll: true,
        });
    });
    chatFeed.scrollTop = chatFeed.scrollHeight;
}

function setTyping(isActive) {
    typingIndicator.classList.toggle("active", isActive);
}

function setSending(state) {
    isSending = state;
    const disableInputs = state || isReadOnlyConversation;
    sendButton.disabled = disableInputs;
    messageInput.disabled = disableInputs;
    if (previewToggle) previewToggle.disabled = disableInputs;
    if (newConversationButton) {
        newConversationButton.disabled = state;
    }
    setTyping(state);
}

function setReadOnlyMode(state) {
    isReadOnlyConversation = state;
    const disableInputs = state || isSending;
    sendButton.disabled = disableInputs;
    messageInput.disabled = disableInputs;
    if (previewToggle) previewToggle.disabled = disableInputs;
    if (state) {
        latestConversationDraft = messageInput.value;
        messageInput.value = "";
        autoResizeTextarea();
        updateInlinePreview();
    } else {
        if (messageInput.value !== latestConversationDraft) {
            messageInput.value = latestConversationDraft;
            autoResizeTextarea();
            updateInlinePreview();
        }
        if (!isSending) {
            messageInput.focus();
        }
    }
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

function getConversationMeta(conversationId) {
    return conversationsMeta.find(
        (meta) => meta.conversation_id === conversationId
    );
}

function renderConversationList() {
    if (!conversationList) return;

    closeConversationContextMenu();
    conversationList.innerHTML = "";

    conversationsMeta.forEach((meta) => {
        const item = document.createElement("button");
        item.type = "button";
        item.className = "conversation-item";
        item.dataset.conversationId = meta.conversation_id;
        if (meta.conversation_id === activeConversationId) {
            item.classList.add("active");
        }
        if (meta.conversation_id !== latestConversationId) {
            item.classList.add("read-only");
        }

        const title = document.createElement("div");
        title.className = "conversation-title";
        title.textContent = formatConversationTitle(meta);

        const snippet = document.createElement("div");
        snippet.className = "conversation-snippet";
        snippet.textContent = meta.preview || "No summary yet.";

        item.append(title, snippet);

        const metaParts = [];
        if (meta.updated_at) {
            metaParts.push(formatTimestamp(meta.updated_at));
        }
        if (meta.message_count) {
            const count = meta.message_count;
            metaParts.push(`${count} message${count === 1 ? "" : "s"}`);
        }

        if (metaParts.length) {
            const metaLine = document.createElement("div");
            metaLine.className = "conversation-meta";
            metaLine.textContent = metaParts.join(" • ");
            item.appendChild(metaLine);
        }

        conversationList.appendChild(item);
    });

    const hasItems = conversationList.children.length > 0;
    if (conversationEmpty) {
        conversationEmpty.hidden = hasItems;
    }
    conversationList.style.display = hasItems ? "" : "none";
}

async function ensureConversation(
    conversationId,
    { forceReload = false } = {}
) {
    if (!conversationId) return null;
    if (!forceReload && conversationCache.has(conversationId)) {
        return conversationCache.get(conversationId);
    }

    const data = await fetchJSON(
        `${API_BASE_URL}/conversations/${conversationId}`
    );
    conversationCache.set(conversationId, data);
    return data;
}

async function loadConversations() {
    if (!conversationList) return 0;

    try {
        const data = await fetchJSON(`${API_BASE_URL}/conversations`);
        conversationsMeta = data.conversations || [];
        latestConversationId = data.latest_conversation_id || null;
        renderConversationList();

        if (conversationsMeta.length === 0) {
            activeConversationId = null;
            setConversationSummary(null);
            setReadOnlyMode(true);
            clearChatFeed();
            return 0;
        }

        const currentMeta = getConversationMeta(activeConversationId);
        if (!currentMeta) {
            const targetId =
                latestConversationId || conversationsMeta[0].conversation_id;
            await selectConversation(targetId, { forceReload: true });
        } else {
            setConversationSummary(currentMeta);
            setReadOnlyMode(activeConversationId !== latestConversationId);
        }

        return conversationsMeta.length;
    } catch (error) {
        if (conversationEmpty) {
            conversationEmpty.hidden = false;
            conversationEmpty.textContent = `Unable to load conversations (${error.message})`;
        }
        return 0;
    }
}

async function selectConversation(
    conversationId,
    { forceReload = false } = {}
) {
    if (!conversationId) return;

    activeConversationId = conversationId;
    renderConversationList();

    const meta = getConversationMeta(conversationId);
    setConversationSummary(meta || null);

    try {
        const data = await ensureConversation(conversationId, { forceReload });
        if (data?.messages) {
            renderConversationMessages(data.messages);
        } else {
            clearChatFeed();
        }

        if (data?.metadata) {
            const mergedMeta = {
                conversation_id: conversationId,
                preview: meta?.preview || "",
                ...data.metadata,
            };
            setConversationSummary(mergedMeta);
            if (meta) {
                Object.assign(meta, mergedMeta);
            }
        }
    } catch (error) {
        appendMessage(
            "catalyst",
            `<strong>History error:</strong> ${error.message}`
        );
    }

    setReadOnlyMode(conversationId !== latestConversationId);
    renderConversationList();
}

async function startNewConversation() {
    if (isSending) return;
    pendingInitialGreeting = null;
    await generateInitialGreeting();
}

async function sendMessage() {
    if (isSending || isReadOnlyConversation) return;

    const text = messageInput.value.trim();
    if (!text) return;

    const conversationId = activeConversationId || latestConversationId;
    if (!conversationId) {
        await generateInitialGreeting();
        messageInput.value = text;
        latestConversationDraft = text;
        autoResizeTextarea();
        return;
    }

    const userTimestamp = new Date().toISOString();
    appendMessage("user", text, {
        timestamp: userTimestamp,
        sessionType: activeSession,
    });
    messageInput.value = "";
    latestConversationDraft = "";
    autoResizeTextarea();
    setSending(true);

    try {
        const payload = {
            message: text,
            session_type: activeSession,
            conversation_id: conversationId,
        };
        if (pendingInitialGreeting) {
            payload.initial_greeting = { ...pendingInitialGreeting };
        }

        const data = await fetchJSON(`${API_BASE_URL}/chat`, {
            method: "POST",
            body: JSON.stringify(payload),
        });

        const responseTimestamp = new Date().toISOString();
        const responseSession = data.session_type || activeSession;
        appendMessage("catalyst", data.response, {
            model: data.model,
            timestamp: responseTimestamp,
            sessionType: responseSession,
        });

        if (pendingInitialGreeting) {
            pendingInitialGreeting = null;
        }

        activeConversationId = data.conversation_id || conversationId;
        latestConversationId = activeConversationId;
        conversationCache.delete(activeConversationId);
        await loadConversations();
        await selectConversation(activeConversationId, { forceReload: true });

        if (data.memory_updated) {
            await refreshGoalDisplay();
        }
    } catch (error) {
        appendMessage("catalyst", `<strong>System</strong>: ${error.message}`);
    } finally {
        setSending(false);
        if (!isReadOnlyConversation) {
            messageInput.focus();
        }
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

        const timestamp = new Date().toISOString();
        appendMessage("catalyst", data.response, {
            model: data.model,
            timestamp,
            sessionType: data.session_type,
        });
        latestConversationDraft = "";
        initModal.close();
        await refreshGoalDisplay();
        if (data.conversation_id) {
            conversationCache.delete(data.conversation_id);
            activeConversationId = data.conversation_id;
            latestConversationId = data.conversation_id;
            await loadConversations();
            await selectConversation(data.conversation_id, {
                forceReload: true,
            });
        }
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

function autoResizeTextarea() {
    messageInput.style.height = "auto";
    const scrollHeight = messageInput.scrollHeight;
    const minHeight = 44; // ~2.75rem in pixels
    const maxHeight = 200;

    if (scrollHeight > minHeight) {
        messageInput.classList.add("multiline");
        messageInput.style.height = `${Math.min(scrollHeight, maxHeight)}px`;
    } else {
        messageInput.classList.remove("multiline");
        messageInput.style.height = `${minHeight}px`;
    }
}

function handleInputChange() {
    autoResizeTextarea();
    updateInlinePreview();
}

let isPreviewVisible = false;

function toggleInlinePreview() {
    isPreviewVisible = !isPreviewVisible;
    previewToggle.classList.toggle("active", isPreviewVisible);
    inputPreviewPanel.classList.toggle("active", isPreviewVisible);

    if (isPreviewVisible) {
        updateInlinePreview();
    }
}

function updateInlinePreview() {
    if (!isPreviewVisible) return;

    const text = messageInput.value.trim();
    if (text) {
        inputPreviewPanel.innerHTML = renderMarkdown(text);
    } else {
        inputPreviewPanel.innerHTML =
            '<em style="color: var(--text-muted);">Preview will appear here...</em>';
    }
}

function showPreview() {
    // Fallback for modal preview if it exists
    if (previewModal && previewContent) {
        const text = messageInput.value.trim();
        if (!text) {
            previewContent.innerHTML =
                '<em style="color: #64748b;">Nothing to preview...</em>';
        } else {
            previewContent.innerHTML = renderMarkdown(text);
        }
        previewModal.showModal();
    }
}

function closePreview() {
    if (previewModal) {
        previewModal.close();
    }
    messageInput.focus();
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
    messageInput.addEventListener("input", handleInputChange);

    // Inline preview toggle
    previewToggle.addEventListener("click", toggleInlinePreview);

    // Keep old modal functionality for compatibility
    if (closePreviewBtn)
        closePreviewBtn.addEventListener("click", closePreview);
    if (editButton) editButton.addEventListener("click", closePreview);
    if (sendFromPreviewButton) {
        sendFromPreviewButton.addEventListener("click", () => {
            previewModal.close();
            sendMessage();
        });
    }

    // Close preview modal when clicking outside
    previewModal.addEventListener("click", (event) => {
        if (event.target === previewModal) {
            closePreview();
        }
    });

    // Escape key to close preview or context menu
    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            if (previewModal.open) {
                closePreview();
            }
            closeConversationContextMenu();
        }
    });

    sessionButtons.forEach((button) =>
        button.addEventListener("click", handleSessionClick)
    );

    initButton.addEventListener("click", (event) => {
        event.preventDefault();
        initializeCatalyst();
    });

    if (conversationList) {
        conversationList.addEventListener("click", (event) => {
            closeConversationContextMenu();
            const item = event.target.closest(".conversation-item");
            if (!item) return;
            const { conversationId } = item.dataset;
            if (!conversationId || conversationId === activeConversationId)
                return;
            selectConversation(conversationId);
        });

        conversationList.addEventListener(
            "contextmenu",
            handleConversationContextMenu
        );
        conversationList.addEventListener(
            "keydown",
            handleConversationListKeydown
        );
        conversationList.addEventListener(
            "scroll",
            closeConversationContextMenu
        );
    }

    if (newConversationButton) {
        newConversationButton.addEventListener("click", (event) => {
            event.preventDefault();
            startNewConversation();
        });
    }

    if (sidebarToggle && sidebar) {
        sidebarToggle.addEventListener("click", (event) => {
            event.preventDefault();
            sidebar.classList.toggle("collapsed");
            const isCollapsed = sidebar.classList.contains("collapsed");
            sidebarToggle.innerHTML = `<span aria-hidden="true">${
                isCollapsed ? "▶" : "◀"
            }</span>`;
            sidebarToggle.title = isCollapsed
                ? "Expand sidebar"
                : "Collapse sidebar";
        });
    }

    if (conversationContextMenu) {
        conversationContextMenu.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-action]");
            if (!button) return;
            const { action } = button.dataset;
            const targetId = contextMenuTargetId;
            if (action === "delete" && targetId) {
                event.preventDefault();
                handleDeleteConversation(targetId);
            }
        });
    }

    document.addEventListener("pointerdown", (event) => {
        if (!conversationContextMenu || conversationContextMenu.hidden) return;
        if (
            conversationContextMenu.contains(event.target) ||
            (contextMenuTargetElement &&
                contextMenuTargetElement.contains(event.target))
        ) {
            return;
        }
        closeConversationContextMenu();
    });

    window.addEventListener("blur", closeConversationContextMenu);
    window.addEventListener("resize", closeConversationContextMenu);
    window.addEventListener("scroll", closeConversationContextMenu, true);
}

async function generateInitialGreeting() {
    try {
        setSending(true);
        const data = await fetchJSON(`${API_BASE_URL}/initial-greeting`, {
            method: "POST",
            body: JSON.stringify({ session_type: activeSession }),
        });
        const timestamp = new Date().toISOString();
        appendMessage("catalyst", data.response, {
            model: data.model,
            timestamp,
            sessionType: data.session_type,
        });
        pendingInitialGreeting = {
            text: data.response,
            session_type: data.session_type || activeSession,
            model: data.model || null,
            timestamp,
            conversation_id: data.conversation_id || null,
        };
        latestConversationDraft = "";
        if (data.conversation_id) {
            activeConversationId = data.conversation_id;
            latestConversationId = data.conversation_id;
            conversationCache.delete(data.conversation_id);
            await loadConversations();
            await selectConversation(data.conversation_id, {
                forceReload: true,
            });
        }
    } catch (error) {
        appendMessage("catalyst", `<strong>System</strong>: ${error.message}`);
        pendingInitialGreeting = null;
    } finally {
        setSending(false);
        if (pendingInitialGreeting && !isReadOnlyConversation) {
            setReadOnlyMode(false);
        }
    }
}

async function init() {
    setActiveSession(determineSessionTypeByLocalTime());
    bindEvents();
    autoResizeTextarea(); // Set initial height
    const hasGoal = await refreshGoalDisplay();
    const conversationCount = await loadConversations();
    if (!hasGoal) {
        appendMessage(
            "catalyst",
            "I don't see your North Star goal yet. Let's set it now so I can tailor our sessions."
        );
        setReadOnlyMode(true);
    } else if (conversationCount === 0) {
        await generateInitialGreeting();
    } else if (activeConversationId) {
        await selectConversation(activeConversationId);
    }
    messageInput.focus();
}

window.addEventListener("DOMContentLoaded", init);
