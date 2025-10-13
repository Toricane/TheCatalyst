import createDOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.2.7/dist/purify.es.mjs";
import { marked } from "https://cdn.jsdelivr.net/npm/marked@12.0.2/lib/marked.esm.js";

const DOMPurify = createDOMPurify(window);

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
const messageContextMenu = document.getElementById("messageContextMenu");
const systemContextModal = document.getElementById("systemContextModal");
const systemContextContent = document.getElementById("systemContextContent");
const closeSystemContextBtn = document.getElementById("closeSystemContextBtn");
const copySystemContextBtn = document.getElementById("copySystemContextBtn");

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
const shareButton = document.getElementById("shareConversationButton");
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
let messageContextTargetElement = null;
const messageDebugData = new WeakMap();
let currentDebugClipboardText = "";
let isExportingConversation = false;

if (copySystemContextBtn) {
    copySystemContextBtn.disabled = true;
}

function determineSessionTypeByLocalTime() {
    const hour = new Date().getHours();
    if (hour >= 4 && hour < 12) return "morning";
    if ((hour >= 20 && hour < 24) || (hour >= 0 && hour < 4)) return "evening";
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

function normalizeDebugInfo(raw) {
    if (!raw) return null;

    const systemPromptSource =
        typeof raw.system_prompt === "string"
            ? raw.system_prompt
            : typeof raw.systemPrompt === "string"
            ? raw.systemPrompt
            : "";

    let contextSnapshot =
        raw.context_snapshot !== undefined
            ? raw.context_snapshot
            : raw.contextSnapshot !== undefined
            ? raw.contextSnapshot
            : null;

    const contextReference =
        raw.context_reference !== undefined
            ? raw.context_reference
            : raw.contextReference !== undefined
            ? raw.contextReference
            : null;

    const systemPromptReferenceRaw =
        raw.system_prompt_reference !== undefined
            ? raw.system_prompt_reference
            : raw.systemPromptReference !== undefined
            ? raw.systemPromptReference
            : null;

    let systemPromptReference = systemPromptReferenceRaw;
    if (typeof systemPromptReference === "string") {
        try {
            systemPromptReference = JSON.parse(systemPromptReference);
        } catch (error) {
            // leave as string if parsing fails
        }
    }

    const conversationId =
        raw.conversation_id !== undefined
            ? raw.conversation_id
            : raw.conversationId !== undefined
            ? raw.conversationId
            : null;

    const messageId =
        raw.message_id !== undefined
            ? raw.message_id
            : raw.messageId !== undefined
            ? raw.messageId
            : null;

    if (typeof contextSnapshot === "string") {
        const trimmed = contextSnapshot.trim();
        if (
            (trimmed.startsWith("{") && trimmed.endsWith("}")) ||
            (trimmed.startsWith("[") && trimmed.endsWith("]"))
        ) {
            try {
                contextSnapshot = JSON.parse(trimmed);
            } catch (error) {
                // keep string if parsing fails
            }
        }
    }

    const hasPrompt =
        typeof systemPromptSource === "string" &&
        systemPromptSource.trim().length > 0;

    const hasContext = (() => {
        if (contextSnapshot === null || contextSnapshot === undefined) {
            return false;
        }
        if (Array.isArray(contextSnapshot)) {
            return contextSnapshot.length > 0;
        }
        if (typeof contextSnapshot === "object") {
            return Object.keys(contextSnapshot).length > 0;
        }
        if (typeof contextSnapshot === "string") {
            return contextSnapshot.trim().length > 0;
        }
        return true;
    })();

    const hasReference = (() => {
        if (contextReference === null || contextReference === undefined) {
            return false;
        }
        if (Array.isArray(contextReference)) {
            return contextReference.length > 0;
        }
        if (typeof contextReference === "object") {
            return Object.keys(contextReference).length > 0;
        }
        if (typeof contextReference === "string") {
            return contextReference.trim().length > 0;
        }
        return true;
    })();

    const hasSystemPromptReference = (() => {
        if (
            systemPromptReference === null ||
            systemPromptReference === undefined
        ) {
            return false;
        }
        if (Array.isArray(systemPromptReference)) {
            return systemPromptReference.length > 0;
        }
        if (typeof systemPromptReference === "object") {
            return Object.keys(systemPromptReference).length > 0;
        }
        if (typeof systemPromptReference === "string") {
            return systemPromptReference.trim().length > 0;
        }
        return true;
    })();

    if (!hasPrompt && !hasContext && !hasReference) {
        return null;
    }

    return {
        systemPrompt: hasPrompt ? systemPromptSource : "",
        contextSnapshot,
        contextReference,
        systemPromptReference,
        conversationId,
        messageId,
    };
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

    closeMessageContextMenu();

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

function closeMessageContextMenu() {
    if (messageContextMenu && !messageContextMenu.hidden) {
        messageContextMenu.hidden = true;
        messageContextMenu.setAttribute("aria-hidden", "true");
        messageContextMenu.style.removeProperty("left");
        messageContextMenu.style.removeProperty("top");
    }
    if (messageContextTargetElement) {
        messageContextTargetElement.classList.remove("menu-open");
        messageContextTargetElement = null;
    }
}

function openMessageContextMenu(x, y, messageElement) {
    if (!messageContextMenu || !messageElement) return;

    closeConversationContextMenu();

    if (
        messageContextTargetElement &&
        messageContextTargetElement !== messageElement
    ) {
        messageContextTargetElement.classList.remove("menu-open");
    }

    messageContextTargetElement = messageElement;
    messageContextTargetElement.classList.add("menu-open");

    const debugInfo = messageDebugData.get(messageElement) || null;
    const viewButton = messageContextMenu.querySelector(
        "button[data-action='view-debug']"
    );
    const debugAvailable = Boolean(debugInfo);
    if (viewButton) {
        viewButton.disabled = !debugAvailable;
        viewButton.setAttribute(
            "aria-disabled",
            debugAvailable ? "false" : "true"
        );
    }

    messageContextMenu.hidden = false;
    messageContextMenu.setAttribute("aria-hidden", "false");
    messageContextMenu.style.left = "0px";
    messageContextMenu.style.top = "0px";

    const rect = messageContextMenu.getBoundingClientRect();
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

    messageContextMenu.style.left = `${posX}px`;
    messageContextMenu.style.top = `${posY}px`;

    const focusable = messageContextMenu.querySelector("button:not(:disabled)");
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

function handleMessageContextMenu(event) {
    if (!messageContextMenu) return;
    const messageElement = event.target.closest("article.message.catalyst");
    if (!messageElement) return;
    event.preventDefault();
    closeMessageContextMenu();
    openMessageContextMenu(event.clientX, event.clientY, messageElement);
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

    const {
        model,
        timestamp,
        sessionType,
        skipScroll = false,
        debugInfo = null,
    } = options;
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

    if (debugInfo && role === "catalyst") {
        messageDebugData.set(article, debugInfo);
        article.classList.add("has-debug");
    }

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
        const debugInfo = normalizeDebugInfo(message);
        appendMessage(role, message.content, {
            model: message.model,
            timestamp: message.timestamp,
            sessionType: message.session_type,
            skipScroll: true,
            debugInfo,
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

    refreshShareButtonState();
}

function refreshShareButtonState() {
    if (!shareButton) return;
    const hasConversation = Boolean(activeConversationId);
    shareButton.disabled = !hasConversation || isExportingConversation;
    shareButton.title = hasConversation
        ? "Copy this conversation as Markdown"
        : "Select a conversation to share";
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

async function fetchMessageContext(conversationId, messageId) {
    const response = await fetch(
        `${API_BASE_URL}/conversations/${conversationId}/messages/${messageId}/context`
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

    return response.json();
}

async function shareActiveConversation() {
    if (!shareButton || !activeConversationId || isExportingConversation) {
        return;
    }

    isExportingConversation = true;
    shareButton.classList.add("loading");
    const label = shareButton.querySelector(".btn-label");
    const originalLabel = label ? label.textContent : shareButton.textContent;
    if (label) {
        label.textContent = "Copying…";
    } else {
        shareButton.textContent = "Copying…";
    }
    refreshShareButtonState();

    try {
        if (!navigator.clipboard || !navigator.clipboard.writeText) {
            throw new Error("Clipboard API unavailable in this browser");
        }

        const response = await fetch(
            `${API_BASE_URL}/conversations/${activeConversationId}/export`
        );

        if (!response.ok) {
            let detail = response.statusText;
            try {
                const data = await response.clone().json();
                detail = data.detail || JSON.stringify(data);
            } catch (jsonError) {
                try {
                    detail = await response.clone().text();
                } catch (textError) {
                    detail = `${response.status} ${response.statusText}`;
                }
            }
            throw new Error(detail);
        }

        const markdown = await response.text();

        await navigator.clipboard.writeText(markdown);

        const toast = document.createElement("div");
        toast.className = "toast-notification";
        toast.textContent = "Conversation copied to clipboard";
        document.body.appendChild(toast);
        setTimeout(() => {
            toast.classList.add("visible");
        }, 10);
        setTimeout(() => {
            toast.classList.remove("visible");
            setTimeout(() => {
                toast.remove();
            }, 300);
        }, 2500);
    } catch (error) {
        appendMessage(
            "catalyst",
            `<strong>Share failed:</strong> ${error.message}`
        );
    } finally {
        if (label) {
            label.textContent = originalLabel;
        } else {
            shareButton.textContent = originalLabel || "Share";
        }
        shareButton.classList.remove("loading");
        isExportingConversation = false;
        refreshShareButtonState();
    }
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
    refreshShareButtonState();
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
        const debugInfo = normalizeDebugInfo(data);
        appendMessage("catalyst", data.response, {
            model: data.model,
            timestamp: responseTimestamp,
            sessionType: responseSession,
            debugInfo,
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
        const debugInfo = normalizeDebugInfo(data);
        appendMessage("catalyst", data.response, {
            model: data.model,
            timestamp,
            sessionType: data.session_type,
            debugInfo,
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

async function openSystemContextModal(debugInfo) {
    closeMessageContextMenu();

    const conversationId = debugInfo?.conversationId ?? null;
    const messageId = debugInfo?.messageId ?? null;

    let systemPromptText = debugInfo?.systemPrompt ?? "";
    let contextData = debugInfo?.contextSnapshot ?? null;
    let contextReference = debugInfo?.contextReference ?? null;
    let systemPromptReference = debugInfo?.systemPromptReference ?? null;

    let systemPromptRuntimeBase = null;
    let systemPromptChecksumMatch = null;

    const hasValue = (value) => {
        if (value === null || value === undefined) return false;
        if (typeof value === "string") return value.trim().length > 0;
        if (Array.isArray(value)) return value.length > 0;
        if (typeof value === "object") return Object.keys(value).length > 0;
        return true;
    };

    const shouldFetchRemote =
        conversationId &&
        messageId &&
        ((hasValue(contextReference) && !hasValue(contextData)) ||
            (hasValue(systemPromptReference) && !hasValue(systemPromptText)));

    if (shouldFetchRemote) {
        try {
            if (systemContextModal && systemContextContent) {
                systemContextContent.innerHTML =
                    '<p class="debug-loading">Loading context&hellip;</p>';
                if (!systemContextModal.open) {
                    systemContextModal.showModal();
                }
            }

            const fetched = await fetchMessageContext(
                conversationId,
                messageId
            );

            if (fetched?.context !== undefined) {
                contextData = fetched.context;
            } else if (
                !hasValue(contextData) &&
                fetched?.snapshot !== undefined
            ) {
                contextData = fetched.snapshot;
            }

            if (!hasValue(contextReference) && fetched?.reference) {
                contextReference = fetched.reference;
            }

            if (!hasValue(systemPromptText) && fetched?.system_prompt) {
                systemPromptText = fetched.system_prompt;
            }

            if (fetched?.system_prompt_reference) {
                systemPromptReference = fetched.system_prompt_reference;
            }

            if (fetched?.system_prompt_runtime_base) {
                systemPromptRuntimeBase = fetched.system_prompt_runtime_base;
            }

            if (fetched?.system_prompt_checksum_match !== undefined) {
                systemPromptChecksumMatch =
                    fetched.system_prompt_checksum_match;
            }
        } catch (error) {
            contextData = {
                error: error.message || "Unable to retrieve context metadata.",
            };
        }
    }

    const hasPrompt = hasValue(systemPromptText);
    const hasContext = hasValue(contextData);
    const hasContextReference = hasValue(contextReference);
    const hasPromptReference = hasValue(systemPromptReference);

    if (
        !hasPrompt &&
        !hasContext &&
        !hasContextReference &&
        !hasPromptReference
    ) {
        window.alert(
            "No system prompt, context snapshot, or reference metadata is available for this message."
        );
        return;
    }

    const normalizeToString = (value) => {
        if (value === null || value === undefined) return "";
        if (typeof value === "string") return value;
        try {
            return JSON.stringify(value, null, 2);
        } catch (error) {
            return String(value);
        }
    };

    const formatMarkdown = (value, { preferCodeBlock = false } = {}) => {
        const rawText = String(value ?? "");
        const trimmed = rawText.trim();
        if (!trimmed) {
            return "_No details were captured for this section._";
        }
        if (
            preferCodeBlock &&
            !rawText.includes("```") &&
            /^[\[{]/.test(trimmed)
        ) {
            return `\`\`\`json\n${rawText}\n\`\`\``;
        }
        return rawText;
    };

    if (debugInfo && typeof debugInfo === "object") {
        debugInfo.systemPrompt = systemPromptText;
        debugInfo.contextSnapshot = contextData;
        debugInfo.contextReference = contextReference;
        debugInfo.systemPromptReference = systemPromptReference;
    }

    const promptText = hasPrompt
        ? systemPromptText
        : "No system instructions were captured for this message.";
    const contextText = hasContext
        ? normalizeToString(contextData)
        : "No context snapshot was captured for this message.";
    const contextReferenceText = hasContextReference
        ? normalizeToString(contextReference)
        : "No context reference metadata was stored for this message.";

    const promptReferencePayload = (() => {
        if (!hasPromptReference) {
            return "No system prompt reference metadata was stored for this message.";
        }

        if (systemPromptRuntimeBase || systemPromptChecksumMatch !== null) {
            return normalizeToString({
                reference: systemPromptReference,
                runtime_base: systemPromptRuntimeBase || undefined,
                checksum_match: systemPromptChecksumMatch,
            });
        }

        return normalizeToString(systemPromptReference);
    })();

    const clipboardSections = [];
    if (hasPrompt) {
        clipboardSections.push(
            "=== System Instructions ===\n".concat(
                normalizeToString(systemPromptText)
            )
        );
    }
    if (hasContext) {
        clipboardSections.push(
            "=== Context Snapshot ===\n".concat(normalizeToString(contextData))
        );
    }
    if (hasContextReference) {
        clipboardSections.push(
            "=== Context Reference ===\n".concat(
                normalizeToString(contextReference)
            )
        );
    }
    if (hasPromptReference) {
        clipboardSections.push(
            "=== System Prompt Reference ===\n".concat(promptReferencePayload)
        );
    }

    currentDebugClipboardText = clipboardSections.join("\n\n");

    const fallbackBody = [
        `System Instructions:\n${promptText}`,
        `Context Snapshot:\n${contextText}`,
        `Context Reference:\n${contextReferenceText}`,
        `System Prompt Reference:\n${promptReferencePayload}`,
    ].join("\n\n");

    if (!systemContextModal || !systemContextContent) {
        window.alert(fallbackBody);
        return;
    }

    const makeSection = (title, text, options = {}) => {
        const wrapper = document.createElement("section");
        wrapper.className = "debug-section";

        const heading = document.createElement("h3");
        heading.textContent = title;
        wrapper.appendChild(heading);

        const body = document.createElement("div");
        body.className = "debug-markdown";
        body.innerHTML = renderMarkdown(formatMarkdown(text, options));
        wrapper.appendChild(body);

        return wrapper;
    };

    systemContextContent.innerHTML = "";
    systemContextContent.appendChild(
        makeSection("System Instructions", promptText)
    );
    systemContextContent.appendChild(
        makeSection("Context Snapshot", contextText, { preferCodeBlock: true })
    );
    systemContextContent.appendChild(
        makeSection("Context Reference", contextReferenceText, {
            preferCodeBlock: true,
        })
    );
    systemContextContent.appendChild(
        makeSection("System Prompt Reference", promptReferencePayload, {
            preferCodeBlock: true,
        })
    );

    if (copySystemContextBtn) {
        copySystemContextBtn.disabled = clipboardSections.length === 0;
        copySystemContextBtn.textContent = "Copy to clipboard";
    }

    if (!systemContextModal.open) {
        systemContextModal.showModal();
    }
}

async function copyDebugDetailsToClipboard() {
    if (!copySystemContextBtn) return;
    if (!currentDebugClipboardText) {
        copySystemContextBtn.textContent = "Nothing to copy";
        setTimeout(() => {
            copySystemContextBtn.textContent = "Copy to clipboard";
        }, 2000);
        return;
    }
    try {
        await navigator.clipboard.writeText(currentDebugClipboardText);
        copySystemContextBtn.textContent = "Copied!";
    } catch (error) {
        copySystemContextBtn.textContent = "Copy failed";
    }
    setTimeout(() => {
        copySystemContextBtn.textContent = "Copy to clipboard";
    }, 2000);
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
            closeMessageContextMenu();
            if (systemContextModal?.open) {
                systemContextModal.close();
            }
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
            closeMessageContextMenu();
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
        conversationList.addEventListener("scroll", () => {
            closeConversationContextMenu();
            closeMessageContextMenu();
        });
    }

    if (chatFeed) {
        chatFeed.addEventListener("contextmenu", handleMessageContextMenu);
        chatFeed.addEventListener("scroll", closeMessageContextMenu);
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

    if (messageContextMenu) {
        messageContextMenu.addEventListener("click", (event) => {
            const button = event.target.closest("button[data-action]");
            if (!button) return;
            const { action } = button.dataset;
            if (action === "view-debug") {
                event.preventDefault();
                const debugInfo = messageContextTargetElement
                    ? messageDebugData.get(messageContextTargetElement) || null
                    : null;
                if (!debugInfo) {
                    window.alert(
                        "No debug information is available for this message."
                    );
                    return;
                }
                openSystemContextModal(debugInfo).catch((error) => {
                    window.alert(
                        `Unable to load debug context: ${error.message}`
                    );
                });
            }
        });
    }

    if (shareButton) {
        shareButton.addEventListener("click", (event) => {
            event.preventDefault();
            shareActiveConversation();
        });
    }

    if (closeSystemContextBtn) {
        closeSystemContextBtn.addEventListener("click", () => {
            systemContextModal?.close();
        });
    }

    if (systemContextModal) {
        systemContextModal.addEventListener("close", () => {
            currentDebugClipboardText = "";
            if (copySystemContextBtn) {
                copySystemContextBtn.textContent = "Copy to clipboard";
                copySystemContextBtn.disabled = true;
            }
        });
    }

    if (copySystemContextBtn) {
        copySystemContextBtn.addEventListener(
            "click",
            copyDebugDetailsToClipboard
        );
    }

    document.addEventListener("pointerdown", (event) => {
        const insideConversationMenu =
            conversationContextMenu &&
            !conversationContextMenu.hidden &&
            (conversationContextMenu.contains(event.target) ||
                (contextMenuTargetElement &&
                    contextMenuTargetElement.contains(event.target)));
        if (!insideConversationMenu) {
            closeConversationContextMenu();
        }

        const insideMessageMenu =
            messageContextMenu &&
            !messageContextMenu.hidden &&
            (messageContextMenu.contains(event.target) ||
                (messageContextTargetElement &&
                    messageContextTargetElement.contains(event.target)));
        if (!insideMessageMenu) {
            closeMessageContextMenu();
        }
    });

    const closeMenus = () => {
        closeConversationContextMenu();
        closeMessageContextMenu();
    };

    window.addEventListener("blur", closeMenus);
    window.addEventListener("resize", closeMenus);
    window.addEventListener("scroll", closeMenus, true);

    refreshShareButtonState();
}

async function generateInitialGreeting() {
    try {
        setSending(true);
        const data = await fetchJSON(`${API_BASE_URL}/initial-greeting`, {
            method: "POST",
            body: JSON.stringify({ session_type: activeSession }),
        });
        const timestamp = new Date().toISOString();
        const debugInfo = normalizeDebugInfo(data);
        appendMessage("catalyst", data.response, {
            model: data.model,
            timestamp,
            sessionType: data.session_type,
            debugInfo,
        });
        pendingInitialGreeting = {
            text: data.response,
            session_type: data.session_type || activeSession,
            model: data.model || null,
            timestamp,
            conversation_id: data.conversation_id || null,
            system_prompt: data.system_prompt || null,
            system_prompt_reference: data.system_prompt_reference || null,
            context_snapshot: data.context_snapshot || null,
            context_reference: data.context_reference || null,
            message_id: data.message_id || null,
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
