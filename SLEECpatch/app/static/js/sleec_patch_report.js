const reportState = {
    data: null,
    details: [],
    selectedIndex: -1,
    requestVersion: 0
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
        "reportToast",
        "diagnosisOutput",
        "diagnosisCount",
        "reportScope"
    ].forEach((id) => {
        reportEls[id] = document.getElementById(id);
    });

    reportEls.loadReportButton.addEventListener("click", loadReportData);
    reportEls.reportUseCase.addEventListener("change", loadReportData);
    reportEls.includePatchedSleec.addEventListener("change", loadReportData);

    loadReportData();
});

async function loadReportData() {
    const version = ++reportState.requestVersion;
    const scope = reportEls.reportUseCase.value || "All use cases";
    setLoading(true);
    updateJsonLink();
    reportState.data = null;
    reportState.details = [];
    reportState.selectedIndex = -1;
    renderReport();
    reportEls.reportScope.textContent = `Loading ${scope}…`;

    try {
        const response = await fetch(reportUrl(), {
            cache: "no-store",
            headers: {
                "Accept": "application/json"
            }
        });
        const data = await response.json().catch(() => ({}));
        if (version !== reportState.requestVersion) return;

        if (!response.ok || data.status !== "OK" || !Array.isArray(data.evaluation_details)) {
            throw new Error(data.error || `Request failed: ${response.status}`);
        }

        reportState.data = data;
        reportState.details = data.evaluation_details || [];
        reportState.selectedIndex = reportState.details.length ? 0 : -1;

        renderReport();
        reportEls.reportScope.textContent = `${scope}: saved patch records across all recorded runs. Repeated runs may add more patch records.`;
        showToast(`Loaded ${reportState.details.length} saved patch row${reportState.details.length === 1 ? "" : "s"}.`);
    } catch (error) {
        if (version !== reportState.requestVersion) return;
        reportEls.reportScope.textContent = `Could not load ${scope}. No results are displayed for this selection.`;
        showToast(error.message);
    } finally {
        if (version === reportState.requestVersion) setLoading(false);
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
    reportEls.metricAvgTime.textContent = formatSeconds(metrics.avg_run_time_seconds);

    renderSummary(data.evaluation_summary || []);
    renderDiagnoses(data.recorded_diagnoses || []);
    renderBreakdowns(metrics);
    renderDetails();
    renderSelectedPatch();
    renderPhilosopher(data);
    renderLogs(data);
}

function renderSummary(rows) {
    reportEls.summaryCount.textContent = `${rows.length} use case${rows.length === 1 ? "" : "s"}`;

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
                    <th>Patch Records</th>
                    <th>Verified Patches</th>
                    <th>Repair Runs</th>
                    <th>Avg Attempts / Run</th>
                    <th>Avg Time / Run</th>
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
                        <td>${escapeHTML(row.repair_run_count || 0)}</td>
                        <td>${formatOptionalNumber(row.avg_run_attempts)}</td>
                        <td>${formatSeconds(row.avg_run_time)}</td>
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

function renderDiagnoses(rows) {
    reportEls.diagnosisCount.textContent = `${rows.length} repair run${rows.length === 1 ? "" : "s"}`;
    reportEls.diagnosisOutput.className = rows.length ? "table-wrap" : "table-wrap empty-state";
    if (!rows.length) {
        reportEls.diagnosisOutput.textContent = "No diagnosis records saved with repair runs for this selection.";
        return;
    }
    reportEls.diagnosisOutput.innerHTML = `
        <table><thead><tr><th>Use Case</th><th>Repair Run</th><th>Input Fingerprint</th>
            <th>Diagnosed Issues</th><th>Selected Issue</th><th>Timestamp</th></tr></thead><tbody>
        ${rows.map(row => `<tr>
            <td>${escapeHTML(row.use_case)}</td>
            <td title="${escapeHTML(row.run_id)}">${escapeHTML(String(row.run_id || "").slice(0, 12))}</td>
            <td title="${escapeHTML(row.input_sha256 || "")}">${escapeHTML(row.input_sha256 ? row.input_sha256.slice(0, 12) : "Not recorded")}</td>
            <td>${row.status === "recorded" && Number.isInteger(row.issue_count) ? row.issue_count :
                (row.status === "inconsistent_record" ? "Inconsistent record" : "Not recorded")}</td>
            <td>${escapeHTML(row.selected_issue_id || "—")}</td>
            <td>${escapeHTML(row.timestamp || "—")}</td>
        </tr>`).join("")}</tbody></table>`;
}

function renderBreakdowns(metrics) {
    const groups = [
        ["Use Case", metrics.by_use_case || {}],
        ["Patches by Issue Type", metrics.by_issue_type || {}],
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
    const reviews = data.philosopher_reviews || [];

    reportEls.philosopherOutput.className = "summary-stack";
    reportEls.philosopherOutput.innerHTML = `
        <div class="count-row"><span>LLM review rows</span><strong>${escapeHTML(metrics.total || 0)}</strong></div>
        <div class="count-row"><span>Pending</span><strong>${escapeHTML(metrics.pending || 0)}</strong></div>
        <div class="count-row"><span>Accepted</span><strong>${escapeHTML(metrics.accepted ?? 0)}</strong></div>
        <div class="count-row"><span>Rejected</span><strong>${escapeHTML(metrics.rejected ?? 0)}</strong></div>
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
        <div class="count-row"><span>Saved patches (selected use cases)</span><strong>${escapeHTML(data.report_metrics?.total_patch_rows || 0)}</strong></div>
        <div class="count-row"><span>Pipeline runs</span><strong>${escapeHTML(runs.length)}</strong></div>
        <div class="count-row"><span>Patch candidates</span><strong>${escapeHTML(candidates.length)}</strong></div>
        <div class="count-row"><span>Patch verifications</span><strong>${escapeHTML(verifications.length)}</strong></div>
        <div class="count-row"><span>Latest saved patch (selected use cases)</span><strong>${escapeHTML(data.evaluation_details?.[0]?.timestamp || "-")}</strong></div>
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

function formatOptionalNumber(value) {
    return value === null || value === undefined ? "Not recorded" : formatNumber(value);
}

function formatSeconds(value) {
    return value === null || value === undefined ? "Not recorded" : `${Number(value).toFixed(3)}s`;
}

function escapeHTML(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
