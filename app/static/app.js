function scrollTimelineToBottom() {
    const container = document.getElementById("timeline");
    if (container) {
        container.scrollTop = container.scrollHeight;
    }
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
    setMessageProgress(status.image);
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
        return;
    }
    if (action === "image") {
        setEngineChipManual("text", "queued", "Preparing scene context", 0.08);
        setEngineChipManual("image", "queued", "Image request received", 0.06);
        if (source.dataset.messageId) {
            showPendingProgress(`.message-progress[data-message-id="${source.dataset.messageId}"]`, "Request received...");
        }
        return;
    }
    if (action === "image-regenerate") {
        setEngineChipManual("image", "queued", "Image regeneration requested", 0.06);
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
        window.setTimeout(connectStatusStream, 2000);
    };
}

function typewriteLatestAssistant() {
    const pending = document.querySelectorAll('.message-body[data-typewriter="pending"]');
    const target = pending.length ? pending[pending.length - 1] : null;
    if (!target) {
        return;
    }
    const original = target.textContent || "";
    const words = original.split(/\s+/).filter(Boolean);
    target.textContent = "";
    target.dataset.typewriter = "running";
    let index = 0;
    const tick = () => {
        if (index >= words.length) {
            target.dataset.typewriter = "done";
            return;
        }
        target.textContent += (index === 0 ? "" : " ") + words[index];
        index += 1;
        window.setTimeout(tick, index < 18 ? 32 : 18);
    };
    tick();
}

window.closeModal = closeModal;
window.toggleInlineComposer = toggleInlineComposer;
window.addLoreEntryRow = addLoreEntryRow;
window.removeLoreEntryRow = removeLoreEntryRow;

document.addEventListener("DOMContentLoaded", () => {
    scrollTimelineToBottom();
    connectStatusStream();
});

document.body.addEventListener("htmx:beforeRequest", (event) => {
    const source = event.detail.elt;
    if (source && source.dataset && source.dataset.action) {
        document.body.dataset.lastAction = source.dataset.action;
        if (source.dataset.messageId) {
            document.body.dataset.lastMessageId = source.dataset.messageId;
        }
        setPendingActionState(source);
    }
});

document.body.addEventListener("htmx:afterSwap", (event) => {
    if (!event.target) {
        return;
    }

    if (event.target.id === "timeline") {
        const composer = document.querySelector(".composer");
        if (composer && document.body.dataset.lastAction === "chat") {
            composer.reset();
        }
        scrollTimelineToBottom();
        if (document.body.dataset.lastAction === "chat") {
            typewriteLatestAssistant();
        }
    }

    if (event.target.id === "modal-panel") {
        const firstField = event.target.querySelector("input, textarea");
        if (firstField) {
            firstField.focus();
        }
    }
});

document.body.addEventListener("htmx:oobAfterSwap", (event) => {
    if (event.target && event.target.id === "timeline") {
        scrollTimelineToBottom();
    }
});
