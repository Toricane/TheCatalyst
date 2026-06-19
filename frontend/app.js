import createDOMPurify from "https://cdn.jsdelivr.net/npm/dompurify@3.2.7/dist/purify.es.mjs";
import { marked } from "https://cdn.jsdelivr.net/npm/marked@12.0.2/lib/marked.esm.js";

const DOMPurify = createDOMPurify(window);

function renderMarkdown(text = "") {
    const normalized = String(text ?? "").replace(/\r\n/g, "\n");
    const parsed = marked.parse(normalized);
    return DOMPurify.sanitize(parsed);
}

const markdownPlainTextEl = document.createElement("div");

function markdownToHtml(text = "") {
    return renderMarkdown(String(text ?? ""));
}

function plainTextFromMarkdown(text = "") {
    const source = String(text ?? "").trim();
    if (!source) return "";
    markdownPlainTextEl.innerHTML = markdownToHtml(source);
    return (markdownPlainTextEl.textContent || "").replace(/\s+/g, " ").trim();
}

function markdownBlock(text = "", extraClass = "") {
    const source = String(text ?? "").trim();
    if (!source) return "";
    const classes = ["markdown-content", extraClass].filter(Boolean).join(" ");
    return `<div class="${classes}">${markdownToHtml(source)}</div>`;
}

function formatGoalSummary(goal) {
    if (!goal) return "";
    const parts = [
        plainTextFromMarkdown(goal.description),
        plainTextFromMarkdown(goal.metric) || "No metric",
        plainTextFromMarkdown(goal.timeline) || "No timeline",
    ];
    return parts.filter(Boolean).join(" • ");
}

function buildNorthStarCard(goal, emptyMessage) {
    if (!goal) {
        return `<p class="empty-state">${escapeHtml(emptyMessage)}</p>`;
    }
    const meta = `${escapeHtml(goal.metric || "No metric")} • ${escapeHtml(goal.timeline || "No timeline")}`;
    return `
        <div class="north-star-card">
            ${markdownBlock(goal.description, "compact")}
            <p class="goal-meta">${meta}</p>
        </div>
    `;
}

function buildInsightsList(insights, emptyMessage) {
    if (!insights?.length) {
        return `<p class="empty-state">${escapeHtml(emptyMessage)}</p>`;
    }
    return `<div class="insight-list">${insights
        .map(
            (insight) => `
        <article class="insight-card">
            <div class="insight-card-header">
                <span class="insight-type">${escapeHtml(insight.insight_type || "insight")}</span>
                ${buildImportanceDots(insight.importance_score)}
            </div>
            ${markdownBlock(insight.description, "compact")}
        </article>`
        )
        .join("")}</div>`;
}

const TOON_HEADER_PATTERN = /^\w[\w.]*\[\d+\]\{[^}]+\}:$/;
const TOON_KV_PATTERN = /^(session|date|missed):/;

function wrapInlineToonBlocks(text = "") {
    const lines = String(text ?? "").split("\n");
    const output = [];
    let index = 0;

    while (index < lines.length) {
        const line = lines[index];
        const trimmed = line.trim();

        if (TOON_HEADER_PATTERN.test(trimmed)) {
            const block = [line];
            index += 1;
            while (
                index < lines.length &&
                (/^  \S/.test(lines[index]) || lines[index].trim() === "")
            ) {
                if (lines[index].trim()) {
                    block.push(lines[index]);
                }
                index += 1;
            }
            output.push("```toon", ...block, "```");
            continue;
        }

        if (TOON_KV_PATTERN.test(trimmed)) {
            const block = [];
            while (
                index < lines.length &&
                TOON_KV_PATTERN.test(lines[index].trim())
            ) {
                block.push(lines[index]);
                index += 1;
            }
            output.push("```toon", ...block, "```");
            continue;
        }

        output.push(line);
        index += 1;
    }

    return output.join("\n");
}

function extractContextStats(reference) {
    if (!reference || typeof reference !== "object") {
        return null;
    }

    const stats = {};
    if (reference.context_format) {
        stats.format = reference.context_format;
    }
    if (reference.context_chars != null) {
        stats.chars = reference.context_chars;
    }
    if (reference.estimated_context_tokens != null) {
        stats.tokens = reference.estimated_context_tokens;
    }
    if (reference.session_type) {
        stats.session = reference.session_type;
    }
    if (reference.generated_at) {
        stats.generatedAt = reference.generated_at;
    }
    return Object.keys(stats).length > 0 ? stats : null;
}

function formatContextStatsSummary(stats, checksumMatch = null) {
    if (!stats && checksumMatch === null) {
        return "";
    }

    const parts = [];
    if (stats?.format) {
        parts.push(`Format: ${stats.format}`);
    }
    if (stats?.tokens != null) {
        parts.push(`~${stats.tokens} context tokens`);
    }
    if (stats?.chars != null) {
        parts.push(`${stats.chars} context chars`);
    }
    if (stats?.session) {
        parts.push(`Session: ${stats.session}`);
    }
    if (checksumMatch === true) {
        parts.push("Base prompt checksum: match");
    } else if (checksumMatch === false) {
        parts.push("Base prompt checksum: drifted");
    }
    return parts.join(" • ");
}

function formatDebugContent(text, options = {}) {
    const { preferCodeBlock = false, wrapToon = false } = options;
    let rawText = String(text ?? "");
    const trimmed = rawText.trim();

    if (!trimmed) {
        return "_No details were captured for this section._";
    }

    if (wrapToon && (rawText.includes("goals[") || rawText.includes("insights["))) {
        rawText = wrapInlineToonBlocks(rawText);
    }

    if (
        preferCodeBlock &&
        !rawText.includes("```") &&
        /^[\[{]/.test(trimmed)
    ) {
        return `\`\`\`json\n${rawText}\n\`\`\``;
    }

    return rawText;
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
const goalBadge = document.getElementById("goalBadge");
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
const goalsModal =
    document.getElementById("goalsModal") ||
    document.getElementById("initModal");
const goalsInitView = document.getElementById("goalsInitView");
const goalsEditView = document.getElementById("goalsEditView");
const goalsList = document.getElementById("goalsList");
const initButton = document.getElementById("initButton");
const closeGoalsButton = document.getElementById("closeGoalsButton");
const addGoalButton = document.getElementById("addGoalButton");
const newGoalDescription = document.getElementById("newGoalDescription");
const newGoalMetric = document.getElementById("newGoalMetric");
const newGoalTimeline = document.getElementById("newGoalTimeline");
const statsButton = document.getElementById("statsButton");
const settingsButton = document.getElementById("settingsButton");
const statsModal = document.getElementById("statsModal");
const statsContent = document.getElementById("statsContent");
const closeStatsBtn = document.getElementById("closeStatsBtn");
const settingsModal = document.getElementById("settingsModal");
const settingsContent = document.getElementById("settingsContent");
const closeSettingsBtn = document.getElementById("closeSettingsBtn");
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
let cachedGoalsData = null;

function escapeHtml(value = "") {
    return String(value)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;");
}

function showGoalsInitView() {
    if (goalsInitView) goalsInitView.hidden = false;
    if (goalsEditView) goalsEditView.hidden = true;
}

function showGoalsEditView() {
    if (goalsInitView) goalsInitView.hidden = true;
    if (goalsEditView) goalsEditView.hidden = false;
}

function openGoalsModal(mode = "auto") {
    if (!goalsModal) return;

    const hasGoals = Boolean(cachedGoalsData?.total);
    if (mode === "init" || (!hasGoals && mode === "auto")) {
        showGoalsInitView();
    } else {
        showGoalsEditView();
        renderGoalsList().catch((error) => {
            window.alert(`Could not load goals: ${error.message}`);
        });
    }
    if (!goalsModal.open) {
        goalsModal.showModal();
    }
}

async function loadGoalsData() {
    const data = await fetchJSON(`${API_BASE_URL}/goals`);
    cachedGoalsData = data;
    return data;
}

function buildGoalCard(goal) {
    const card = document.createElement("article");
    card.className = `goal-card${goal.rank === 1 ? " north-star" : ""}`;
    card.dataset.goalId = String(goal.id);
    card.setAttribute("role", "listitem");

    const header = document.createElement("div");
    header.className = "goal-card-header";
    header.innerHTML = goal.rank === 1
        ? '<span class="goal-card-badge">North Star</span>'
        : `<span class="goal-card-badge">Rank ${goal.rank}</span>`;

    const descriptionField = document.createElement("label");
    descriptionField.className = "field";
    descriptionField.innerHTML = "<span>Description</span>";
    const descriptionInput = document.createElement("textarea");
    descriptionInput.rows = 2;
    descriptionInput.value = goal.description || "";
    descriptionField.appendChild(descriptionInput);

    const metaRow = document.createElement("div");
    metaRow.className = "goals-add-row";

    const metricField = document.createElement("label");
    metricField.className = "field";
    metricField.innerHTML = "<span>Metric</span>";
    const metricInput = document.createElement("input");
    metricInput.type = "text";
    metricInput.value = goal.metric || "";
    metricField.appendChild(metricInput);

    const timelineField = document.createElement("label");
    timelineField.className = "field";
    timelineField.innerHTML = "<span>Timeline</span>";
    const timelineInput = document.createElement("input");
    timelineInput.type = "text";
    timelineInput.value = goal.timeline || "";
    timelineField.appendChild(timelineInput);

    metaRow.append(metricField, timelineField);

    const actions = document.createElement("div");
    actions.className = "goal-card-actions";

    const saveButton = document.createElement("button");
    saveButton.type = "button";
    saveButton.textContent = "Save";
    saveButton.addEventListener("click", () => {
        saveGoalCard(goal.id, {
            description: descriptionInput.value,
            metric: metricInput.value,
            timeline: timelineInput.value,
        }).catch((error) => {
            window.alert(`Could not save goal: ${error.message}`);
        });
    });

    actions.appendChild(saveButton);

    if (goal.rank !== 1) {
        const promoteButton = document.createElement("button");
        promoteButton.type = "button";
        promoteButton.textContent = "Set as North Star";
        promoteButton.addEventListener("click", () => {
            updateGoal(goal.id, { rank: 1 }).catch((error) => {
                window.alert(`Could not promote goal: ${error.message}`);
            });
        });
        actions.appendChild(promoteButton);

        const deactivateButton = document.createElement("button");
        deactivateButton.type = "button";
        deactivateButton.className = "destructive";
        deactivateButton.textContent = "Deactivate";
        deactivateButton.addEventListener("click", () => {
            if (!window.confirm("Deactivate this sub-goal?")) return;
            updateGoal(goal.id, { is_active: false }).catch((error) => {
                window.alert(`Could not deactivate goal: ${error.message}`);
            });
        });
        actions.appendChild(deactivateButton);
    }

    card.append(header, descriptionField, metaRow, actions);
    return card;
}

async function renderGoalsList() {
    if (!goalsList) return;
    const data = await loadGoalsData();
    goalsList.innerHTML = "";
    if (!data.goals?.length) {
        goalsList.innerHTML =
            '<p class="empty-state">No active goals yet. Set your North Star to begin.</p>';
        return;
    }
    data.goals.forEach((goal) => {
        goalsList.appendChild(buildGoalCard(goal));
    });
}

async function updateGoal(goalId, payload) {
    await fetchJSON(`${API_BASE_URL}/goals/${goalId}`, {
        method: "PUT",
        body: JSON.stringify(payload),
    });
    await refreshGoalDisplay();
    if (goalsModal?.open && goalsEditView && !goalsEditView.hidden) {
        await renderGoalsList();
    }
}

async function saveGoalCard(goalId, fields) {
    const description = fields.description.trim();
    if (!description) {
        window.alert("Description is required.");
        return;
    }
    await updateGoal(goalId, {
        description,
        metric: fields.metric.trim() || null,
        timeline: fields.timeline.trim() || null,
    });
}

async function addSubGoal() {
    const description = newGoalDescription?.value.trim();
    if (!description) {
        newGoalDescription?.focus();
        return;
    }
    await fetchJSON(`${API_BASE_URL}/goals`, {
        method: "POST",
        body: JSON.stringify({
            description,
            metric: newGoalMetric?.value.trim() || null,
            timeline: newGoalTimeline?.value.trim() || null,
        }),
    });
    if (newGoalDescription) newGoalDescription.value = "";
    if (newGoalMetric) newGoalMetric.value = "";
    if (newGoalTimeline) newGoalTimeline.value = "";
    await refreshGoalDisplay();
    await renderGoalsList();
}

function buildImportanceDots(score = 0) {
    const normalized = Math.max(0, Math.min(5, Number(score) || 0));
    const dots = Array.from({ length: 5 }, (_, index) => {
        const active = index < normalized ? " active" : "";
        return `<span class="${active.trim()}"></span>`;
    }).join("");
    return `<span class="importance-dots" aria-hidden="true">${dots}</span>`;
}

function buildSparkline(values, maxValue = 10) {
    if (!values.length) {
        return '<p class="empty-state">No energy or focus ratings logged yet.</p>';
    }
    const bars = values
        .map((value) => {
            const height = Math.max(8, Math.round((value / maxValue) * 100));
            return `<div class="sparkline-bar" style="height:${height}%" title="${value}/10"></div>`;
        })
        .join("");
    return `<div class="sparkline-bars">${bars}</div>`;
}

function buildRitualCalendar(logs, days = 30) {
    const byDate = new Map(logs.map((log) => [log.date, log]));
    const today = new Date();
    const cells = [];

    for (let offset = days - 1; offset >= 0; offset -= 1) {
        const date = new Date(today);
        date.setDate(today.getDate() - offset);
        const key = date.toISOString().slice(0, 10);
        const log = byDate.get(key);
        let status = "none";
        if (log?.morning_completed && log?.evening_completed) {
            status = "complete";
        } else if (log?.morning_completed || log?.evening_completed) {
            status = "partial";
        }
        const title = `${key}: ${status === "complete" ? "Both rituals" : status === "partial" ? "One ritual" : "No rituals"}`;
        cells.push(`<div class="ritual-day ${status}" title="${escapeHtml(title)}"></div>`);
    }

    return `
        <div class="ritual-calendar" aria-label="Last ${days} days of ritual completion">
            ${cells.join("")}
        </div>
        <div class="ritual-calendar-legend">
            <span><span class="legend-dot complete"></span> Both rituals</span>
            <span><span class="legend-dot partial"></span> One ritual</span>
            <span><span class="legend-dot none"></span> None</span>
        </div>
    `;
}

function collectRecentTextEntries(logs, field, limit = 3) {
    const entries = [];
    for (const log of logs) {
        const value = log?.[field];
        if (!value || !String(value).trim()) continue;
        entries.push({
            date: log.date,
            text: String(value).trim(),
        });
        if (entries.length >= limit) break;
    }
    return entries;
}

function renderHighlightList(entries, emptyMessage) {
    if (!entries.length) {
        return `<p class="empty-state">${escapeHtml(emptyMessage)}</p>`;
    }
    const items = entries
        .map(
            (entry) => `
        <li>
            <div class="highlight-date">${escapeHtml(entry.date)}</div>
            ${markdownBlock(entry.text, "compact")}
        </li>`
        )
        .join("");
    return `<ul class="highlight-list">${items}</ul>`;
}

async function openStatsModal() {
    if (!statsModal || !statsContent) return;
    statsContent.innerHTML = '<p class="panel-loading">Loading your momentum...</p>';
    statsModal.showModal();

    try {
        const [stats, logs, insights, goals] = await Promise.all([
            fetchJSON(`${API_BASE_URL}/stats`),
            fetchJSON(`${API_BASE_URL}/logs/recent?days=30`),
            fetchJSON(`${API_BASE_URL}/insights?limit=8`),
            loadGoalsData(),
        ]);

        const northStar = goals.north_star;
        const recentLogs = Array.isArray(logs) ? logs.slice().reverse() : [];
        const sparkSource = recentLogs.slice(-14);
        const energyValues = sparkSource
            .map((log) => log.energy_level)
            .filter((value) => value != null);
        const focusValues = sparkSource
            .map((log) => log.focus_rating)
            .filter((value) => value != null);

        const wins = collectRecentTextEntries(logs, "wins");
        const gratitude = collectRecentTextEntries(logs, "gratitude");

        const insightMarkup = buildInsightsList(
            insights,
            "Insights appear as Catalyst notices patterns in your conversations."
        );

        const hasTracking =
            stats.total_sessions > 0 ||
            stats.streak > 0 ||
            (Array.isArray(logs) && logs.length > 0);

        statsContent.innerHTML = `
            <section class="stats-section">
                <h3>North Star</h3>
                ${buildNorthStarCard(
                    northStar,
                    "Set your North Star to anchor your momentum."
                )}
            </section>
            <section class="stats-section">
                <h3>Momentum</h3>
                ${
                    hasTracking
                        ? `<div class="momentum-headline">
                            <div class="momentum-stat">
                                <span class="value">${stats.streak}</span>
                                <span class="label">Day streak</span>
                            </div>
                            <div class="momentum-stat">
                                <span class="value">${stats.total_sessions}</span>
                                <span class="label">Ritual sessions</span>
                            </div>
                            <div class="momentum-stat">
                                <span class="value">${Math.round(stats.completion_rate?.morning || 0)}%</span>
                                <span class="label">Morning (30d)</span>
                            </div>
                            <div class="momentum-stat">
                                <span class="value">${Math.round(stats.completion_rate?.evening || 0)}%</span>
                                <span class="label">Evening (30d)</span>
                            </div>
                           </div>`
                        : '<p class="empty-state">Complete a morning or evening ritual to start tracking momentum.</p>'
                }
            </section>
            <section class="stats-section">
                <h3>Ritual consistency (30 days)</h3>
                ${buildRitualCalendar(Array.isArray(logs) ? logs : [])}
            </section>
            <section class="stats-section">
                <h3>Energy &amp; focus (last 14 logged days)</h3>
                <div class="sparkline-row">
                    <span class="sparkline-label">Energy</span>
                    ${buildSparkline(energyValues)}
                </div>
                <div class="sparkline-row">
                    <span class="sparkline-label">Focus</span>
                    ${buildSparkline(focusValues)}
                </div>
                ${
                    energyValues.length || focusValues.length
                        ? `<p class="empty-state" style="font-style:normal;">30-day averages: energy ${stats.average_energy.toFixed(1)}/10, focus ${stats.average_focus.toFixed(1)}/10</p>`
                        : ""
                }
            </section>
            <section class="stats-section">
                <h3>Recent wins</h3>
                ${renderHighlightList(wins, "Wins show up after evening reflections and daily logs.")}
            </section>
            <section class="stats-section">
                <h3>Gratitude highlights</h3>
                ${renderHighlightList(gratitude, "Gratitude entries appear when you log them with Catalyst.")}
            </section>
            <section class="stats-section">
                <h3>Key insights</h3>
                ${insightMarkup}
            </section>
        `;
    } catch (error) {
        statsContent.innerHTML = `<p class="empty-state">Could not load stats: ${escapeHtml(error.message)}</p>`;
    }
}

function buildRateLimitMeter(label, remaining, total) {
    const safeTotal = total > 0 ? total : 1;
    const used = Math.max(0, safeTotal - (remaining ?? 0));
    const percent = Math.min(100, Math.round((used / safeTotal) * 100));
    const warning = percent >= 80 ? " warning" : "";
    return `
        <div class="rate-limit-meter">
            <div class="rate-limit-meter-label">
                <span>${escapeHtml(label)}</span>
                <span>${remaining ?? 0} / ${total} remaining</span>
            </div>
            <div class="rate-limit-meter-track">
                <div class="rate-limit-meter-fill${warning}" style="width:${percent}%"></div>
            </div>
        </div>
    `;
}

function renderLtmSection(title, body) {
    const content = body?.trim()
        ? markdownBlock(body, "ltm compact")
        : '<p class="empty-state">No content yet — Catalyst builds this through your conversations.</p>';
    return `
        <details class="ltm-section">
            <summary>${escapeHtml(title)}</summary>
            <div class="ltm-body">${content}</div>
        </details>
    `;
}

async function openSettingsModal() {
    if (!settingsModal || !settingsContent) return;
    settingsContent.innerHTML = '<p class="panel-loading">Loading settings...</p>';
    settingsModal.showModal();

    try {
        const [profile, health, rateLimits, goals] = await Promise.all([
            fetchJSON(`${API_BASE_URL}/memory/profile`),
            fetchJSON(`${API_BASE_URL}/health`),
            fetchJSON(`${API_BASE_URL}/rate-limit-status`),
            loadGoalsData(),
        ]);

        const northStar = goals.north_star;
        const meta = profile._meta || {};
        const modelName = health.ai_model || "Unknown model";

        const rateLimitMarkup = Object.entries(rateLimits?.models || {})
            .map(([model, status]) => {
                const dailyRemaining = status.daily_requests_remaining;
                const dailyLimit = status.limits?.rpd;
                if (dailyLimit == null || dailyRemaining == null) {
                    return `<p class="empty-state">${escapeHtml(model)}: daily quota not tracked client-side.</p>`;
                }
                return buildRateLimitMeter(
                    `${model} daily requests`,
                    dailyRemaining,
                    dailyLimit
                );
            })
            .join("");

        settingsContent.innerHTML = `
            <section class="settings-section">
                <h3>Goals</h3>
                ${
                    northStar
                        ? `${markdownBlock(northStar.description, "compact")}
                           <p class="goal-meta">${escapeHtml(northStar.metric || "No metric")} • ${escapeHtml(northStar.timeline || "No timeline")}</p>`
                        : "<p class=\"empty-state\">No North Star set yet.</p>"
                }
                <button type="button" class="primary btn-inline" id="settingsEditGoalsButton">Edit goals</button>
            </section>
            <section class="settings-section ltm-section">
                <h3>Mentor Memory</h3>
                <p>Updated by Catalyst during evening reflections.</p>
                <p>Version ${escapeHtml(String(meta.version ?? "—"))} • Last updated ${escapeHtml(meta.updated_at ? formatTimestamp(meta.updated_at) : "—")}</p>
                ${renderLtmSection("Personality", profile.personality)}
                ${renderLtmSection("Patterns", profile.patterns)}
                ${renderLtmSection("Challenges", profile.challenges)}
                ${renderLtmSection("Breakthroughs", profile.breakthroughs)}
                ${renderLtmSection("Current State", profile.current_state)}
            </section>
            <section class="settings-section">
                <h3>API &amp; Usage</h3>
                <p>Primary model: <strong>${escapeHtml(modelName)}</strong></p>
                ${rateLimitMarkup || '<p class="empty-state">Rate limit status unavailable.</p>'}
            </section>
        `;

        const editGoalsButton = document.getElementById("settingsEditGoalsButton");
        editGoalsButton?.addEventListener("click", () => {
            settingsModal.close();
            openGoalsModal("edit");
        });
    } catch (error) {
        settingsContent.innerHTML = `<p class="empty-state">Could not load settings: ${escapeHtml(error.message)}</p>`;
    }
}

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

    if (!hasPrompt && !hasContext && !hasReference && !hasSystemPromptReference) {
        return null;
    }

    return {
        systemPrompt: hasPrompt ? systemPromptSource : "",
        contextSnapshot,
        contextReference,
        systemPromptReference,
        contextStats: extractContextStats(
            typeof systemPromptReference === "object"
                ? systemPromptReference
                : null
        ),
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
    body.className = "message-body markdown-content";
    body.innerHTML = markdownToHtml(text);

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
        const data = await loadGoalsData();
        if (data.total > 0 && data.north_star) {
            goalDisplay.textContent = formatGoalSummary(data.north_star);
            if (goalsModal?.open && goalsInitView && !goalsInitView.hidden) {
                goalsModal.close();
            }
            return true;
        }
        goalDisplay.textContent = "No North Star set yet.";
        openGoalsModal("init");
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
        snippet.className = "conversation-snippet markdown-content compact";
        const previewText = meta.preview || "No summary yet.";
        snippet.innerHTML = markdownToHtml(previewText);

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
        goalsModal?.close();
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
        inputPreviewPanel.classList.add("markdown-content", "compact");
        inputPreviewPanel.innerHTML = markdownToHtml(text);
    } else {
        inputPreviewPanel.classList.remove("markdown-content", "compact");
        inputPreviewPanel.innerHTML =
            '<p class="empty-state">Preview will appear here...</p>';
    }
}

function showPreview() {
    // Fallback for modal preview if it exists
    if (previewModal && previewContent) {
        const text = messageInput.value.trim();
        if (!text) {
            previewContent.classList.remove("markdown-content", "compact");
            previewContent.innerHTML =
                '<p class="empty-state">Nothing to preview...</p>';
        } else {
            previewContent.classList.add("markdown-content", "compact");
            previewContent.innerHTML = markdownToHtml(text);
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
        ((!hasValue(systemPromptText) || !hasValue(contextData)) &&
            (hasValue(contextReference) || hasValue(systemPromptReference)));

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

    const contextStats =
        extractContextStats(systemPromptReference) ||
        debugInfo?.contextStats ||
        null;
    const statsSummary = formatContextStatsSummary(
        contextStats,
        systemPromptChecksumMatch
    );

    if (debugInfo && typeof debugInfo === "object") {
        debugInfo.systemPrompt = systemPromptText;
        debugInfo.contextSnapshot = contextData;
        debugInfo.contextReference = contextReference;
        debugInfo.systemPromptReference = systemPromptReference;
        debugInfo.contextStats = contextStats;
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
    if (statsSummary) {
        clipboardSections.push(`=== Context Stats ===\n${statsSummary}`);
    }
    if (hasPrompt) {
        clipboardSections.push(
            "=== System Instructions ===\n".concat(
                normalizeToString(systemPromptText)
            )
        );
    }
    if (hasContext) {
        clipboardSections.push(
            "=== Context Snapshot (raw — not sent to model) ===\n".concat(
                normalizeToString(contextData)
            )
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
        body.className = "debug-markdown markdown-content compact";
        body.innerHTML = markdownToHtml(formatDebugContent(text, options));
        wrapper.appendChild(body);

        return wrapper;
    };

    systemContextContent.innerHTML = "";

    if (statsSummary) {
        const statsBanner = document.createElement("div");
        statsBanner.className = "debug-stats";
        statsBanner.textContent = statsSummary;
        systemContextContent.appendChild(statsBanner);
    }

    systemContextContent.appendChild(
        makeSection(
            "System Instructions (sent to the model)",
            promptText,
            { wrapToon: true }
        )
    );
    systemContextContent.appendChild(
        makeSection(
            "Context Snapshot (raw data — not sent to the model)",
            contextText,
            { preferCodeBlock: true }
        )
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

    initButton?.addEventListener("click", (event) => {
        event.preventDefault();
        initializeCatalyst();
    });

    if (goalBadge) {
        goalBadge.addEventListener("click", () => {
            openGoalsModal(cachedGoalsData?.total ? "edit" : "init");
        });
    }

    closeGoalsButton?.addEventListener("click", () => goalsModal?.close());
    addGoalButton?.addEventListener("click", () => {
        addSubGoal().catch((error) => {
            window.alert(`Could not add goal: ${error.message}`);
        });
    });

    statsButton?.addEventListener("click", () => {
        openStatsModal();
    });

    settingsButton?.addEventListener("click", () => {
        openSettingsModal();
    });

    closeStatsBtn?.addEventListener("click", () => statsModal?.close());
    closeSettingsBtn?.addEventListener("click", () => settingsModal?.close());

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
