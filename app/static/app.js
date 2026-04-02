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

function setMessageProgress(snapshot) {
    document.querySelectorAll(".message-progress").forEach((node) => {
        node.hidden = true;
    });

    if (!snapshot || (snapshot.state !== "running" && snapshot.state !== "preparing" && snapshot.state !== "conditioning")) {
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
