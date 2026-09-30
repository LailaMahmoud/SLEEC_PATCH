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
        "metricPending",
        "metricAccepted",
        "metricRejected",
        "metricRate",
        "meterAccepted",
        "meterRejected",
        "progressHeadline",
        "progressSub",
        "decisionHint",
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
    els.reviewUseCase.addEventListener("change", loadReviewQueue);
    els.includeReviewed.addEventListener("change", loadReviewQueue);
    els.acceptButton.addEventListener("click", () => submitDecision("Accepted"));
    els.rejectButton.addEventListener("click", () => submitDecision("Rejected"));

    showReviewerProfession();
    loadReviewQueue();
});

// The profession typed on the workbench's first step, kept for this browser tab.
function showReviewerProfession() {
    const target = document.getElementById("reviewerProfession");
    let profession = "";
    try {
        profession = (sessionStorage.getItem("sleecPatchProfession") || "").trim();
    } catch (error) {
        profession = "";
    }
    if (!target || !profession) return;
    target.textContent = profession;
    target.title = profession;
    target.hidden = false;
}

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
    } catch (error) {
        showToast(error.message);
    } finally {
        setLoading(false);
    }
}

function renderMetrics(metrics = {}) {
    const overall = metrics.overall || {};
    const total = Number(overall.total || 0);
    const pending = Number(overall.pending || 0);
    const accepted = Number(overall.accepted || 0);
    const rejected = Number(overall.rejected || 0);
    const reviewed = accepted + rejected;

    els.metricPending.textContent = pending;
    els.metricAccepted.textContent = accepted;
    els.metricRejected.textContent = rejected;
    els.metricRate.textContent = reviewed ? formatRate(overall.acceptance_rate) : "–";
    els.meterAccepted.style.width = total ? `${(accepted / total) * 100}%` : "0%";
    els.meterRejected.style.width = total ? `${(rejected / total) * 100}%` : "0%";

    if (!total) {
        els.progressHeadline.textContent = "No patches waiting for review";
        els.progressSub.textContent = "Patches appear here after the workbench verifies an AI-generated repair.";
    } else if (!pending) {
        els.progressHeadline.textContent = "All caught up";
        els.progressSub.textContent = `You have reviewed all ${total} patch${total === 1 ? "" : "es"}.`;
    } else {
        els.progressHeadline.textContent = `${pending} patch${pending === 1 ? "" : "es"} left to review`;
        els.progressSub.textContent = `${reviewed} of ${total} reviewed so far.`;
    }

    renderBreakdown(els.useCaseBreakdown, metrics.by_use_case || {});
    renderBreakdown(els.operationBreakdown, metrics.by_operation || {});
}

function renderBreakdown(container, rows) {
    const entries = Object.entries(rows).sort(([a], [b]) => a.localeCompare(b));

    if (!entries.length) {
        container.innerHTML = `<div class="empty-state">No data yet.</div>`;
        return;
    }

    container.innerHTML = `
        <div class="table-wrap">
            <table class="data-table">
                <thead><tr><th>Name</th><th class="num">Total</th><th class="num">To review</th><th class="num">Accepted</th><th class="num">Rejected</th><th class="num">Acceptance</th></tr></thead>
                <tbody>
                    ${entries.map(([name, row]) => `
                        <tr>
                            <td>${escapeHTML(humanize(name))}</td>
                            <td class="num">${escapeHTML(row.total || 0)}</td>
                            <td class="num">${escapeHTML(row.pending || 0)}</td>
                            <td class="num">${escapeHTML(row.accepted || 0)}</td>
                            <td class="num">${escapeHTML(row.rejected || 0)}</td>
                            <td class="num">${(row.accepted || 0) + (row.rejected || 0) ? escapeHTML(formatRate(row.acceptance_rate)) : "–"}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>
    `;
}

function humanize(value) {
    const text = String(value || "").replace(/_/g, " ").trim();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "Unknown";
}

function decisionClass(decision) {
    const normalized = decision.toLowerCase();
    return ["accepted", "rejected"].includes(normalized) ? normalized : "pending";
}

function renderQueue() {
    const count = reviewState.patches.length;
    els.queueCount.textContent = count;

    if (!count) {
        els.queueList.innerHTML = `<div class="empty-state">${
            els.includeReviewed.checked
                ? "No saved AI patches match this filter."
                : "Nothing left to review here. Tick \u201cAlso show patches I've already reviewed\u201d to revisit past decisions."
        }</div>`;
        return;
    }

    els.queueList.innerHTML = reviewState.patches.map((patch, index) => {
        const decision = formatDecision(patch.philosopher_decision);
        const title = humanize(patch.operation);
        const sub = [patch.use_case || "Unknown use case", patch.issue_id, patch.patch_id].filter(Boolean).join(" · ");

        return `
            <button type="button"
                    class="queue-item ${index === reviewState.selectedIndex ? "is-active" : ""}"
                    data-index="${index}"
                    aria-pressed="${index === reviewState.selectedIndex}">
                <span class="queue-item-top">
                    <span class="queue-item-title">${escapeHTML(title || `Patch ${patch.id}`)}</span>
                    <span class="badge ${decisionClass(decision)}">${escapeHTML(decision === "Pending" ? "To review" : decision)}</span>
                </span>
                <span class="queue-item-sub">${escapeHTML(sub)}</span>
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
    const alreadyDecided = Boolean(patch.philosopher_decision);

    els.detailEmpty.hidden = true;
    els.patchDetail.hidden = false;
    els.detailMeta.textContent = [
        patch.use_case || "Unknown use case",
        patch.issue_id || "Unknown issue",
        patch.patch_id || `Patch ${patch.id}`,
        Number(patch.verified) ? "Verified by the checker" : "Not yet verified"
    ].join(" · ");
    els.detailTitle.textContent = humanize(patch.operation);
    els.decisionBadge.textContent = decision === "Pending" ? "To review" : decision;
    els.decisionBadge.className = `badge ${decisionClass(decision)}`;
    els.decisionHint.textContent = alreadyDecided
        ? `You ${decision.toLowerCase()} this patch${patch.review_timestamp ? ` on ${String(patch.review_timestamp).slice(0, 10)}` : ""}.`
        : "Does the proposed rule keep the intended meaning?";
    els.originalRule.textContent = patch.original_rule || "No original rule stored.";
    els.proposedRule.textContent = patch.proposed_rule || "No proposed rule stored.";
    els.patchExplanation.textContent = patch.natural_language_explanation || "No explanation stored.";
    els.reviewComments.value = patch.philosopher_comments || "";
    setDecisionButtonsDisabled(alreadyDecided);
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
    els.loadQueueButton.textContent = isLoading ? "Loading…" : "Reload";
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
