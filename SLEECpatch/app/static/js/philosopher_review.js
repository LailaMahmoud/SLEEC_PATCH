const reviewState = {
    patches: [],
    selectedIndex: -1,
    saving: false
};

const els = {};

document.addEventListener("DOMContentLoaded", () => {
    [
        "reviewUseCase",
        "includeReviewed",
        "loadQueueButton",
        "refreshMetricsButton",
        "metricTotal",
        "metricPending",
        "metricAccepted",
        "metricRejected",
        "metricRate",
        "queueCount",
        "queueList",
        "detailEmpty",
        "patchDetail",
        "detailMeta",
        "detailTitle",
        "decisionBadge",
        "originalRule",
        "proposedRule",
        "patchExplanation",
        "reviewComments",
        "acceptButton",
        "rejectButton",
        "useCaseBreakdown",
        "operationBreakdown",
        "reviewToast"
    ].forEach((id) => {
        els[id] = document.getElementById(id);
    });

    els.loadQueueButton.addEventListener("click", loadReviewQueue);
    els.refreshMetricsButton.addEventListener("click", refreshMetrics);
    els.acceptButton.addEventListener("click", () => submitDecision("Accepted"));
    els.rejectButton.addEventListener("click", () => submitDecision("Rejected"));

    loadReviewQueue();
});

async function postJSON(url, payload = {}) {
    const response = await fetch(url, {
        method: "POST",
        headers: {
            "Content-Type": "application/json"
        },
        body: JSON.stringify(payload)
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok || data.status === "ERROR") {
        throw new Error(data.error || `Request failed: ${response.status}`);
    }

    return data;
}

function escapeHTML(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function formatDecision(value) {
    const decision = String(value || "").trim();
    return decision || "Pending";
}

function formatRate(value) {
    return `${Math.round(Number(value || 0) * 100)}%`;
}

function selectedPatch() {
    return reviewState.patches[reviewState.selectedIndex] || null;
}

async function loadReviewQueue() {
    setLoading(true);

    try {
        const data = await postJSON("/api/sleec-patch/philosopher-review-queue", {
            use_case: els.reviewUseCase.value,
            include_reviewed: els.includeReviewed.checked
        });

        reviewState.patches = data.patches || [];
        reviewState.selectedIndex = reviewState.patches.length ? 0 : -1;

        renderMetrics(data.metrics);
        renderQueue();
        renderSelectedPatch();
        showToast(`Loaded ${reviewState.patches.length} patch${reviewState.patches.length === 1 ? "" : "es"}.`);
    } catch (error) {
        showToast(error.message);
    } finally {
        setLoading(false);
    }
}

async function refreshMetrics() {
    try {
        const data = await postJSON("/api/sleec-patch/philosopher-review-metrics");
        renderMetrics(data.metrics);
        showToast("Metrics refreshed.");
    } catch (error) {
        showToast(error.message);
    }
}

function renderMetrics(metrics = {}) {
    const overall = metrics.overall || {};

    els.metricTotal.textContent = overall.total || 0;
    els.metricPending.textContent = overall.pending || 0;
    els.metricAccepted.textContent = overall.accepted || 0;
    els.metricRejected.textContent = overall.rejected || 0;
    els.metricRate.textContent = formatRate(overall.acceptance_rate);

    renderBreakdown(els.useCaseBreakdown, metrics.by_use_case || {});
    renderBreakdown(els.operationBreakdown, metrics.by_operation || {});
}

function renderBreakdown(container, rows) {
    const entries = Object.entries(rows).sort(([a], [b]) => a.localeCompare(b));

    if (!entries.length) {
        container.innerHTML = `<div class="empty-state">No data.</div>`;
        return;
    }

    container.innerHTML = entries.map(([name, row]) => `
        <div class="breakdown-row">
            <strong>${escapeHTML(name)}</strong>
            <span>Total ${escapeHTML(row.total || 0)}</span>
            <span>Pending ${escapeHTML(row.pending || 0)}</span>
            <span>Accept ${escapeHTML(row.accepted || 0)}</span>
            <span>${escapeHTML(formatRate(row.acceptance_rate))}</span>
        </div>
    `).join("");
}

function renderQueue() {
    const count = reviewState.patches.length;
    els.queueCount.textContent = `${count} patch${count === 1 ? "" : "es"}`;

    if (!count) {
        els.queueList.className = "queue-list empty-state";
        els.queueList.textContent = "No saved semantic patches match this queue.";
        return;
    }

    els.queueList.className = "queue-list";
    els.queueList.innerHTML = reviewState.patches.map((patch, index) => {
        const title = [
            patch.use_case || "Unknown",
            patch.issue_id || "issue",
            patch.patch_id || `row-${patch.id}`
        ].join(" · ");

        const subline = [
            patch.operation || "operation",
            Number(patch.verified) ? "Verified" : "Pending verification",
            formatDecision(patch.philosopher_decision)
        ].join(" · ");

        return `
            <button type="button"
                    class="queue-item ${index === reviewState.selectedIndex ? "is-active" : ""}"
                    data-index="${index}">
                <strong>${escapeHTML(title)}</strong>
                <span>${escapeHTML(subline)}</span>
            </button>
        `;
    }).join("");

    els.queueList.querySelectorAll(".queue-item").forEach((button) => {
        button.addEventListener("click", () => {
            reviewState.selectedIndex = Number(button.dataset.index);
            renderQueue();
            renderSelectedPatch();
        });
    });
}

function renderSelectedPatch() {
    const patch = selectedPatch();

    if (!patch) {
        els.detailEmpty.hidden = false;
        els.patchDetail.hidden = true;
        return;
    }

    const decision = formatDecision(patch.philosopher_decision);
    const normalized = decision.toLowerCase();

    els.detailEmpty.hidden = true;
    els.patchDetail.hidden = false;
    els.detailMeta.textContent = [
        patch.use_case || "Unknown use case",
        patch.issue_id || "Unknown issue",
        patch.operation || "Unknown operation",
        Number(patch.verified) ? "Verified" : "Pending verification"
    ].join(" · ");
    els.detailTitle.textContent = patch.patch_id || `Patch result ${patch.id}`;
    els.decisionBadge.textContent = decision;
    els.decisionBadge.className = `decision-badge ${normalized}`;
    els.originalRule.textContent = patch.original_rule || "No original rule stored.";
    els.proposedRule.textContent = patch.proposed_rule || "No proposed rule stored.";
    els.patchExplanation.textContent = patch.natural_language_explanation || "No explanation stored.";
    els.reviewComments.value = patch.philosopher_comments || "";
    setDecisionButtonsDisabled(Boolean(patch.philosopher_decision));
}

async function submitDecision(decision) {
    const patch = selectedPatch();

    if (!patch || reviewState.saving) {
        return;
    }

    reviewState.saving = true;
    setDecisionButtonsDisabled(true);

    try {
        const data = await postJSON("/api/sleec-patch/philosopher-review-decision", {
            id: patch.id,
            use_case: patch.use_case,
            issue_id: patch.issue_id,
            issue_type: patch.issue_type,
            patch_id: patch.patch_id,
            operation: patch.operation,
            original_rule: patch.original_rule,
            proposed_rule: patch.proposed_rule,
            natural_language_explanation: patch.natural_language_explanation,
            decision,
            comments: els.reviewComments.value
        });

        patch.philosopher_decision = decision;
        patch.philosopher_comments = els.reviewComments.value;
        patch.review_timestamp = data.saved?.review_timestamp || "";

        if (!els.includeReviewed.checked) {
            reviewState.patches.splice(reviewState.selectedIndex, 1);
            reviewState.selectedIndex = Math.min(
                reviewState.selectedIndex,
                reviewState.patches.length - 1
            );
        }

        renderMetrics(data.metrics);
        renderQueue();
        renderSelectedPatch();
        showToast(`Decision saved: ${decision}.`);
    } catch (error) {
        showToast(error.message);
        setDecisionButtonsDisabled(Boolean(patch.philosopher_decision));
    } finally {
        reviewState.saving = false;
    }
}

function setLoading(isLoading) {
    els.loadQueueButton.disabled = isLoading;
    els.loadQueueButton.textContent = isLoading ? "Loading..." : "Load Queue";
}

function setDecisionButtonsDisabled(disabled) {
    els.acceptButton.disabled = disabled;
    els.rejectButton.disabled = disabled;
}

function showToast(message) {
    els.reviewToast.textContent = message;
    els.reviewToast.classList.add("is-visible");

    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
        els.reviewToast.classList.remove("is-visible");
    }, 3000);
}
