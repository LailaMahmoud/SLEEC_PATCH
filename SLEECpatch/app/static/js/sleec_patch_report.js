const reportState = {
    data: null,
    details: [],
    selectedIndex: -1
};

const reportEls = {};

document.addEventListener("DOMContentLoaded", () => {
    [
        "reportUseCase",
        "includePatchedSleec",
        "loadReportButton",
        "jsonLink",
        "metricTotalRows",
        "metricVerifiedRows",
        "metricLlmRows",
        "metricDetRows",
        "metricAvgTime",
        "summaryCount",
        "summaryOutput",
        "breakdownOutput",
        "detailCount",
        "detailsOutput",
        "patchDetailOutput",
        "philosopherOutput",
        "logsOutput",
        "reportToast"
    ].forEach((id) => {
        reportEls[id] = document.getElementById(id);
    });

    reportEls.loadReportButton.addEventListener("click", loadReportData);
    reportEls.reportUseCase.addEventListener("change", updateJsonLink);
    reportEls.includePatchedSleec.addEventListener("change", updateJsonLink);

    loadReportData();
});

async function loadReportData() {
    setLoading(true);
    updateJsonLink();

    try {
        const response = await fetch(reportUrl(), {
            headers: {
                "Accept": "application/json"
            }
        });
        const data = await response.json().catch(() => ({}));

        if (!response.ok || data.status === "ERROR") {
            throw new Error(data.error || `Request failed: ${response.status}`);
        }

        reportState.data = data;
        reportState.details = data.evaluation_details || [];
        reportState.selectedIndex = reportState.details.length ? 0 : -1;

        renderReport();
        showToast(`Loaded ${reportState.details.length} saved patch row${reportState.details.length === 1 ? "" : "s"}.`);
    } catch (error) {
        showToast(error.message);
    } finally {
        setLoading(false);
    }
}

function reportUrl() {
    const params = new URLSearchParams();
    const useCase = reportEls.reportUseCase.value;

    if (useCase) {
        params.set("use_case", useCase);
    }

    params.set("include_patched_sleec", reportEls.includePatchedSleec.checked ? "1" : "0");

    return `/api/sleec-patch/report-data?${params.toString()}`;
}

function updateJsonLink() {
    reportEls.jsonLink.href = reportUrl();
}

function renderReport() {
    const data = reportState.data || {};
    const metrics = data.report_metrics || {};

    reportEls.metricTotalRows.textContent = metrics.total_patch_rows || 0;
    reportEls.metricVerifiedRows.textContent = metrics.verified_patch_rows || 0;
    reportEls.metricLlmRows.textContent = metrics.llm_patch_rows || 0;
    reportEls.metricDetRows.textContent = metrics.deterministic_patch_rows || 0;
    reportEls.metricAvgTime.textContent = `${Number(metrics.avg_total_time_seconds || 0).toFixed(3)}s`;

    renderSummary(data.evaluation_summary || []);
    renderBreakdowns(metrics);
    renderDetails();
    renderSelectedPatch();
    renderPhilosopher(data);
    renderLogs(data);
}

function renderSummary(rows) {
    reportEls.summaryCount.textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;

    if (!rows.length) {
        reportEls.summaryOutput.className = "table-wrap empty-state";
        reportEls.summaryOutput.textContent = "No stored evaluation summary.";
        return;
    }

    reportEls.summaryOutput.className = "table-wrap";
    reportEls.summaryOutput.innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>Use Case</th>
                    <th>Total</th>
                    <th>Verified</th>
                    <th>Avg Attempts</th>
                    <th>Avg Time</th>
                    <th>Modified</th>
                    <th>Added</th>
                    <th>Deleted</th>
                    <th>Review</th>
                </tr>
            </thead>
            <tbody>
                ${rows.map((row) => `
                    <tr>
                        <td>${escapeHTML(row.use_case)}</td>
                        <td>${escapeHTML(row.total_records || 0)}</td>
                        <td>${escapeHTML(row.verified_patches || 0)}</td>
                        <td>${formatNumber(row.avg_attempts)}</td>
                        <td>${formatNumber(row.avg_total_time)}s</td>
                        <td>${escapeHTML(row.rules_modified || 0)}</td>
                        <td>${escapeHTML(row.rules_added || 0)}</td>
                        <td>${escapeHTML(row.rules_deleted || 0)}</td>
                        <td>${escapeHTML(row.social_review_needed || 0)}</td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    `;
}

function renderBreakdowns(metrics) {
    const groups = [
        ["Use Case", metrics.by_use_case || {}],
        ["Issue Type", metrics.by_issue_type || {}],
        ["Operation", metrics.by_operation || {}],
        ["Source", metrics.by_source || {}]
    ];

    reportEls.breakdownOutput.className = "breakdown-grid";
    reportEls.breakdownOutput.innerHTML = groups.map(([title, rows]) => `
        <section>
            <h3>${escapeHTML(title)}</h3>
            ${renderCountList(rows)}
        </section>
    `).join("");
}

function renderCountList(rows) {
    const entries = Object.entries(rows).sort(([a], [b]) => a.localeCompare(b));

    if (!entries.length) {
        return `<div class="empty-state compact">No data.</div>`;
    }

    return entries.map(([name, value]) => `
        <div class="count-row">
            <span>${escapeHTML(name)}</span>
            <strong>${escapeHTML(value)}</strong>
        </div>
    `).join("");
}

function renderDetails() {
    const rows = reportState.details;
    reportEls.detailCount.textContent = `${rows.length} row${rows.length === 1 ? "" : "s"}`;

    if (!rows.length) {
        reportEls.detailsOutput.className = "table-wrap empty-state";
        reportEls.detailsOutput.textContent = "No saved patch rows match this filter.";
        return;
    }

    reportEls.detailsOutput.className = "table-wrap";
    reportEls.detailsOutput.innerHTML = `
        <table>
            <thead>
                <tr>
                    <th>Use Case</th>
                    <th>Issue</th>
                    <th>Patch</th>
                    <th>Operation</th>
                    <th>Source</th>
                    <th>Verified</th>
                    <th>Time</th>
                    <th>Timestamp</th>
                </tr>
            </thead>
            <tbody>
                ${rows.map((row, index) => `
                    <tr class="${index === reportState.selectedIndex ? "is-selected" : ""}" data-index="${index}">
                        <td>${escapeHTML(row.use_case)}</td>
                        <td>${escapeHTML(row.issue_id || row.issue_type || "-")}</td>
                        <td>${escapeHTML(row.patch_id || row.id || "-")}</td>
                        <td><button type="button" class="link-button" data-index="${index}">${escapeHTML(row.operation || "-")}</button></td>
                        <td>${escapeHTML(row.source || "-")}</td>
                        <td>${Number(row.verified) ? "Yes" : "No"}</td>
                        <td>${formatNumber(row.total_time_seconds)}s</td>
                        <td>${escapeHTML(row.timestamp || "-")}</td>
                    </tr>
                `).join("")}
            </tbody>
        </table>
    `;

    reportEls.detailsOutput.querySelectorAll("tr[data-index], .link-button").forEach((el) => {
        el.addEventListener("click", () => {
            reportState.selectedIndex = Number(el.dataset.index || el.closest("tr").dataset.index);
            renderDetails();
            renderSelectedPatch();
        });
    });
}

function renderSelectedPatch() {
    const row = reportState.details[reportState.selectedIndex];

    if (!row) {
        reportEls.patchDetailOutput.className = "empty-state";
        reportEls.patchDetailOutput.textContent = "No patch selected.";
        return;
    }

    reportEls.patchDetailOutput.className = "patch-detail";
    reportEls.patchDetailOutput.innerHTML = `
        <div class="detail-meta">
            <span>${escapeHTML(row.use_case || "Unknown")}</span>
            <span>${escapeHTML(row.issue_id || "No issue id")}</span>
            <span>${escapeHTML(row.issue_type || "No issue type")}</span>
            <span>${escapeHTML(row.source || "No source")}</span>
        </div>
        <h3>${escapeHTML(row.patch_id || `Patch row ${row.id}`)}</h3>
        <dl class="detail-list">
            <div><dt>Operation</dt><dd>${escapeHTML(row.operation || "-")}</dd></div>
            <div><dt>Target Rule</dt><dd>${escapeHTML(row.target_rule_id || "-")}</dd></div>
            <div><dt>Attempts</dt><dd>${escapeHTML(row.attempts || 0)}</dd></div>
            <div><dt>Expert Match</dt><dd>${Number(row.expert_match) ? "Yes" : "No"}</dd></div>
            <div><dt>Philosopher Decision</dt><dd>${escapeHTML(row.philosopher_decision || "Pending")}</dd></div>
        </dl>
        <h4>Original Rule</h4>
        <pre>${escapeHTML(row.original_rule || "Not stored.")}</pre>
        <h4>Proposed Rule</h4>
        <pre>${escapeHTML(row.proposed_rule || "Not stored.")}</pre>
        <h4>Explanation</h4>
        <p>${escapeHTML(row.natural_language_explanation || "No explanation stored.")}</p>
        ${row.patched_sleec ? `<h4>Patched SLEEC</h4><pre>${escapeHTML(row.patched_sleec)}</pre>` : ""}
    `;
}

function renderPhilosopher(data) {
    const metrics = data.philosopher_review_metrics?.overall || {};
    const legacySummary = data.philosopher_review_summary || {};
    const reviews = data.philosopher_reviews || [];

    reportEls.philosopherOutput.className = "summary-stack";
    reportEls.philosopherOutput.innerHTML = `
        <div class="count-row"><span>LLM review rows</span><strong>${escapeHTML(metrics.total || 0)}</strong></div>
        <div class="count-row"><span>Pending</span><strong>${escapeHTML(metrics.pending || 0)}</strong></div>
        <div class="count-row"><span>Accepted</span><strong>${escapeHTML(metrics.accepted || legacySummary.accepted || 0)}</strong></div>
        <div class="count-row"><span>Rejected</span><strong>${escapeHTML(metrics.rejected || legacySummary.rejected || 0)}</strong></div>
        <div class="count-row"><span>Saved review records</span><strong>${escapeHTML(reviews.length)}</strong></div>
    `;
}

function renderLogs(data) {
    const runs = data.experiment_runs || [];
    const candidates = data.experiment_candidates || [];
    const verifications = data.experiment_verifications || [];
    const persistence = data.persistence || {};

    reportEls.logsOutput.className = "summary-stack";
    reportEls.logsOutput.innerHTML = `
        <div class="count-row"><span>Backend</span><strong>${escapeHTML(persistence.backend || "-")}</strong></div>
        <div class="count-row"><span>Total patch rows</span><strong>${escapeHTML(persistence.total_patch_rows || 0)}</strong></div>
        <div class="count-row"><span>Pipeline runs</span><strong>${escapeHTML(runs.length)}</strong></div>
        <div class="count-row"><span>Patch candidates</span><strong>${escapeHTML(candidates.length)}</strong></div>
        <div class="count-row"><span>Patch verifications</span><strong>${escapeHTML(verifications.length)}</strong></div>
        <div class="count-row"><span>Latest patch</span><strong>${escapeHTML(persistence.latest_patch_timestamp || "-")}</strong></div>
    `;
}

function setLoading(isLoading) {
    reportEls.loadReportButton.disabled = isLoading;
    reportEls.loadReportButton.textContent = isLoading ? "Loading..." : "Load Report Data";
}

function showToast(message) {
    reportEls.reportToast.textContent = message;
    reportEls.reportToast.classList.add("is-visible");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
        reportEls.reportToast.classList.remove("is-visible");
    }, 2400);
}

function formatNumber(value) {
    return Number(value || 0).toFixed(2);
}

function escapeHTML(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
