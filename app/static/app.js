function scrollTimelineToBottom() {
    const container = document.getElementById("timeline");
    if (container) {
        container.scrollTop = container.scrollHeight;
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

async function refreshEngineStatus() {
    try {
        const response = await fetch("/status", { headers: { "HX-Request": "true" } });
        if (!response.ok) {
            return;
        }
        const status = await response.json();
        setEngineChip("text", status.text);
        setEngineChip("image", status.image);
    } catch (_) {
        // keep polling quiet
    }
}

function typewriteLatestAssistant() {
    const target = document.querySelector('.story-block.assistant:last-of-type .message-body[data-typewriter="pending"]');
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

document.addEventListener("DOMContentLoaded", () => {
    scrollTimelineToBottom();
    refreshEngineStatus();
    window.setInterval(refreshEngineStatus, 1200);
});

document.body.addEventListener("htmx:beforeRequest", (event) => {
    const source = event.detail.elt;
    if (source && source.dataset && source.dataset.action) {
        document.body.dataset.lastAction = source.dataset.action;
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

    refreshEngineStatus();
});

document.body.addEventListener("htmx:oobAfterSwap", (event) => {
    if (event.target && event.target.id === "timeline") {
        scrollTimelineToBottom();
    }
    refreshEngineStatus();
});
