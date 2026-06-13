function scrollTimelineToBottom() {
    const container = document.getElementById("timeline");
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
}

function attachTimelineImageLoadScroll() {
    const container = document.getElementById("timeline");
    if (!container) {
        return;
    }
    container.querySelectorAll("img").forEach((image) => {
        if (image.dataset.scrollBound === "1") {
            return;
        }
        image.dataset.scrollBound = "1";
        image.addEventListener("load", () => {
            scrollTimelineToBottom();
        });
    });
}

function settleTimelineScroll() {
    scrollTimelineToBottom();
    window.setTimeout(scrollTimelineToBottom, 100);
    window.setTimeout(scrollTimelineToBottom, 450);
}

function resizeComposerTextArea(textarea) {
    if (!textarea) {
        return;
    }
    textarea.style.height = "auto";
    textarea.style.height = Math.min(textarea.scrollHeight, 220) + "px";
}

function bindComposerShortcuts() {
    document.querySelectorAll(".composer textarea").forEach((textarea) => {
        if (textarea.dataset.composerBound === "1") {
            return;
        }
        textarea.dataset.composerBound = "1";
        resizeComposerTextArea(textarea);
        textarea.addEventListener("input", () => resizeComposerTextArea(textarea));
        textarea.addEventListener("keydown", (event) => {
            if ((event.ctrlKey || event.metaKey) && event.key === "Enter") {
                event.preventDefault();
                const form = textarea.closest("form");
                if (form) {
                    form.requestSubmit();
                }
            }
        });
    });
}

function toggleInlineComposer(id) {
    const panel = document.getElementById(id);
    if (!panel) {
        return;
    }
    const open = panel.hasAttribute("hidden");
    document.querySelectorAll(".inline-image-tools").forEach((element) => {
        if (element.id !== id) {
            element.setAttribute("hidden", "hidden");
        }
    });
    if (open) {
        panel.removeAttribute("hidden");
        const field = panel.querySelector("textarea");
        if (field) {
            field.focus();
        }
    } else {
        panel.setAttribute("hidden", "hidden");
    }
}

function closeModal(event) {
    if (event) {
        event.preventDefault();
    }
    const modal = document.getElementById("modal-panel");
    if (modal) {
        modal.innerHTML = "";
    }
}

function addLoreEntryRow(form) {
    if (!form) {
        return;
    }
    const list = form.querySelector("[data-lorebook-list]");
    if (!list) {
        return;
    }
    const nextIndex = Number.parseInt(form.dataset.loreNextIndex || "0", 10) || 0;
    const article = document.createElement("article");
    article.className = "lore-entry-card";
    article.dataset.loreEntry = "true";
    article.innerHTML = `
        <input type="hidden" name="lore_id_${nextIndex}" value="">
        <input type="hidden" name="lore_delete_${nextIndex}" value="0" data-lore-delete>

        <label>
            <span>Title</span>
            <input type="text" name="lore_title_${nextIndex}" value="">
        </label>

        <label>
            <span>Content</span>
            <textarea name="lore_content_${nextIndex}" rows="3"></textarea>
        </label>

        <div class="lorebook-grid">
            <label>
                <span>Keywords</span>
                <input type="text" name="lore_keywords_${nextIndex}" value="" placeholder="comma, separated, triggers">
            </label>
            <label>
                <span>Priority</span>
                <input type="number" name="lore_priority_${nextIndex}" value="0">
            </label>
        </div>

        <div class="toggle-row">
            <label class="checkbox-row">
                <input type="checkbox" name="lore_enabled_${nextIndex}" value="1" checked>
                <span>Enabled</span>
            </label>
            <label class="checkbox-row">
                <input type="checkbox" name="lore_always_include_${nextIndex}" value="1">
                <span>Always include</span>
            </label>
            <button class="ghost-button danger-subtle" type="button" onclick="window.removeLoreEntryRow(this)">Delete Entry</button>
        </div>
    `;
    list.appendChild(article);
    form.dataset.loreNextIndex = String(nextIndex + 1);
    const firstField = article.querySelector("input[type='text'], textarea");
    if (firstField) {
        firstField.focus();
    }
}

function removeLoreEntryRow(button) {
    const card = button ? button.closest("[data-lore-entry]") : null;
    if (!card) {
        return;
    }
    const deleteField = card.querySelector("[data-lore-delete]");
    if (deleteField) {
        deleteField.value = "1";
        card.hidden = true;
        return;
    }
    card.remove();
}

function setEngineChip(prefix, snapshot) {
    const chip = document.getElementById(prefix + "-engine-chip");
    if (!chip || !snapshot) {
        return;
    }
    chip.dataset.state = snapshot.state || "idle";
    chip.querySelector(".engine-detail").textContent = snapshot.detail || "";
    chip.querySelector(".engine-state").textContent = snapshot.mock
        ? "mock"
        : snapshot.loaded
            ? "ready"
            : snapshot.state || "idle";
    const bar = chip.querySelector(".engine-progress-fill");
    if (bar) {
        const progress = Math.max(0, Math.min(1, snapshot.progress ?? 0));
        bar.style.width = (progress * 100).toFixed(0) + "%";
    }
}

function setEngineChipManual(prefix, state, detail, progress) {
    const chip = document.getElementById(prefix + "-engine-chip");
    if (!chip) {
        return;
    }
    chip.dataset.state = state || "idle";
    const detailNode = chip.querySelector(".engine-detail");
    const stateNode = chip.querySelector(".engine-state");
    const bar = chip.querySelector(".engine-progress-fill");
    if (detailNode) {
        detailNode.textContent = detail || "";
    }
    if (stateNode) {
        stateNode.textContent = state || "idle";
    }
    if (bar) {
        const safeProgress = Math.max(0, Math.min(1, progress ?? 0));
        bar.style.width = (safeProgress * 100).toFixed(0) + "%";
    }
}

function activeRuntimeSnapshot(status) {
    if (!status) {
        return null;
    }
    if (status.runtime && !status.runtime.ready) {
        return { kind: "runtime", ...status.runtime };
    }
    const busyStates = new Set(["queued", "preparing", "conditioning", "loading", "unloading", "generating", "running", "finalizing"]);
    if (status.image && busyStates.has(status.image.state)) {
        return { kind: "image", ...status.image };
    }
    if (status.text && busyStates.has(status.text.state)) {
        return { kind: "text", ...status.text };
    }
    if (status.image && status.image.state === "error") {
        return { kind: "image", ...status.image };
    }
    if (status.text && status.text.state === "error") {
        return { kind: "text", ...status.text };
    }
    return status.image && status.image.loaded ? { kind: "image", ...status.image } : status.text;
}

function setRuntimeReadiness(status) {
    const runtime = status ? status.runtime : null;
    const panel = document.getElementById("readiness-panel");
    const title = document.getElementById("readiness-title");
    const detail = document.getElementById("readiness-detail");
    const fill = document.getElementById("readiness-progress-fill");
    const ready = runtime ? Boolean(runtime.ready) : true;
    document.body.dataset.runtimeReady = ready ? "1" : "0";

    if (panel) {
        panel.dataset.ready = ready ? "true" : "false";
        panel.dataset.state = runtime ? runtime.state || "idle" : "ready";
    }
    if (title) {
        title.textContent = ready ? "Ready to write" : "Warming local engines";
    }
    if (detail) {
        detail.textContent = runtime
            ? runtime.detail || (ready ? "Runtime ready." : "Loading local models...")
            : "Runtime ready.";
    }
    if (fill) {
        const progress = runtime ? Math.max(0, Math.min(1, runtime.progress ?? 0)) : 1;
        fill.style.width = (progress * 100).toFixed(0) + "%";
    }

    const retryButton = document.getElementById("readiness-retry");
    if (retryButton) {
        retryButton.hidden = !(runtime && runtime.state === "error");
    }

    document.querySelectorAll('form[data-action="chat"]').forEach((form) => {
        form.classList.toggle("runtime-not-ready", !ready);
        const button = form.querySelector('button[type="submit"]');
        if (!button || button.dataset.busy === "1") {
            return;
        }
        button.disabled = !ready;
        if (ready) {
            button.textContent = "Advance Scene";
        } else if (runtime && runtime.state === "error") {
            button.textContent = "Engines Failed - Retry Above";
        } else {
            button.textContent = "Warming Engines...";
        }
    });
}

function setSceneStatus(status) {
    const banner = document.getElementById("scene-status-banner");
    if (!banner) {
        return;
    }
    const active = activeRuntimeSnapshot(status) || {};
    const state = active.state || "idle";
    const detail = active.detail || "Ready for the next scene beat.";
    const copy = banner.querySelector(".scene-status-copy");
    banner.dataset.state = state;
    if (copy) {
        copy.textContent = detail;
    }
}

function setSceneStatusManual(state, detail) {
    const banner = document.getElementById("scene-status-banner");
    if (!banner) {
        return;
    }
    banner.dataset.state = state || "idle";
    const copy = banner.querySelector(".scene-status-copy");
    if (copy) {
        copy.textContent = detail || "Working...";
    }
}

function setMessageProgress(snapshot) {
    document.querySelectorAll(".message-progress").forEach((node) => {
        node.hidden = true;
    });

    const activeStates = new Set(["queued", "preparing", "conditioning", "loading", "running", "finalizing"]);
    if (!snapshot || !activeStates.has(snapshot.state)) {
        return;
    }

    let target = null;
    if (snapshot.image_id) {
        target = document.querySelector(`.message-progress[data-image-id="${snapshot.image_id}"]`);
    }
    if (!target && snapshot.message_id) {
        target = document.querySelector(`.message-progress[data-message-id="${snapshot.message_id}"]`);
    }
    if (!target) {
        return;
    }

    target.hidden = false;
    const label = target.querySelector(".message-progress-label");
    const fill = target.querySelector(".message-progress-bar span");
    if (label) {
        label.textContent = snapshot.detail || "Working...";
    }
    if (fill) {
        const progress = Math.max(0, Math.min(1, snapshot.progress ?? 0));
        fill.style.width = (progress * 100).toFixed(0) + "%";
    }
}

function applyStatusSnapshot(status) {
    if (!status) {
        return;
    }
    setEngineChip("text", status.text);
    setEngineChip("image", status.image);
    setRuntimeReadiness(status);
    setSceneStatus(status);
    setMessageProgress(status.image);
    refreshTimelineWhenImageFinalizes(status.image);
}

function formatDiagnosticState(snapshot) {
    if (!snapshot) {
        return "--";
    }
    if (snapshot.mock) {
        return "mock";
    }
    if (snapshot.loaded) {
        return "ready";
    }
    return snapshot.state || "idle";
}

async function refreshDiagnostics() {
    const box = document.getElementById("diagnostics-json");
    try {
        const response = await fetch("/diagnostics", { cache: "no-store" });
        const data = await response.json();
        const resources = data.resources || {};
        const ram = document.getElementById("diag-ram");
        const vram = document.getElementById("diag-vram");
        const text = document.getElementById("diag-text");
        const image = document.getElementById("diag-image");
        if (ram) {
            ram.textContent = `${Number(resources.free_ram_gb || 0).toFixed(1)} GB free`;
        }
        if (vram) {
            vram.textContent = `${resources.vram_used_mib || 0}/${(resources.vram_used_mib || 0) + (resources.vram_free_mib || 0)} MiB`;
        }
        if (text) {
            text.textContent = formatDiagnosticState(data.text);
        }
        if (image) {
            image.textContent = formatDiagnosticState(data.image);
        }
        if (box) {
            box.textContent = JSON.stringify(data, null, 2);
        }
    } catch (error) {
        if (box) {
            box.textContent = `Diagnostics fetch failed: ${error}`;
        }
    }
}

function toggleDiagnosticsDrawer(forceOpen) {
    const drawer = document.getElementById("diagnostics-drawer");
    if (!drawer) {
        return;
    }
    const shouldOpen = typeof forceOpen === "boolean" ? forceOpen : drawer.hasAttribute("hidden");
    if (shouldOpen) {
        drawer.removeAttribute("hidden");
        refreshDiagnostics();
        if (window.__diagnosticsTimer) {
            window.clearInterval(window.__diagnosticsTimer);
        }
        window.__diagnosticsTimer = window.setInterval(refreshDiagnostics, 3500);
    } else {
        drawer.setAttribute("hidden", "hidden");
        if (window.__diagnosticsTimer) {
            window.clearInterval(window.__diagnosticsTimer);
            window.__diagnosticsTimer = null;
        }
    }
}

function refreshTimelineWhenImageFinalizes(snapshot) {
    if (window.__streamActive) {
        return;
    }
    if (!snapshot || !snapshot.message_id) {
        return;
    }
    const isGenerated = snapshot.state === "ready" && snapshot.detail && snapshot.detail.startsWith("Image generated");
    const isError = snapshot.state === "error";
    if (!isGenerated && !isError) {
        return;
    }
    const key = `${snapshot.message_id}:${snapshot.state}:${snapshot.detail}`;
    if (window.__lastImageRefreshKey === key) {
        return;
    }
    window.__lastImageRefreshKey = key;
    const shell = document.querySelector(".app-shell");
    const characterId = shell ? shell.dataset.activeCharacterId : "";
    if (!characterId || !window.htmx) {
        return;
    }
    document.body.dataset.lastAction = "image-complete-refresh";
    window.htmx.ajax("GET", `/timeline/${characterId}`, {
        target: "#timeline",
        swap: "innerHTML",
    });
}

function timelineImageCount() {
    return document.querySelectorAll("#timeline .scene-visual img").length;
}

function scheduleTimelineRefreshUntilNewImage(minImageCount) {
    if (!window.htmx) {
        return;
    }
    if (window.__autoImageRefreshTimer) {
        window.clearInterval(window.__autoImageRefreshTimer);
    }
    const startedAt = Date.now();
    const maxMs = 180000;
    const refresh = () => {
        if (window.__streamActive) {
            return;
        }
        if (timelineImageCount() > minImageCount) {
            window.clearInterval(window.__autoImageRefreshTimer);
            window.__autoImageRefreshTimer = null;
            return;
        }
        if (Date.now() - startedAt > maxMs) {
            window.clearInterval(window.__autoImageRefreshTimer);
            window.__autoImageRefreshTimer = null;
            return;
        }
        const shell = document.querySelector(".app-shell");
        const characterId = shell ? shell.dataset.activeCharacterId : "";
        if (!characterId) {
            return;
        }
        document.body.dataset.lastAction = "image-complete-refresh";
        window.htmx.ajax("GET", `/timeline/${characterId}`, {
            target: "#timeline",
            swap: "innerHTML",
        });
    };
    window.__autoImageRefreshTimer = window.setInterval(refresh, 3000);
    window.setTimeout(refresh, 1200);
}

function showPendingProgress(selector, labelText) {
    const target = document.querySelector(selector);
    if (!target) {
        return;
    }
    target.hidden = false;
    const label = target.querySelector(".message-progress-label");
    const fill = target.querySelector(".message-progress-bar span");
    if (label) {
        label.textContent = labelText;
    }
    if (fill) {
        fill.style.width = "12%";
    }
}

function setPendingActionState(source) {
    if (!source || !source.dataset) {
        return;
    }
    const action = source.dataset.action || "";
    if (action === "chat" || action === "regenerate") {
        setEngineChipManual("text", "queued", "Reply request received", 0.08);
        setSceneStatusManual("queued", action === "regenerate" ? "Regenerating the latest scene beat..." : "Writing the next scene beat...");
        const autoImage = source.querySelector('input[name="auto_image"]');
        if (action === "chat" && autoImage && autoImage.checked) {
            setEngineChipManual("image", "queued", "Will render image after reply", 0.04);
            setSceneStatusManual("queued", "Writing the reply first; the visual will render after.");
        }
        return;
    }
    if (action === "image") {
        setEngineChipManual("text", "queued", "Preparing scene context", 0.08);
        setEngineChipManual("image", "queued", "Image request received", 0.06);
        setSceneStatusManual("queued", "Preparing a visual for this scene beat...");
        if (source.dataset.messageId) {
            showPendingProgress(`.message-progress[data-message-id="${source.dataset.messageId}"]`, "Request received...");
        }
        return;
    }
    if (action === "image-regenerate") {
        setEngineChipManual("image", "queued", "Image regeneration requested", 0.06);
        setSceneStatusManual("queued", "Regenerating this visual...");
        if (source.dataset.imageId) {
            showPendingProgress(`.message-progress[data-image-id="${source.dataset.imageId}"]`, "Regeneration requested...");
        }
    }
}

function connectStatusStream() {
    if (!window.EventSource) {
        return;
    }

    if (window.__statusStream) {
        window.__statusStream.close();
    }

    const stream = new EventSource("/status/stream");
    window.__statusStream = stream;

    stream.onmessage = (event) => {
        try {
            applyStatusSnapshot(JSON.parse(event.data));
        } catch (_) {
            // keep the stream resilient
        }
    };

    stream.onerror = () => {
        stream.close();
        if (!window.__shutdownMode) {
            window.setTimeout(connectStatusStream, 2000);
        }
    };
}

// ---------------------------------------------------------------------------
// Real token streaming (replaces the old fake post-hoc typewriter)
// ---------------------------------------------------------------------------

function buildStreamingBeats(userText, characterName) {
    const timeline = document.getElementById("timeline");
    if (!timeline) {
        return null;
    }
    let feed = timeline.querySelector(".story-feed");
    if (!feed) {
        timeline.innerHTML = '<div class="story-feed scene-feed"></div>';
        feed = timeline.querySelector(".story-feed");
    }
    const beatCount = feed.querySelectorAll(".story-block").length;

    const userBeat = document.createElement("article");
    userBeat.className = "story-block scene-beat user";
    userBeat.innerHTML =
        '<div class="message-meta"><span class="beat-index"></span><span class="speaker-name">You</span></div>' +
        '<div class="message-body" data-role="user"></div>';
    userBeat.querySelector(".beat-index").textContent = "Beat " + (beatCount + 1);
    userBeat.querySelector(".message-body").textContent = userText;

    const aiBeat = document.createElement("article");
    aiBeat.className = "story-block scene-beat assistant streaming";
    aiBeat.id = "streaming-beat";
    aiBeat.innerHTML =
        '<div class="message-meta"><span class="beat-index"></span><span class="speaker-name"></span></div>' +
        '<div class="frame-meta streaming-meta"><span class="streaming-indicator">Connecting to the story engine...</span></div>' +
        '<div class="message-body streaming-body" data-role="assistant"></div>';
    aiBeat.querySelector(".beat-index").textContent = "Beat " + (beatCount + 2);
    aiBeat.querySelector(".speaker-name").textContent = characterName;

    feed.appendChild(userBeat);
    feed.appendChild(aiBeat);
    settleTimelineScroll();
    return aiBeat.querySelector(".streaming-body");
}

function setStreamingIndicator(text) {
    const node = document.querySelector("#streaming-beat .streaming-indicator");
    if (node) {
        node.textContent = text;
    }
}

async function streamChat(form) {
    const textarea = form.querySelector("textarea");
    const button = form.querySelector('button[type="submit"]');
    const userText = (textarea ? textarea.value : "").trim();
    if (!userText || (button && button.dataset.busy === "1")) {
        return;
    }
    const formData = new FormData(form);
    formData.set("message", userText);
    const autoImage = formData.get("auto_image");
    const characterName = form.dataset.characterName || "Companion";
    const streamUrl = form.dataset.streamUrl;
    if (!streamUrl) {
        return;
    }

    const body = buildStreamingBeats(userText, characterName);
    if (!body) {
        return;
    }
    window.__streamActive = true;
    if (textarea) {
        textarea.value = "";
        resizeComposerTextArea(textarea);
    }
    if (button) {
        button.dataset.busy = "1";
        button.disabled = true;
        button.textContent = "Writing...";
    }
    if (autoImage) {
        document.body.dataset.imageCountBeforeChat = String(timelineImageCount());
    }
    setSceneStatusManual("generating", "Writing the next scene beat...");
    setEngineChipManual("text", "generating", "Writing story reply", 0.5);

    let sawDone = false;
    let errText = "";
    let firstToken = true;
    try {
        const response = await fetch(streamUrl, { method: "POST", body: formData });
        if (!response.ok || !response.body) {
            throw new Error("HTTP " + response.status);
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";
        for (;;) {
            const { done, value } = await reader.read();
            if (done) {
                break;
            }
            buffer += decoder.decode(value, { stream: true });
            let newlineAt;
            while ((newlineAt = buffer.indexOf("\n")) >= 0) {
                const line = buffer.slice(0, newlineAt).trim();
                buffer = buffer.slice(newlineAt + 1);
                if (!line) {
                    continue;
                }
                let event;
                try {
                    event = JSON.parse(line);
                } catch (_) {
                    continue;
                }
                if (event.t === "tok") {
                    if (firstToken) {
                        firstToken = false;
                        setStreamingIndicator("Writing...");
                    }
                    body.textContent += event.v;
                    scrollTimelineToBottom();
                } else if (event.t === "status") {
                    setSceneStatusManual("generating", event.v);
                    setStreamingIndicator(event.v);
                } else if (event.t === "done") {
                    sawDone = true;
                } else if (event.t === "err") {
                    errText = event.v || "Generation failed.";
                }
            }
        }
    } catch (error) {
        errText = errText || String(error);
    }

    window.__streamActive = false;
    if (button) {
        delete button.dataset.busy;
        button.disabled = false;
        button.textContent = "Advance Scene";
    }

    if (errText || !sawDone) {
        const failure = errText || "The stream ended unexpectedly.";
        setSceneStatusManual("error", failure);
        setStreamingIndicator(failure);
        const beat = document.getElementById("streaming-beat");
        if (beat) {
            beat.classList.add("streaming-failed");
        }
        if (textarea && !textarea.value) {
            textarea.value = userText;
            resizeComposerTextArea(textarea);
        }
        return;
    }

    document.body.dataset.lastAction = "chat-stream";
    const shell = document.querySelector(".app-shell");
    const characterId = shell ? shell.dataset.activeCharacterId : "";
    if (characterId && window.htmx) {
        window.htmx.ajax("GET", `/timeline/${characterId}`, {
            target: "#timeline",
            swap: "innerHTML",
        });
    }
    if (autoImage) {
        const minImageCount = Number.parseInt(document.body.dataset.imageCountBeforeChat || "0", 10) || 0;
        scheduleTimelineRefreshUntilNewImage(minImageCount);
    }
}

function bindStreamingComposer() {
    const form = document.querySelector('form[data-action="chat"]');
    if (!form || form.dataset.streamBound === "1") {
        return;
    }
    form.dataset.streamBound = "1";
    form.addEventListener("submit", (event) => {
        event.preventDefault();
        streamChat(form);
    });
}

// ---------------------------------------------------------------------------
// Composer preference persistence (auto-image toggle + preset survive turns)
// ---------------------------------------------------------------------------

function persistComposerPrefs() {
    const form = document.querySelector('form[data-action="chat"]');
    if (!form || form.dataset.prefsBound === "1") {
        return;
    }
    form.dataset.prefsBound = "1";
    const checkbox = form.querySelector('input[name="auto_image"]');
    if (checkbox) {
        const saved = window.localStorage.getItem("companion.autoImage");
        if (saved !== null) {
            checkbox.checked = saved === "1";
        }
        checkbox.addEventListener("change", () => {
            window.localStorage.setItem("companion.autoImage", checkbox.checked ? "1" : "0");
        });
    }
    const radios = form.querySelectorAll('input[name="resolution_preset"]');
    const savedPreset = window.localStorage.getItem("companion.imagePreset");
    radios.forEach((radio) => {
        if (savedPreset && radio.value === savedPreset) {
            radio.checked = true;
        }
        radio.addEventListener("change", () => {
            if (radio.checked) {
                window.localStorage.setItem("companion.imagePreset", radio.value);
            }
        });
    });
}

function retryWarmup() {
    setSceneStatusManual("loading", "Retrying engine warmup...");
    fetch("/runtime/retry-warmup", { method: "POST" }).catch(() => {
        setSceneStatusManual("error", "Retry request failed; is the app server running?");
    });
}

// ---------------------------------------------------------------------------
// Power off: unload models, stop engines, close the server - from the UI
// ---------------------------------------------------------------------------

function showShutdownScreen(message, final) {
    let screen = document.getElementById("shutdown-screen");
    if (!screen) {
        screen = document.createElement("div");
        screen.id = "shutdown-screen";
        screen.innerHTML =
            '<div class="shutdown-card">' +
            '<p class="eyebrow">Companion</p>' +
            '<h2 id="shutdown-title">Shutting down</h2>' +
            '<p id="shutdown-detail"></p>' +
            "</div>";
        document.body.appendChild(screen);
    }
    const title = document.getElementById("shutdown-title");
    const detail = document.getElementById("shutdown-detail");
    if (final) {
        if (title) {
            title.textContent = "App is off";
        }
        screen.dataset.final = "1";
    }
    if (detail) {
        detail.textContent = message;
    }
}

async function performShutdown() {
    window.__shutdownMode = true;
    if (window.__statusStream) {
        window.__statusStream.close();
    }
    if (window.__autoImageRefreshTimer) {
        window.clearInterval(window.__autoImageRefreshTimer);
    }
    showShutdownScreen("Asking the server to unload models and stop the local engines...");
    try {
        await fetch("/runtime/shutdown", { method: "POST" });
    } catch (_) {
        showShutdownScreen("Could not reach the server - it may already be off. You can close this tab.", true);
        return;
    }
    // Narrate unload phases until the server stops answering.
    const startedAt = Date.now();
    const poll = async () => {
        try {
            const response = await fetch("/status", { cache: "no-store" });
            const data = await response.json();
            const text = data.text || {};
            const image = data.image || {};
            const busy = [text, image].find((s) => s.state && s.state !== "idle" && s.state !== "ready");
            const phase = busy ? busy.detail : "Stopping the app server...";
            showShutdownScreen(phase || "Stopping the app server...");
        } catch (_) {
            showShutdownScreen(
                "All models unloaded and local engines stopped. The server is off - you can close this tab. " +
                "Double-click START_COMPANION_APP.cmd to start it again.",
                true
            );
            return;
        }
        if (Date.now() - startedAt < 180000) {
            window.setTimeout(poll, 1200);
        } else {
            showShutdownScreen("Shutdown is taking unusually long; check the server terminal.", true);
        }
    };
    window.setTimeout(poll, 1200);
}

function requestShutdown() {
    const button = document.getElementById("power-button");
    if (!button) {
        return;
    }
    if (button.dataset.armed === "1") {
        button.dataset.armed = "0";
        button.textContent = "Power Off";
        performShutdown();
        return;
    }
    const draft = document.querySelector(".composer textarea");
    button.dataset.armed = "1";
    button.textContent = draft && draft.value.trim() ? "Confirm? (unsent draft!)" : "Confirm Power Off?";
    window.setTimeout(() => {
        if (button.dataset.armed === "1") {
            button.dataset.armed = "0";
            button.textContent = "Power Off";
        }
    }, 6000);
}

window.closeModal = closeModal;
window.toggleInlineComposer = toggleInlineComposer;
window.addLoreEntryRow = addLoreEntryRow;
window.removeLoreEntryRow = removeLoreEntryRow;
window.toggleDiagnosticsDrawer = toggleDiagnosticsDrawer;
window.refreshDiagnostics = refreshDiagnostics;
window.retryWarmup = retryWarmup;
window.requestShutdown = requestShutdown;

document.addEventListener("DOMContentLoaded", () => {
    attachTimelineImageLoadScroll();
    bindComposerShortcuts();
    bindStreamingComposer();
    persistComposerPrefs();
    settleTimelineScroll();
    connectStatusStream();
});

document.body.addEventListener("htmx:beforeRequest", (event) => {
    const source = event.detail.elt;
    if (source && source.dataset && source.dataset.action) {
        document.body.dataset.lastAction = source.dataset.action;
        if (source.dataset.messageId) {
            document.body.dataset.lastMessageId = source.dataset.messageId;
        }
        if (source.dataset.action === "chat") {
            const autoImage = source.querySelector('input[name="auto_image"]');
            if (autoImage && autoImage.checked) {
                document.body.dataset.awaitingAutoImage = "1";
                document.body.dataset.imageCountBeforeChat = String(timelineImageCount());
            } else {
                delete document.body.dataset.awaitingAutoImage;
                delete document.body.dataset.imageCountBeforeChat;
            }
        }
        setPendingActionState(source);
    }
});

document.body.addEventListener("htmx:afterSwap", (event) => {
    if (!event.target) {
        return;
    }

    if (event.target.id === "timeline") {
        attachTimelineImageLoadScroll();
        bindComposerShortcuts();
        settleTimelineScroll();
        if (document.body.dataset.lastAction === "chat" && document.body.dataset.awaitingAutoImage === "1") {
            const minImageCount = Number.parseInt(document.body.dataset.imageCountBeforeChat || "0", 10) || 0;
            scheduleTimelineRefreshUntilNewImage(minImageCount);
            delete document.body.dataset.awaitingAutoImage;
            delete document.body.dataset.imageCountBeforeChat;
        }
    }

    if (event.target.id === "modal-panel") {
        bindComposerShortcuts();
        const firstField = event.target.querySelector("input, textarea");
        if (firstField) {
            firstField.focus();
        }
    }
});

document.body.addEventListener("htmx:oobAfterSwap", (event) => {
    if (event.target && event.target.id === "timeline") {
        attachTimelineImageLoadScroll();
        settleTimelineScroll();
    }
});
