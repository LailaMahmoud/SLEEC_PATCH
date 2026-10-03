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
        "latexLink",
        "reportScope",
        "statPatches",
        "statPatchesSub",
        "statVerified",
        "statVerifiedSub",
        "statRuns",
        "statRunsSub",
        "statTime",
        "sourceOutput",
        "expertOutput",
        "summaryCount",
        "summaryOutput",
        "issueTypeOutput",
        "operationOutput",
        "detailCount",
        "detailsOutput",
        "patchDetailOutput",
        "diagnosisCount",
        "diagnosisOutput",
        "logsOutput",
        "reportToast"
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
    const scope = reportEls.reportUseCase.value || "all use cases";
    setLoading(true);
    updateJsonLink();
    reportState.data = null;
    reportState.details = [];
    reportState.selectedIndex = -1;
    renderReport();
    reportEls.reportScope.textContent = `Loading results for ${scope}…`;

    try {
        const response = await fetch(reportUrl(), {
            cache: "no-store",
            headers: { "Accept": "application/json" }
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
        const latest = data.evaluation_details?.[0]?.timestamp;
        reportEls.reportScope.textContent = `Showing ${scope}. Every saved run is included, so repeating a run adds more patches.`
            + (latest ? ` Latest patch saved ${formatDate(latest)}.` : "");
    } catch (error) {
        if (version !== reportState.requestVersion) return;
        reportEls.reportScope.textContent = `Could not load results for ${scope}.`;
        showToast(error.message);
    } finally {
        if (version === reportState.requestVersion) setLoading(false);
    }
}

function reportUrl() {
    const params = new URLSearchParams();
    const useCase = reportEls.reportUseCase.value;
    if (useCase) params.set("use_case", useCase);
    params.set("include_patched_sleec", reportEls.includePatchedSleec.checked ? "1" : "0");
    return `/api/sleec-patch/report-data?${params.toString()}`;
}

function updateJsonLink() {
    reportEls.jsonLink.href = reportUrl();
    const params = new URLSearchParams();
    if (reportEls.reportUseCase.value) params.set("use_case", reportEls.reportUseCase.value);
    reportEls.latexLink.href = `/api/sleec-patch/download-report-latex?${params.toString()}`;
}

function renderReport() {
    const data = reportState.data || {};
    const metrics = data.report_metrics || {};

    renderHeadline(metrics);
    renderSources(metrics);
    renderExpert(data.philosopher_review_metrics?.overall || {});
    renderSummary(data.evaluation_summary || []);
    renderBars(reportEls.issueTypeOutput, metrics.by_issue_type || {});
    renderBars(reportEls.operationOutput, metrics.by_operation || {});
    renderDetails();
    renderSelectedPatch();
    renderDiagnoses(data.recorded_diagnoses || []);
    renderLogs(data);
}

/* ── 1. Headline numbers ── */
function renderHeadline(metrics) {
    const total = Number(metrics.total_patch_rows || 0);
    const verified = Number(metrics.verified_patch_rows || 0);
    const runs = Number(metrics.repair_run_count || 0);

    reportEls.statPatches.textContent = total;
    reportEls.statPatchesSub.textContent = runs
        ? `About ${formatNumber(total / runs, 1)} per repair run`
        : "No repair runs saved yet";

    reportEls.statVerified.textContent = verified;
    reportEls.statVerifiedSub.textContent = total
        ? `${percent(verified, total)} of proposed patches`
        : "Nothing to verify yet";

    reportEls.statRuns.textContent = runs;
    reportEls.statRunsSub.textContent = metrics.avg_run_attempts == null
        ? "One run repairs one selected issue"
        : `${formatNumber(metrics.avg_run_attempts, 1)} attempts per run on average`;

    reportEls.statTime.textContent = formatSeconds(metrics.avg_run_time_seconds);
}

/* ── 2. Source split + expert verdicts ── */
function renderSources(metrics) {
    const det = Number(metrics.deterministic_patch_rows || 0);
    const llm = Number(metrics.llm_patch_rows || 0);
    const total = det + llm;

    if (!total) {
        reportEls.sourceOutput.innerHTML = `<div class="empty-state">No patches saved yet.</div>`;
        return;
    }

    reportEls.sourceOutput.innerHTML = `
        <div class="split-figures">
            <div><span class="stat-label">Rule-based</span><strong>${det}</strong><small>${percent(det, total)}</small></div>
            <div><span class="stat-label">AI-generated</span><strong>${llm}</strong><small>${percent(llm, total)}</small></div>
        </div>
        <div class="meter" role="img" aria-label="${det} rule-based and ${llm} AI-generated patches">
            <span class="is-det" style="width:${(det / total) * 100}%"></span>
            <span class="is-llm" style="width:${(llm / total) * 100}%"></span>
        </div>
        <div class="legend">
            <span><i style="background:var(--accent)"></i>Rule-based</span>
            <span><i style="background:var(--peach)"></i>AI-generated</span>
        </div>
    `;
}

function renderExpert(overall) {
    const total = Number(overall.total || 0);
    const accepted = Number(overall.accepted || 0);
    const rejected = Number(overall.rejected || 0);
    const pending = Number(overall.pending || 0);

    if (!total) {
        reportEls.expertOutput.innerHTML = `<div class="empty-state">No verified AI-generated patches to review yet.</div>`;
        return;
    }

    reportEls.expertOutput.innerHTML = `
        <div class="split-figures">
            <div><span class="stat-label">Accepted</span><strong>${accepted}</strong></div>
            <div><span class="stat-label">Rejected</span><strong>${rejected}</strong></div>
            <div><span class="stat-label">Still to review</span><strong>${pending}</strong></div>
            <div><span class="stat-label">Acceptance rate</span><strong>${accepted + rejected ? percent(accepted, accepted + rejected) : "–"}</strong></div>
        </div>
        <div class="meter" role="img" aria-label="${accepted} accepted, ${rejected} rejected, ${pending} still to review">
            <span class="is-accepted" style="width:${(accepted / total) * 100}%"></span>
            <span class="is-rejected" style="width:${(rejected / total) * 100}%"></span>
        </div>
        <div class="legend">
            <span><i style="background:var(--success)"></i>Accepted</span>
            <span><i style="background:var(--danger)"></i>Rejected</span>
            <span><i style="background:var(--surface-2);box-shadow:inset 0 0 0 1px var(--border)"></i>Still to review</span>
        </div>
    `;
}

/* ── 3. Per use case ── */
function renderSummary(rows) {
    reportEls.summaryCount.textContent = `${rows.length} use case${rows.length === 1 ? "" : "s"}`;

    if (!rows.length) {
        reportEls.summaryOutput.innerHTML = `<div class="empty-state">No saved results for this selection yet. Run a repair in the workbench to see it here.</div>`;
        return;
    }

    reportEls.summaryOutput.innerHTML = `
        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Use case</th>
                        <th class="num">Repair runs</th>
                        <th class="num">Patches</th>
                        <th class="num">Verified</th>
                        <th>Rules changed</th>
                        <th class="num">Avg time / run</th>
                        <th class="num">Need expert review</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map((row) => {
                        const total = Number(row.total_records || 0);
                        const verified = Number(row.verified_patches || 0);
                        return `
                        <tr>
                            <td><strong>${escapeHTML(row.use_case)}</strong></td>
                            <td class="num">${escapeHTML(row.repair_run_count || 0)}</td>
                            <td class="num">${total}</td>
                            <td class="num">${verified}${total ? `<span class="pct">${percent(verified, total)}</span>` : ""}</td>
                            <td>
                                <span class="rule-changes">
                                    <span><b>${escapeHTML(row.rules_modified || 0)}</b> modified</span>
                                    <span><b>${escapeHTML(row.rules_added || 0)}</b> added</span>
                                    <span><b>${escapeHTML(row.rules_deleted || 0)}</b> deleted</span>
                                </span>
                            </td>
                            <td class="num">${formatSeconds(row.avg_run_time)}</td>
                            <td class="num">${escapeHTML(row.social_review_needed || 0)}</td>
                        </tr>`;
                    }).join("")}
                </tbody>
            </table>
        </div>
    `;
}

/* ── 4. Breakdowns ── */
function renderBars(container, rows) {
    const entries = Object.entries(rows).sort(([, a], [, b]) => b - a);

    if (!entries.length) {
        container.innerHTML = `<div class="empty-state">No data yet.</div>`;
        return;
    }

    const max = Math.max(...entries.map(([, value]) => Number(value) || 0), 1);
    container.innerHTML = `
        <div class="bar-list">
            ${entries.map(([name, value]) => `
                <div class="bar-row">
                    <span class="bar-name" title="${escapeHTML(name)}">${escapeHTML(humanize(name))}</span>
                    <span class="meter"><span class="is-fill" style="width:${(Number(value) / max) * 100}%"></span></span>
                    <span class="bar-value">${escapeHTML(value)}</span>
                </div>
            `).join("")}
        </div>
    `;
}

/* ── 5. Explorer ── */
function renderDetails() {
    const rows = reportState.details;
    reportEls.detailCount.textContent = `${rows.length} patch${rows.length === 1 ? "" : "es"}`;

    if (!rows.length) {
        reportEls.detailsOutput.innerHTML = `<div class="empty-state">No saved patches match this filter.</div>`;
        return;
    }

    reportEls.detailsOutput.innerHTML = `
        <div class="table-wrap">
            <table class="data-table">
                <thead>
                    <tr>
                        <th>Operation</th>
                        <th>Use case</th>
                        <th>Issue</th>
                        <th>Source</th>
                        <th>Status</th>
                        <th class="num">Time</th>
                        <th>Saved</th>
                    </tr>
                </thead>
                <tbody>
                    ${rows.map((row, index) => `
                        <tr class="is-clickable ${index === reportState.selectedIndex ? "is-selected" : ""}"
                            data-index="${index}" tabindex="0"
                            aria-selected="${index === reportState.selectedIndex}">
                            <td><strong>${escapeHTML(humanize(row.operation))}</strong></td>
                            <td>${escapeHTML(row.use_case || "–")}</td>
                            <td>${escapeHTML(row.issue_id || humanize(row.issue_type) || "–")}</td>
                            <td class="nowrap">${escapeHTML(sourceLabel(row.source))}</td>
                            <td>${verifiedBadge(row.verified)}</td>
                            <td class="num">${formatSeconds(row.total_time_seconds)}</td>
                            <td class="nowrap" title="${escapeHTML(formatDate(row.timestamp))}">${escapeHTML(formatShortDate(row.timestamp))}</td>
                        </tr>
                    `).join("")}
                </tbody>
            </table>
        </div>
    `;

    reportEls.detailsOutput.querySelectorAll("tr[data-index]").forEach((tr) => {
        const select = () => {
            reportState.selectedIndex = Number(tr.dataset.index);
            reportEls.detailsOutput.querySelectorAll("tr[data-index]").forEach((other) => {
                const isSelected = other === tr;
                other.classList.toggle("is-selected", isSelected);
                other.setAttribute("aria-selected", isSelected);
            });
            renderSelectedPatch();
        };
        tr.addEventListener("click", select);
        tr.addEventListener("keydown", (event) => {
            if (event.key === "Enter" || event.key === " ") {
                event.preventDefault();
                select();
            }
        });
    });
}

function renderSelectedPatch() {
    const row = reportState.details[reportState.selectedIndex];

    if (!row) {
        reportEls.patchDetailOutput.innerHTML = `<div class="empty-state">Select a patch to inspect it.</div>`;
        return;
    }

    const decision = String(row.philosopher_decision || "").trim();
    const decisionText = decision
        || (String(row.source).toLowerCase() === "llm" && Number(row.verified) ? "Awaiting review" : "Not required");

    reportEls.patchDetailOutput.innerHTML = `
        <div>
            <div class="detail-meta">
                ${verifiedBadge(row.verified)}
                <span class="badge">${escapeHTML(sourceLabel(row.source))}</span>
            </div>
            <h3 style="margin-top:10px">${escapeHTML(humanize(row.operation))}</h3>
            <p class="muted" style="font-size:13px">${escapeHTML([row.use_case, row.issue_id || humanize(row.issue_type), row.patch_id].filter(Boolean).join(" · "))}</p>
        </div>
        <dl class="detail-facts">
            <div><dt>Target rule</dt><dd>${escapeHTML(row.target_rule_id || "–")}</dd></div>
            <div><dt>Attempts</dt><dd>${escapeHTML(row.attempts || 0)}</dd></div>
            <div><dt>Matches expert fix</dt><dd>${Number(row.expert_match) ? "Yes" : "No"}</dd></div>
            <div><dt>SLEEC expert decision</dt><dd>${escapeHTML(decisionText)}</dd></div>
        </dl>
        <section>
            <h4>Original rule</h4>
            <pre>${escapeHTML(row.original_rule || "Not stored.")}</pre>
        </section>
        <section class="after">
            <h4>Proposed rule</h4>
            <pre>${escapeHTML(row.proposed_rule || "Not stored.")}</pre>
        </section>
        <section>
            <h4>Explanation</h4>
            <p style="font-size:14px">${escapeHTML(row.natural_language_explanation || "No explanation stored.")}</p>
        </section>
        ${row.patched_sleec ? `<section><h4>Full patched specification</h4><pre>${escapeHTML(row.patched_sleec)}</pre></section>` : ""}
    `;
}

/* ── 6. Technical records ── */
function renderDiagnoses(rows) {
    reportEls.diagnosisCount.textContent = `${rows.length} run${rows.length === 1 ? "" : "s"}`;

    if (!rows.length) {
        reportEls.diagnosisOutput.innerHTML = `<div class="empty-state">No diagnosis records saved with repair runs for this selection.</div>`;
        return;
    }

    reportEls.diagnosisOutput.innerHTML = `
        <div class="table-wrap">
            <table class="data-table">
                <thead><tr><th>Use case</th><th>Run</th><th>Input fingerprint</th>
                    <th class="num">Issues found</th><th>Issue repaired</th><th>Saved</th></tr></thead>
                <tbody>
                ${rows.map((row) => `<tr>
                    <td>${escapeHTML(row.use_case)}</td>
                    <td title="${escapeHTML(row.run_id)}"><code>${escapeHTML(String(row.run_id || "").slice(0, 12))}</code></td>
                    <td title="${escapeHTML(row.input_sha256 || "")}">${row.input_sha256 ? `<code>${escapeHTML(row.input_sha256.slice(0, 12))}</code>` : "Not recorded"}</td>
                    <td class="num">${row.status === "recorded" && Number.isInteger(row.issue_count) ? row.issue_count
                        : (row.status === "inconsistent_record" ? "Inconsistent" : "Not recorded")}</td>
                    <td>${escapeHTML(row.selected_issue_id || "–")}</td>
                    <td>${escapeHTML(formatDate(row.timestamp))}</td>
                </tr>`).join("")}
                </tbody>
            </table>
        </div>`;
}

function renderLogs(data) {
    const persistence = data.persistence || {};
    const facts = [
        ["Storage backend", persistence.backend || "–"],
        ["Pipeline runs logged", (data.experiment_runs || []).length],
        ["Candidate patches logged", (data.experiment_candidates || []).length],
        ["Verification checks logged", (data.experiment_verifications || []).length],
        ["Expert review records", (data.philosopher_reviews || []).length]
    ];

    reportEls.logsOutput.innerHTML = `
        <div class="fact-list">
            ${facts.map(([label, value]) => `<div class="fact"><span>${escapeHTML(label)}</span><strong>${escapeHTML(value)}</strong></div>`).join("")}
        </div>
    `;
}

/* ── Helpers ── */
function setLoading(isLoading) {
    reportEls.loadReportButton.disabled = isLoading;
    reportEls.loadReportButton.textContent = isLoading ? "Loading…" : "Reload";
}

function showToast(message) {
    reportEls.reportToast.textContent = message;
    reportEls.reportToast.classList.add("is-visible");
    window.clearTimeout(showToast.timer);
    showToast.timer = window.setTimeout(() => {
        reportEls.reportToast.classList.remove("is-visible");
    }, 3000);
}

function verifiedBadge(value) {
    return Number(value)
        ? `<span class="badge verified">Verified</span>`
        : `<span class="badge unverified">Not verified</span>`;
}

function sourceLabel(source) {
    const value = String(source || "").toLowerCase();
    if (value === "llm") return "AI-generated";
    if (value === "deterministic") return "Rule-based";
    return source ? humanize(source) : "Unknown";
}

function humanize(value) {
    const text = String(value || "").replace(/_/g, " ").trim();
    return text ? text.charAt(0).toUpperCase() + text.slice(1) : "";
}

function percent(part, whole) {
    return whole ? `${Math.round((part / whole) * 100)}%` : "–";
}

function formatNumber(value, digits = 2) {
    return Number(value || 0).toFixed(digits);
}

function formatSeconds(value) {
    if (value === null || value === undefined || value === "") return "–";
    const seconds = Number(value);
    if (!Number.isFinite(seconds)) return "–";
    if (seconds >= 60) return `${Math.floor(seconds / 60)}m ${Math.round(seconds % 60)}s`;
    return `${seconds.toFixed(seconds < 10 ? 1 : 0)}s`;
}

function formatDate(value) {
    if (!value) return "–";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString(undefined, { year: "numeric", month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

function formatShortDate(value) {
    if (!value) return "–";
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleDateString(undefined, { month: "short", day: "numeric" });
}

function escapeHTML(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
