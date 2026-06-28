let sleecPatchState = {
    sleecText: "",
    issues: [],
    selectedIssue: null,
    verifiedPatches: [],
    log: null
};


function escapeHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}
async function postJSON(url, data) {
    const response = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(data)
    });

    const result = await response.json();

    if (!response.ok) {
        alert(result.error || "Request failed");
        throw new Error(result.error || "Request failed");
    }

    return result;
}

async function diagnoseWFIs() {
    const sleecText = document.getElementById("sleecInput").value.trim();

    if (!sleecText) {
        alert("Please enter SLEEC specification.");
        return;
    }

    const data = await postJSON("/api/sleec-patch/diagnose", {
        sleec_text: sleecText
    });

    console.log("DIAGNOSE DATA:", data);

    sleecPatchState.sleecText = sleecText;
    sleecPatchState.issues = data.issues || [];
    sleecPatchState.rawDiagnosis = data;

    renderIssues();
}

function shortIssueText(value) {
    if (!value) return "";

    let text = String(value);

    text = text.replace(/-{10,}/g, "");
    text = text.replace(/\*{10,}/g, "");
    text = text.replace(/\n\s*\n/g, "\n");

    if (text.length > 500) {
        return text.substring(0, 500) + "\n...";
    }

    return text;
}

function renderIssues() {
    const out = document.getElementById("issuesOutput");

    if (!sleecPatchState.issues.length) {
        out.innerHTML = "<p>No WFIs detected.</p>";
        return;
    }

    let html = "";

    sleecPatchState.issues.forEach((issue, index) => {
        const selectedClass =
            sleecPatchState.selectedIssue &&
            sleecPatchState.selectedIssue.id === issue.id
                ? " selected-issue"
                : "";

        html += `
            <div class="issue-card${selectedClass}" onclick="selectIssue(${index})">
                <div class="issue-header">
                    <span class="issue-type">${issue.issue_type}</span>
                    <span class="issue-id">${issue.id}</span>
                </div>

                <div class="issue-section">
                    <strong>Original Rule(s)</strong>
                    <pre>${(issue.original_rules || []).join("\n") || "No original rule extracted."}</pre>
                </div>

                <div class="issue-section">
                    <strong>Diagnosis Trace</strong>
                    <pre>${shortIssueText(issue.value)}</pre>
                </div>

                <button class="secondary small-btn" onclick="event.stopPropagation(); selectIssue(${index});">
                    Select Issue
                </button>
            </div>
        `;
    });

    out.innerHTML = html;
}

function selectIssue(index) {
    sleecPatchState.selectedIssue = sleecPatchState.issues[index];

    document.getElementById("selectedIssueOutput").innerHTML = `
        <div class="issue-card selected-issue">
            <div class="issue-header">
                <span class="issue-type">${sleecPatchState.selectedIssue.issue_type}</span>
                <span class="issue-id">${sleecPatchState.selectedIssue.id}</span>
            </div>

            <p><strong>Selected WFI diagnosis trace</strong></p>
            <pre>${sleecPatchState.selectedIssue.value}</pre>
        </div>
    `;

    renderIssues();
}

async function generateVerifiedPatches() {

    if (!sleecPatchState.selectedIssue) {
        alert("Select one WFI first.");
        return;
    }

    const useCase =
        document.getElementById("useCase").value.trim() || "Unknown";

    document.getElementById("patchOutput").innerHTML = `
        <div class="patch-card">
            <h3>Generating verified patches...</h3>
            <p>
                SLEEC-PATCH is generating deterministic repairs first,
                then invoking GPT for semantic refinement,
                followed by SLEEC verification and ranking.
            </p>
        </div>
    `;

    document.getElementById("logOutput").innerHTML = `
        <div class="metric-card">
            <h3>Verification running</h3>
            <p>Please wait. This may take several seconds.</p>
        </div>
    `;

    const data = await postJSON(
        "/api/sleec-patch/generate-verified",
        {
            use_case: useCase,
            sleec_text: sleecPatchState.sleecText,
            issue: sleecPatchState.selectedIssue,
            max_attempts: 5
        }
    );

    console.log("VERIFIED PATCH DATA:", data);

    // save everything

    sleecPatchState.deterministicCandidates =
        data.deterministic_candidates || [];

    sleecPatchState.llmCandidates =
        data.llm_candidates || [];

    sleecPatchState.verifiedPatches =
        data.verified_patches || [];

    sleecPatchState.log =
        data.log || {};

    // NEW

    renderCandidatePatches(
        "deterministicOutput",
        sleecPatchState.deterministicCandidates,
        "Deterministic"
    );

    renderCandidatePatches(
        "llmOutput",
        sleecPatchState.llmCandidates,
        "GPT Semantic"
    );

    renderVerifiedPatches();

    renderLog();
}
function renderCandidatePatches(containerId, patches, title) {

    const container = document.getElementById(containerId);

    if (!container) return;

    if (!patches || patches.length === 0) {
        container.innerHTML = `<p>No ${title} candidate repairs.</p>`;
        return;
    }

    let html = "";

    patches.forEach((p, i) => {

        html += `
        <div class="patch-card">

            <h3>${title} ${i + 1}</h3>

            <p><b>Patch ID:</b> ${p.patch_id}</p>

            <p><b>Operation:</b> ${p.operation}</p>

            <p><b>Source:</b> ${p.source}</p>

            <p><b>Original Rule</b></p>

            <pre>${p.original_rule || ""}</pre>

            <p><b>Proposed Patch</b></p>

            <pre>${p.proposed_rule || ""}</pre>

        </div>
        `;
    });

    container.innerHTML = html;
}


function renderVerifiedPatches() {
    const out = document.getElementById("patchOutput");

    if (!sleecPatchState.verifiedPatches.length) {
        out.innerHTML = `
            <div class="patch-card">
                <span class="badge bad">No verified patch found</span>
                <p>The system could not generate a formally verified patch within the attempt limit.</p>
            </div>
        `;
        return;
    }

    let html = "";

sleecPatchState.verifiedPatches.forEach((p) => {

    const ranking = p.ranking || {};

    html += `
        <div class="patch-card">

            <h3>Rank #${p.rank || "-"} — ${p.patch_id} — ${p.operation}</h3>

            <p><strong>Source:</strong> ${p.source || "llm"}</p>

            <p><strong>Ranking Score:</strong> ${p.ranking_score || 0}</p>

            <div class="metric-card">

                <p><strong>Structural Simplicity:</strong> ${ranking.structural_simplicity || 0}</p>

                <p><strong>Logical Simplicity:</strong> ${ranking.logical_simplicity || 0}</p>

                <p><strong>Semantic Clarity:</strong> ${ranking.semantic_clarity || 0}</p>

                <p><strong>Interpretability:</strong> ${ranking.interpretability || 0}</p>

            </div>

            <p><strong>Verified by SLEEC</strong></p>

            <h4>Original Rule</h4>
            <pre>${escapeHtml(p.original_rule || "")}</pre>

            <h4>Proposed Patch</h4>
            <pre>${escapeHtml(p.proposed_rule || "")}</pre>

            <h4>Explanation</h4>
            <p>${escapeHtml(p.natural_language_explanation || "")}</p>

            <h4>Patched SLEEC</h4>
            <pre>${escapeHtml(p.patched_sleec || "")}</pre>

        </div>
    `;
});

    out.innerHTML = html;
}

function renderLog() {
    const log = sleecPatchState.log;
    const out = document.getElementById("logOutput");

    if (!log) {
        out.innerHTML = "No log available.";
        return;
    }

    out.innerHTML = `
        <div class="metric-card">
            <h3>Efficiency Log</h3>

            <p><strong>Attempts:</strong> ${log.attempts}</p>
            <p><strong>Failed patches:</strong> ${log.failed_patch_count}</p>
            <p><strong>Verified patches:</strong> ${log.verified_patch_count}</p>
            <p><strong>Generation time:</strong> ${log.generation_time_seconds}s</p>
            <p><strong>Validation time:</strong> ${log.validation_time_seconds}s</p>
            <p><strong>Total time:</strong> ${log.total_time_seconds}s</p>
            <p><strong>Successful:</strong> ${log.successful ? "Yes" : "No"}</p>
        </div>
    `;
}

async function loadEvaluationSummary() {
    const data = await postJSON("/api/sleec-patch/evaluation-summary", {});

    const out = document.getElementById("summaryOutput");

    if (!data.length) {
        out.innerHTML = "<p>No stored evaluation results yet.</p>";
        return;
    }

    let html = `
        <table>
            <thead>
                <tr>
                    <th>Use Case</th>
                    <th>Verified Patches</th>
                    <th>Avg Attempts</th>
                    <th>Avg Time</th>
                    <th>Rules Modified</th>
                    <th>Rules Added</th>
                    <th>Rules Deleted</th>
                    <th>Capabilities Refined</th>
                    <th>Social Review</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.forEach(r => {
        html += `
            <tr>
                <td>${r.use_case}</td>
                <td>${r.verified_patches || 0}</td>
                <td>${Number(r.avg_attempts || 0).toFixed(2)}</td>
                <td>${Number(r.avg_total_time || 0).toFixed(2)}s</td>
                <td>${r.rules_modified || 0}</td>
                <td>${r.rules_added || 0}</td>
                <td>${r.rules_deleted || 0}</td>
                <td>${r.capabilities_refined || 0}</td>
                <td>${r.social_review_needed || 0}</td>
            </tr>
        `;
    });

    html += "</tbody></table>";

    out.innerHTML = html;
}



async function loadDetailedEvaluationResults() {
    const data = await postJSON("/api/sleec-patch/evaluation-results", {});

    const out = document.getElementById("summaryOutput");

    if (!data.length) {
        out.innerHTML = "<p>No stored detailed results yet.</p>";
        return;
    }

    let html = `
        <table>
            <thead>
                <tr>
                    <th>Use Case</th>
                    <th>Issue ID</th>
                    <th>Issue Type</th>
                    <th>Patch</th>
                    <th>Operation</th>
                    <th>Attempts</th>
                    <th>Time</th>
                    <th>Modified</th>
                    <th>Added</th>
                    <th>Deleted</th>
                    <th>Defeaters</th>
                    <th>Capability Refined</th>
                    <th>Review</th>
                </tr>
            </thead>
            <tbody>
    `;

    data.forEach((r, index) => {
        html += `
            <tr>
                <td>${escapeHtml(r.use_case)}</td>
                <td>${escapeHtml(r.issue_id)}</td>
                <td>${escapeHtml(r.issue_type)}</td>
                <td>${escapeHtml(r.patch_id)}</td>

                <td>
                    <button
                        class="link-btn"
                        onclick="showPatchDetailsFromResults(${index})">
                        ${escapeHtml(r.operation || "-")}
                    </button>
                </td>

                <td>${escapeHtml(r.attempts || 0)}</td>
                <td>${Number(r.total_time_seconds || 0).toFixed(2)}s</td>
                <td>${escapeHtml(r.rules_modified || 0)}</td>
                <td>${escapeHtml(r.rules_added || 0)}</td>
                <td>${escapeHtml(r.rules_deleted || 0)}</td>
                <td>${escapeHtml(r.defeaters_added || 0)}</td>
                <td>${escapeHtml(r.capabilities_refined || 0)}</td>
                <td>${escapeHtml(r.requires_social_scientist_review || 0)}</td>
            </tr>
        `;
    });

    html += "</tbody></table>";

    out.innerHTML = html;

    window.latestDetailedResults = data;
}

function showPatchDetailsFromResults(index) {
    const row = window.latestDetailedResults[index];
    showPatchDetails(row);
}






function showPatchDetails(row) {
    const box = document.getElementById("patchDetailOutput");

    if (!box) {
        alert("Missing patchDetailOutput div in HTML.");
        return;
    }

    box.innerHTML = `
        <div class="patch-card">
            <h3>Patch Details</h3>

            <p><strong>Patch ID:</strong> ${row.patch_id || "-"}</p>
            <p><strong>Issue ID:</strong> ${row.issue_id || "-"}</p>
            <p><strong>Issue Type:</strong> ${row.issue_type || "-"}</p>
            <p><strong>Rule ID:</strong> ${row.target_rule_id || "-"}</p>
            <p><strong>Operation:</strong> ${row.operation || "-"}</p>
            <p><strong>Source:</strong> ${row.source || "-"}</p>

            <h4>Original Rule</h4>
            <pre>${row.original_rule || "Not stored"}</pre>

            <h4>Resolution Patch</h4>
            <pre>${row.proposed_rule || "Not stored"}</pre>

            <h4>Explanation</h4>
            <p>${row.natural_language_explanation || "No explanation stored."}</p>
        </div>
    `;

    box.scrollIntoView({ behavior: "smooth" });
}






async function loadSelectedUseCase() {
    const useCase = document.getElementById("useCase").value;

    const data = await postJSON("/api/sleec-patch/load-usecase", {
        use_case: useCase
    });

    console.log("LOAD RESPONSE:", data);

    document.getElementById("sleecInput").value = data.sleec_text || "";
}

function pct(x) {
    return Math.round((Number(x) || 0) * 100) + "%";
}

async function runEvaluationA() {
    const useCase = document.getElementById("useCase").value;

    const data = await postJSON("/api/sleec-patch/evaluation-a", {
        use_case: useCase
    });

    renderEvaluationA(data.result);
}

async function runEvaluationB() {
    const useCase = document.getElementById("useCase").value;

    const data = await postJSON("/api/sleec-patch/evaluation-b", {
        use_case: useCase
    });

    renderEvaluationB(data.result);
}

async function loadPhilosopherReview() {
    const useCase = document.getElementById("useCase").value;

    const data = await postJSON("/api/sleec-patch/non-deterministic-patches", {
        use_case: useCase
    });

    renderEvaluationC(data);
}

function renderEvaluationA(data) {
    const r = data.result || data;

    const opRows = Object.entries(r.by_operation || {}).map(([op, v]) => `
        <tr>
            <td>${escapeHtml(op)}</td>
            <td>${v.generated}</td>
            <td>${v.matched}</td>
            <td>${pct(v.match_rate)}</td>
        </tr>
    `).join("");

    const patchRows = (r.patch_rows || []).map(p => `
        <tr>
            <td>${escapeHtml(p.issue_id)}</td>
            <td>${escapeHtml(p.patch_id)}</td>
            <td>${escapeHtml(p.operation)}</td>
            <td>${escapeHtml(p.target_rule_id)}</td>
            <td>${p.matched_corrected ? "✅ Match" : "❌ No"}</td>
        </tr>
    `).join("");

    document.getElementById("evaluationAOutput").innerHTML = `
        <div class="eval-cards">
            <div class="eval-card"><b>Total WFIs</b><span>${r.total_wfis || 0}</span></div>
            <div class="eval-card"><b>WFIs With Match</b><span>${r.wfis_with_matching_patch || 0}</span></div>
            <div class="eval-card"><b>Total Patches</b><span>${r.total_patches || 0}</span></div>
            <div class="eval-card"><b>Patch Match Rate</b><span>${pct(r.patch_match_rate)}</span></div>
        </div>

        <h4>Match by Operation</h4>
        <table class="eval-table">
            <thead>
                <tr>
                    <th>Operation</th>
                    <th>Generated</th>
                    <th>Matched</th>
                    <th>Rate</th>
                </tr>
            </thead>
            <tbody>
                ${opRows || `<tr><td colspan="4">No operation results.</td></tr>`}
            </tbody>
        </table>

        <h4>Patch Details</h4>
        <table class="eval-table">
            <thead>
                <tr>
                    <th>Issue</th>
                    <th>Patch</th>
                    <th>Operation</th>
                    <th>Target Rule</th>
                    <th>Match</th>
                </tr>
            </thead>
            <tbody>
                ${patchRows || `<tr><td colspan="5">No patch results.</td></tr>`}
            </tbody>
        </table>
    `;
}

function renderEvaluationB(data) {
    const r = data.result || data;
    const corrected = r.corrected_vs_original || {};
    const patch = r.sleecpatch_vs_original || {};
    const sim = r.similarities || {};

    const metrics = [
        "rules_edited",
        "rules_added",
        "rules_deleted",
        "constraints_added",
        "constraints_removed",
        "defeaters_added",
        "defeaters_removed",
        "actions_changed"
    ];

    const rows = metrics.map(m => `
        <tr>
            <td>${m}</td>
            <td>${corrected[m] ?? 0}</td>
            <td>${patch[m] ?? 0}</td>
            <td>${pct(sim[m])}</td>
        </tr>
    `).join("");

    document.getElementById("evaluationBOutput").innerHTML = `
        <div class="eval-cards">
            <div class="eval-card"><b>Use Case</b><span>${escapeHtml(r.use_case)}</span></div>
            <div class="eval-card"><b>Overall Similarity</b><span>${pct(r.overall_similarity)}</span></div>
            <div class="eval-card"><b>Corrected Edits</b><span>${corrected.rules_edited ?? 0}</span></div>
            <div class="eval-card"><b>SLEECPATCH Edits</b><span>${patch.rules_edited ?? 0}</span></div>
        </div>

        <table class="eval-table">
            <thead>
                <tr>
                    <th>Metric</th>
                    <th>Original → Corrected</th>
                    <th>Original → SLEECPATCH</th>
                    <th>Similarity</th>
                </tr>
            </thead>
            <tbody>${rows}</tbody>
        </table>
    `;
}

function renderEvaluationC(data) {
    const patches = data.patches || [];

    const rows = patches.map((p, index) => `
        <tr>
            <td>${escapeHtml(p.issue_id)}</td>
            <td>${escapeHtml(p.patch_id)}</td>
            <td>${escapeHtml(p.operation)}</td>
            <td class="small-cell">${escapeHtml(p.proposed_rule || "")}</td>
            <td>
                <button class="success" onclick="submitPhilosopherReviewByIndex(${index}, 'accept')">Accept</button>
                <button class="danger" onclick="submitPhilosopherReviewByIndex(${index}, 'reject')">Reject</button>
            </td>
        </tr>
    `).join("");

    window.semanticPatchesForReview = patches;

    document.getElementById("evaluationCOutput").innerHTML = `
        <div class="eval-cards">
            <div class="eval-card"><b>Semantic Patches</b><span>${patches.length}</span></div>
        </div>

        <table class="eval-table">
            <thead>
                <tr>
                    <th>Issue</th>
                    <th>Patch</th>
                    <th>Operation</th>
                    <th>Proposed Rule</th>
                    <th>Decision</th>
                </tr>
            </thead>
            <tbody>
                ${rows || `<tr><td colspan="5">No semantic patches found.</td></tr>`}
            </tbody>
        </table>
    `;
}

async function submitPhilosopherReviewByIndex(index, decision) {
    const patch = window.semanticPatchesForReview[index];
    const comment = prompt("Optional comment:");

    await postJSON("/api/sleec-patch/philosopher-review", {
        ...patch,
        reviewer: "Philosopher",
        decision: decision,
        comment: comment || ""
    });

    alert("Review saved.");
}

async function exportEvaluationExcel() {
    const useCase = document.getElementById("useCase").value;

    const data = await postJSON("/api/sleec-patch/export-evaluation", {
        use_case: useCase
    });

    alert("Excel exported: " + data.excel_path);
}

async function submitPhilosopherReview(patch, decision) {
    const comment = prompt("Optional comment:");

    await postJSON("/api/sleec-patch/philosopher-review", {
        ...patch,
        reviewer: "Philosopher",
        decision: decision,
        comment: comment || ""
    });

    alert("Review saved.");
}