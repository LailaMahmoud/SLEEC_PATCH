let sleecPatchState = {
    userProfession: "",
    sleecText: "",
    issues: [],
    selectedIssue: null,
    verifiedPatches: [],
    deterministicCandidates: [],
    llmCandidates: [],
    failedPatches: [],
    issueResults: {},
    selectedPatchIndex: null,
    comparisonPatchIndexes: [],
    approvedPatchIndex: null,
    patchDecisions: {},
    log: null,
    rawDiagnosis: null,
    manualVerification: null,
    resolutionChoice: null
};

let patchWizard = null;
// Any input, case or issue change invalidates outstanding UI requests.
let workbenchVersion = 0;


function escapeHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function escapeCodeHtml(value) {
    return String(value || "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;");
}

function patchDisplayLabel(patch) {
    return patch.operation_label || patch.operation || "Patch";
}

function issueTypeLabel(value) {
    const labels = {
        conflicts: "Conflict",
        situational_conflicts: "Situational Conflict",
        concerns: "Concern",
        purpose_blocking: "Insufficiency",
        redundancies: "Redundancy",
        conflict: "Conflict",
        concern: "Concern",
        purpose: "Insufficiency",
        redundancy: "Redundancy"
    };

    return labels[value] || String(value || "Issue").replaceAll("_", " ");
}

function orderedIssues(issues) {
    const order = [
        "conflicts",
        "situational_conflicts",
        "concerns",
        "purpose_blocking",
        "redundancies"
    ];

    return [...(issues || [])].sort((a, b) => {
        const ai = order.indexOf(a.issue_type);
        const bi = order.indexOf(b.issue_type);
        return (ai < 0 ? 99 : ai) - (bi < 0 ? 99 : bi);
    });
}

function issueProgressText() {
    if (!sleecPatchState.issues.length) return "No issues";
    const index = sleecPatchState.issues.findIndex(
        issue => issueKey(issue) === currentIssueKey()
    );
    return `Issue ${Math.max(index, 0) + 1} of ${sleecPatchState.issues.length}`;
}

function selectedIssueIndex() {
    return sleecPatchState.issues.findIndex(
        issue => issueKey(issue) === currentIssueKey()
    );
}

function renderHighlightedCode(value) {
    return `<pre class="sleec-highlighted-code">${highlightSleecCode(value || "")}</pre>`;
}

function rankingBand(score) {
    const numeric = Number(score) || 0;
    if (numeric >= 85) return "strong";
    if (numeric >= 70) return "moderate";
    return "weak";
}

function scoreBadge(label, value) {
    const band = rankingBand(value);
    return `
        <div class="score-chip ${band}">
            <dt>${escapeHtml(label)}</dt>
            <dd>${escapeHtml(value || 0)}</dd>
        </div>
    `;
}

function renderInlineBadges(items, className = "neutral") {
    const values = Array.isArray(items) ? items.filter(Boolean) : [];

    if (!values.length) return "";

    return `
        <div class="review-flags">
            ${values.map(item => `<span class="badge ${className}">${escapeHtml(item)}</span>`).join("")}
        </div>
    `;
}

function renderRationaleList(items) {
    const values = Array.isArray(items) ? items.filter(Boolean) : [];

    if (!values.length) return "";

    return `
        <div class="rationale-list">
            <strong>Why this rank?</strong>
            <ul>
                ${values.map(item => `<li>${escapeHtml(item)}</li>`).join("")}
            </ul>
        </div>
    `;
}

function renderRegressionReport(report) {
    if (!report) return "";

    const passed = Boolean(report.regression_passed);
    const fixed = Boolean(report.selected_issue_fixed);

    return `
        <div class="regression-report ${passed ? "passed" : "failed"}">
            <div class="regression-report-top">
                <strong>Regression Verification</strong>
                <span class="badge ${passed ? "good" : "bad"}">
                    ${passed ? "Passed" : "Needs review"}
                </span>
            </div>
            <dl class="score-list regression-score-list">
                <div><dt>Selected WFI</dt><dd>${fixed ? "Fixed" : "Still present"}</dd></div>
                <div><dt>New WFIs</dt><dd>${escapeHtml(report.new_issue_count || 0)}</dd></div>
                <div><dt>Resolved</dt><dd>${escapeHtml(report.resolved_issue_count || 0)}</dd></div>
                <div><dt>Remaining</dt><dd>${escapeHtml(report.remaining_issue_count || 0)}</dd></div>
                <div><dt>Total After</dt><dd>${escapeHtml(report.after_issue_count || 0)}</dd></div>
            </dl>
            ${
                report.new_issues && report.new_issues.length
                    ? `<div class="regression-new-issues">
                        <strong>New issues introduced</strong>
                        <ul>
                            ${report.new_issues.slice(0, 3).map(issue => `
                                <li>
                                    <span>${escapeHtml(issue.issue_type || "issue")}</span>
                                    ${escapeHtml(issue.summary || "")}
                                </li>
                            `).join("")}
                        </ul>
                    </div>`
                    : ""
            }
        </div>
    `;
}

function escapeRegExp(value) {
    return String(value).replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function extractHighlightTerms(text) {
    const terms = [];
    const lines = String(text || "").split("\n");

    lines.forEach(line => {
        const match = line.match(/^\s*(.+?)\s*:\s*\[\d+\s*,\s*\d+\]\s*$/);

        if (match) {
            const term = match[1].trim();
            if (term && !terms.includes(term)) terms.push(term);
        }
    });

    return terms;
}

function highlightTraceTerms(text, terms) {
    let html = escapeHtml(text);
    const sortedTerms = [...terms]
        .filter(Boolean)
        .sort((a, b) => b.length - a.length);

    sortedTerms.forEach(term => {
        const escapedTerm = escapeHtml(term);
        const pattern = new RegExp(escapeRegExp(escapedTerm), "g");
        html = html.replace(
            pattern,
            `<span class="trace-highlight-token">${escapedTerm}</span>`
        );
    });

    return html;
}

function traceBlockTitle(line, currentTitle) {
    const trimmed = line.trim();

    if (/^Situational conflict under situation/i.test(trimmed)) return "Conflict Situation";
    if (/^For rule:/i.test(trimmed)) return "Rule Being Checked";
    if (/^Because of the following SLEEC rule:/i.test(trimmed)) return "Conflicting SLEEC Rule";
    if (/^TO BE HIGHLIGHTED/i.test(trimmed)) return "Highlighted Terms";
    if (/^UNSAT CORE/i.test(trimmed)) return "Unsat Core";
    if (/^detect conflict|^Conflict detected|^find trace|^vol:/i.test(trimmed)) return "Conflict Reasoning";
    if (/^checking when|^solving under config|^domain size|^unsat$/i.test(trimmed)) return "Solver Log";
    if (/^when\s+/i.test(trimmed)) return "Expanded Formal Rules";

    return currentTitle;
}

function formatDiagnosisTrace(value, options = {}) {
    const text = String(value || "").replace(/-{10,}/g, "").replace(/\*{10,}/g, "");
    const maxBlocks = options.maxBlocks || null;
    const maxChars = options.maxChars || null;
    const highlightTerms = extractHighlightTerms(text);
    const blocks = [];
    let currentTitle = "Diagnosis Trace";
    let currentLines = [];

    function pushBlock() {
        const content = currentLines.join("\n").trim();
        if (!content) return;

        blocks.push({
            title: currentTitle,
            content
        });
        currentLines = [];
    }

    text.split("\n").forEach(line => {
        const trimmed = line.trim();

        if (/^\s*(.+?)\s*:\s*\[\d+\s*,\s*\d+\]\s*$/.test(line)) return;
        if (!trimmed && !currentLines.length) return;

        const nextTitle = traceBlockTitle(line, currentTitle);
        const isHeaderOnly = [
            "Situational conflict under situation",
            "For rule:",
            "Because of the following SLEEC rule:",
            "TO BE HIGHLIGHTED",
            "UNSAT CORE"
        ].some(prefix => trimmed.toLowerCase().startsWith(prefix.toLowerCase()));

        if (nextTitle !== currentTitle) {
            pushBlock();
            currentTitle = nextTitle;
        }

        if (!isHeaderOnly) currentLines.push(line);
    });

    pushBlock();

    let visibleBlocks = maxBlocks ? blocks.slice(0, maxBlocks) : blocks;
    let truncated = maxBlocks && blocks.length > maxBlocks;

    if (maxChars) {
        let remaining = maxChars;
        visibleBlocks = visibleBlocks.map(block => {
            if (remaining <= 0) {
                truncated = true;
                return null;
            }

            if (block.content.length > remaining) {
                truncated = true;
                const content = block.content.slice(0, remaining).trimEnd() + "\n...";
                remaining = 0;
                return {...block, content};
            }

            remaining -= block.content.length;
            return block;
        }).filter(Boolean);
    }

    const highlightHtml = highlightTerms.length
        ? `
            <section class="trace-block trace-highlight-list">
                <h4>Highlighted Terms</h4>
                <div>
                    ${highlightTerms.map(term => `<span class="trace-highlight-pill">${escapeHtml(term)}</span>`).join("")}
                </div>
            </section>
        `
        : "";

    const blockHtml = visibleBlocks.map(block => `
        <section class="trace-block">
            <h4>${escapeHtml(block.title)}</h4>
            <pre>${highlightTraceTerms(block.content, highlightTerms)}</pre>
        </section>
    `).join("");

    const truncatedHtml = truncated
        ? `<p class="trace-truncated">Output shortened here. Select the issue to view the full structured trace.</p>`
        : "";

    return `
        <div class="trace-blocks">
            ${highlightHtml}
            ${blockHtml}
            ${truncatedHtml}
        </div>
    `;
}

function highlightSleecCode(value) {
    return escapeCodeHtml(value)
        .replace(/(^|\s)(def|rule|when|then|unless|if|and|or|not|must|may|shall)\b/g, '$1<span class="sleec-kw">$2</span>')
        .replace(/(^|\s)(conflict|concern|purpose|capability|event|measure|defeater)\b/g, '$1<span class="sleec-kw-strong">$2</span>')
        .replace(/\b(r\d+|rule[_-]?\d+)\b/gi, '<span class="sleec-rule-id">$1</span>')
        .replace(/(#.*)$/gm, '<span class="sleec-comment">$1</span>');
}

function updateSleecEditorHighlight() {
    const input = document.getElementById("sleecInput");
    const highlight = document.getElementById("sleecInputHighlight");

    if (!input || !highlight) return;

    highlight.innerHTML = highlightSleecCode(input.value) + "\n";
    syncSleecEditorScroll();
}

function syncSleecEditorScroll() {
    const input = document.getElementById("sleecInput");
    const highlight = document.getElementById("sleecInputHighlight");

    if (!input || !highlight) return;

    highlight.scrollTop = input.scrollTop;
    highlight.scrollLeft = input.scrollLeft;
}

function updatePatchEditorHighlight() {
    const input = document.getElementById("stakeholderProposedRule");
    const highlight = document.getElementById("stakeholderProposedRuleHighlight");

    if (!input || !highlight) return;

    highlight.innerHTML = highlightSleecCode(input.value) + "\n";
    syncPatchEditorScroll();
}

function syncPatchEditorScroll() {
    const input = document.getElementById("stakeholderProposedRule");
    const highlight = document.getElementById("stakeholderProposedRuleHighlight");

    if (!input || !highlight) return;

    highlight.scrollTop = input.scrollTop;
    highlight.scrollLeft = input.scrollLeft;
}

async function postJSON(url, data) {
    const loaderText = loaderTextForUrl(url);

    return window.withLoader(async () => {
        const response = await fetch(url, {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify(data)
        });

        // Read the raw body first so a non-JSON error page (e.g. a 500 HTML
        // page from the server) does not blow up as an uncaught JSON.parse
        // SyntaxError that silently aborts the caller.
        const raw = await response.text();
        let result = null;
        try {
            result = raw ? JSON.parse(raw) : null;
        } catch (parseError) {
            result = null;
        }

        if (!response.ok || result === null) {
            const message = (result && result.error)
                || `Request failed (HTTP ${response.status}). `
                   + `The server returned ${result === null ? "a non-JSON error page" : "an error"}.`;
            alert(message);
            throw new Error(message);
        }

        return result;
    }, loaderText);
}

function loaderTextForUrl(url) {
    if (url.includes("diagnose")) return "Diagnosing well-formedness issues...";
    if (url.includes("generate-verified")) return "Generating and verifying candidate repairs...";
    if (url.includes("evaluation")) return "Loading evaluation results...";
    if (url.includes("load-usecase")) return "Loading SLEEC use case...";
    if (url.includes("philosopher")) return "Saving review...";
    if (url.includes("verify-edited-sleec")) return "Verifying the selected issue and checking for new issues...";
    return "Working...";
}

function refreshPatchWizard() {
    if (patchWizard) patchWizard.refresh();
    updateWorkflowHeader();
}

function goToPatchStep(step) {
    if (patchWizard) patchWizard.goToStep(step);
    updateWorkflowHeader(step);
}

const WIZARD_STEP_LABELS = [
    "Profession",
    "Instructions",
    "Use case",
    "Diagnosis",
    "Resolution",
    "Candidates",
    "Patches",
    "Edit patch",
    "Verify and next",
    "Evaluation"
];

function updateWorkflowHeader(step) {
    const activeStep = step || patchWizard?.getCurrentStep?.() || 1;
    const total = WIZARD_STEP_LABELS.length;
    const profession = (document.getElementById("userProfession")?.value || "").trim();
    const useCase = document.getElementById("useCase")?.value || "";
    const hasIssue = Boolean(sleecPatchState.selectedIssue);

    const stepCount = document.getElementById("trailStepCount");
    const stepLabel = document.getElementById("trailStepLabel");
    const meterFill = document.getElementById("trailMeterFill");
    if (stepCount) stepCount.textContent = `Step ${activeStep} of ${total}`;
    if (stepLabel) stepLabel.textContent = WIZARD_STEP_LABELS[activeStep - 1] || "";
    if (meterFill) meterFill.style.width = `${(activeStep / total) * 100}%`;

    const context = document.getElementById("trailContext");
    if (!context) return;

    // Only show what the user has actually provided; each item jumps back to the step that set it.
    const items = [
        { key: "Profession", value: profession, step: 1 },
        { key: "Use case", value: useCase, step: 3 },
        { key: "Issue", value: hasIssue ? issueProgressText().replace(/^Issue /, "") : "", step: 4 }
    ].filter(item => item.value);

    context.replaceChildren();

    if (!items.length) {
        const hint = document.createElement("li");
        hint.className = "trail-hint";
        hint.textContent = "Your selections will appear here as you go.";
        context.append(hint);
        return;
    }

    items.forEach(item => {
        const li = document.createElement("li");
        li.className = "trail-item";
        const isCurrent = item.step === activeStep;
        const node = document.createElement(isCurrent ? "span" : "button");
        node.className = `trail-chip${isCurrent ? " is-current" : ""}`;
        node.title = isCurrent ? item.value : `${item.value} (click to change)`;
        if (!isCurrent) {
            node.type = "button";
            node.addEventListener("click", () => goToPatchStep(item.step));
        }

        const key = document.createElement("span");
        key.className = "trail-key";
        key.textContent = item.key;
        const value = document.createElement("span");
        value.className = "trail-value";
        value.textContent = item.value;

        node.append(key, value);
        li.append(node);
        context.append(li);
    });
}

function saveUserProfession() {
    const input = document.getElementById("userProfession");
    sleecPatchState.userProfession = (input?.value || "").trim();
    storeProfession(sleecPatchState.userProfession);
    refreshPatchWizard();
}

// Shared with the SLEEC Expert Review page, which shows it next to its heading.
function storeProfession(value) {
    try {
        if (value) sessionStorage.setItem("sleecPatchProfession", value);
        else sessionStorage.removeItem("sleecPatchProfession");
    } catch (error) {
        // Storage can be unavailable (private mode); the workbench works without it.
    }
}

function continueFromProfession() {
    saveUserProfession();

    if (!sleecPatchState.userProfession) {
        alert("Please describe your profession or area of expertise before continuing.");
        return;
    }

    goToPatchStep(2);
}

function hasGeneratedPatches() {
    return Boolean(
        sleecPatchState.log ||
        sleecPatchState.verifiedPatches.length ||
        sleecPatchState.deterministicCandidates.length ||
        sleecPatchState.llmCandidates.length
    );
}

function hasVerifiedCurrentResolution() {
    const saved = currentIssueResult();
    return resolutionChoiceVerified(saved);
}

function issueKey(issue) {
    if (!issue) return "";
    return issue.id || `${issue.issue_type}:${String(issue.value || "").slice(0, 120)}`;
}

function currentIssueKey() {
    return issueKey(sleecPatchState.selectedIssue);
}

function currentIssueResult() {
    return sleecPatchState.issueResults[currentIssueKey()] || null;
}

function hasAttemptedIssueResult(result) {
    if (!result) return false;

    return Boolean(
        result.log ||
        (result.verifiedPatches || []).length ||
        (result.deterministicCandidates || []).length ||
        (result.llmCandidates || []).length ||
        result.manualVerification
    );
}

function patchIsVerified(patch) {
    if (!patch) return false;
    if (patch.stakeholder_edited) {
        return patch.edit_verified === true
            && patch.edit_verification?.valid === true
            && patch.edit_verification?.verified_text === patch.patched_sleec;
    }
    return patch.verified === true && patch.formally_verified === true;
}

function currentPatchReport(patch) {
    return patch.stakeholder_edited ? patch.edit_verification?.regression_report : patch.regression_report;
}

function resolutionChoiceVerified(result) {
    const choice = result?.resolutionChoice;
    if (!choice) return false;
    if (choice.kind === "manual") {
        return result.manualVerification?.valid === true
            && result.manualVerification.verified_text === choice.sleecText;
    }
    if (choice.kind === "patch") {
        const patch = result.verifiedPatches?.[choice.patchIndex];
        return patchIsVerified(patch) && patch.patched_sleec === choice.sleecText;
    }
    return false;
}

function resetCurrentRunState() {
    sleecPatchState.verifiedPatches = [];
    sleecPatchState.deterministicCandidates = [];
    sleecPatchState.llmCandidates = [];
    sleecPatchState.failedPatches = [];
    sleecPatchState.selectedPatchIndex = null;
    sleecPatchState.comparisonPatchIndexes = [];
    sleecPatchState.approvedPatchIndex = null;
    sleecPatchState.patchDecisions = {};
    sleecPatchState.log = null;
    sleecPatchState.manualVerification = null;
    sleecPatchState.resolutionChoice = null;
}

function captureCurrentRunState(data = null) {
    return {
        deterministicCandidates: sleecPatchState.deterministicCandidates,
        llmCandidates: sleecPatchState.llmCandidates,
        verifiedPatches: sleecPatchState.verifiedPatches,
        failedPatches: sleecPatchState.failedPatches,
        selectedPatchIndex: sleecPatchState.selectedPatchIndex,
        comparisonPatchIndexes: sleecPatchState.comparisonPatchIndexes,
        patchDecisions: sleecPatchState.patchDecisions,
        approvedPatchIndex: sleecPatchState.approvedPatchIndex,
        log: sleecPatchState.log,
        manualVerification: sleecPatchState.manualVerification,
        resolutionChoice: sleecPatchState.resolutionChoice,
        raw: data
    };
}

function persistCurrentIssueUiState() {
    const key = currentIssueKey();
    if (!key || !sleecPatchState.issueResults[key]) return;
    sleecPatchState.issueResults[key] = captureCurrentRunState(
        sleecPatchState.issueResults[key].raw || null
    );
}

function restoreIssueResult(result) {
    if (!result) {
        resetCurrentRunState();
        renderIssueRunOutput();
        document.getElementById("deterministicOutput").innerHTML = "No deterministic repairs yet.";
        document.getElementById("llmOutput").innerHTML = "No GPT semantic repairs yet.";
        document.getElementById("patchOutput").innerHTML = "No verified patches yet.";
        document.getElementById("stakeholderDecisionOutput").innerHTML = "Run the pipeline for this issue.";
        document.getElementById("verificationSummaryOutput").innerHTML = "No verified resolution selected yet.";
        document.getElementById("logOutput").innerHTML = "No log yet.";
        return;
    }

    sleecPatchState.deterministicCandidates = result.deterministicCandidates || [];
    sleecPatchState.llmCandidates = result.llmCandidates || [];
    sleecPatchState.verifiedPatches = result.verifiedPatches || [];
    sleecPatchState.failedPatches = result.failedPatches || [];
    sleecPatchState.selectedPatchIndex = result.selectedPatchIndex ?? (
        sleecPatchState.verifiedPatches.length ? 0 : null
    );
    sleecPatchState.comparisonPatchIndexes = result.comparisonPatchIndexes || [];
    sleecPatchState.patchDecisions = result.patchDecisions || {};
    sleecPatchState.approvedPatchIndex = result.approvedPatchIndex ?? null;
    sleecPatchState.log = result.log || null;
    sleecPatchState.manualVerification = result.manualVerification || null;
    sleecPatchState.resolutionChoice = result.resolutionChoice || null;

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
    renderStakeholderDecision();
    renderLog();
    renderIssueRunOutput();
    renderVerificationSummary();
}

function issueRunStatus(issue) {
    const result = sleecPatchState.issueResults[issueKey(issue)];
    if (!result) return "not run";
    if (resolutionChoiceVerified(result)) return "resolved";
    if (hasAttemptedIssueResult(result)) return "attempted";
    return "attempted";
}

function issueStatusBadgeClass(status) {
    if (status === "resolved") return "good";
    if (status === "attempted") return "neutral";
    return "bad";
}

function renderIssueSidebars() {
    const sidebarIds = [
        "issueSidebarStep3",
        "issueSidebarStep4",
        "issueSidebarStep5"
    ];
    const countIds = [
        "issueSidebarCountStep3",
        "issueSidebarCountStep4",
        "issueSidebarCountStep5"
    ];

    const selectedKey = currentIssueKey();
    const total = sleecPatchState.issues.length;
    const resolved = sleecPatchState.issues.filter(
        issue => issueRunStatus(issue) === "resolved"
    ).length;
    const countText = total ? `${resolved}/${total}` : "0";

    countIds.forEach(id => {
        const count = document.getElementById(id);
        if (count) count.textContent = countText;
    });

    const html = total
        ? sleecPatchState.issues.map((issue, index) => {
            const status = issueRunStatus(issue);
            const isActive = issueKey(issue) === selectedKey;
            const title = issue.id || `Issue ${index + 1}`;

            return `
                <button type="button"
                        class="issue-sidebar-item ${isActive ? "is-active" : ""}"
                        onclick="selectIssue(${index})">
                    <span>
                        <strong>${escapeHtml(title)}</strong>
                        <small>${escapeHtml(issue.issue_type || "issue")}</small>
                    </span>
                    <span class="badge ${issueStatusBadgeClass(status)}">
                        ${escapeHtml(status)}
                    </span>
                </button>
            `;
        }).join("")
        : "No issues selected.";

    sidebarIds.forEach(id => {
        const sidebar = document.getElementById(id);
        if (!sidebar) return;

        sidebar.className = total
            ? "issue-sidebar-list"
            : "issue-sidebar-list empty";
        sidebar.innerHTML = html;
    });
}

function unresolvedIssueIndexAfter(currentIndex) {
    if (!sleecPatchState.issues.length) return -1;

    for (let offset = 1; offset <= sleecPatchState.issues.length; offset += 1) {
        const index = (currentIndex + offset) % sleecPatchState.issues.length;
        if (issueRunStatus(sleecPatchState.issues[index]) !== "resolved") {
            return index;
        }
    }

    return -1;
}

function selectNextUnresolvedIssue() {
    const currentIndex = sleecPatchState.issues.findIndex(
        issue => issueKey(issue) === currentIssueKey()
    );
    const nextIndex = unresolvedIssueIndexAfter(Math.max(currentIndex, 0));

    if (nextIndex < 0) {
        alert("All detected issues have a successful run.");
        return;
    }

    selectIssue(nextIndex);
}

function renderIssueRunOutput() {
    const out = document.getElementById("issueRunOutput");
    if (!out) return;

    const selected = sleecPatchState.selectedIssue;
    const total = sleecPatchState.issues.length;
    const resolved = sleecPatchState.issues.filter(issue => issueRunStatus(issue) === "resolved").length;
    const attempted = sleecPatchState.issues.filter(issue => issueRunStatus(issue) === "attempted").length;
    const selectedStatus = selected ? issueRunStatus(selected) : "none";
    const llmCount = sleecPatchState.llmCandidates.length;
    const deterministicCount = sleecPatchState.deterministicCandidates.length;
    const verifiedCount = sleecPatchState.verifiedPatches.length;
    const readyForNext = hasVerifiedCurrentResolution();

    out.innerHTML = `
        <div class="issue-run-strip">
            <div>
                <h3>Issue Run</h3>
                <p class="issue-run-title">
                    <strong>${escapeHtml(selected?.id || "No issue selected")}</strong>
                    ${selected ? `- ${escapeHtml(selected.issue_type || "")}` : ""}
                </p>
                <div class="issue-status-row">
                    <span class="badge neutral">Status: ${escapeHtml(selectedStatus)}</span>
                    <span class="badge good">Resolved: ${escapeHtml(resolved)} / ${escapeHtml(total)}</span>
                    <span class="badge neutral">Attempted: ${escapeHtml(attempted)}</span>
                    <span class="badge neutral">Deterministic: ${escapeHtml(deterministicCount)}</span>
                    <span class="badge neutral">LLM persisted: ${escapeHtml(llmCount)}</span>
                    <span class="badge neutral">Verified: ${escapeHtml(verifiedCount)}</span>
                </div>
            </div>
            <div class="issue-run-actions ${readyForNext ? "issue-run-actions-ready" : ""}">
                <button class="secondary small-btn" onclick="goToPatchStep(4)">Current Diagnosis</button>
                <button class="${readyForNext ? "next-issue-cta" : "primary small-btn"}"
                        onclick="${readyForNext ? "goToPatchStep(9)" : "goToPatchStep(7)"}">
                    ${readyForNext ? "Review Next-Issue Handoff" : "Choose Verified Patch"}
                </button>
                <button class="success small-btn" onclick="generateVerifiedPatches()">Run Again</button>
            </div>
        </div>
    `;
}

function canAdvancePatchWizard(step) {
    if (step === 1) return Boolean(sleecPatchState.userProfession || document.getElementById("userProfession")?.value.trim());
    if (step === 2) return true;
    if (step === 3) return Boolean(sleecPatchState.rawDiagnosis);
    if (step === 4) return Boolean(sleecPatchState.selectedIssue);
    if (step === 5) return hasGeneratedPatches() || hasVerifiedCurrentResolution();
    if (step === 6) return hasGeneratedPatches();
    if (step === 7) return sleecPatchState.verifiedPatches.length > 0;
    if (step === 8) return hasVerifiedCurrentResolution();
    if (step === 9) return true;
    if (step === 10) return true;
    return false;
}

function resetPatchWorkbench(keepProfession = false) {
    workbenchVersion += 1;
    const profession = keepProfession ? sleecPatchState.userProfession : "";
    sleecPatchState = {
        userProfession: profession,
        sleecText: "",
        issues: [],
        selectedIssue: null,
        verifiedPatches: [],
        deterministicCandidates: [],
        llmCandidates: [],
        failedPatches: [],
        issueResults: {},
        selectedPatchIndex: null,
        comparisonPatchIndexes: [],
        approvedPatchIndex: null,
        patchDecisions: {},
        log: null,
        rawDiagnosis: null,
        manualVerification: null,
        resolutionChoice: null
    };

    document.getElementById("issuesOutput").innerHTML = "No diagnosis yet.";
    document.getElementById("selectedIssueOutput").innerHTML = "Select one issue.";
    const manualOutput = document.getElementById("manualResolutionOutput");
    if (manualOutput) manualOutput.innerHTML = "";
    document.getElementById("deterministicOutput").innerHTML = "No deterministic repairs yet.";
    document.getElementById("llmOutput").innerHTML = "No GPT semantic repairs yet.";
    document.getElementById("patchOutput").innerHTML = "No verified patches yet.";
    document.getElementById("stakeholderDecisionOutput").innerHTML = "Select a verified patch to review.";
    document.getElementById("verificationSummaryOutput").innerHTML = "No verified resolution selected yet.";
    document.getElementById("logOutput").innerHTML = "No log yet.";
    const issueRunOutput = document.getElementById("issueRunOutput");
    if (issueRunOutput) issueRunOutput.innerHTML = "No issue run loaded.";
    const professionInput = document.getElementById("userProfession");
    if (professionInput) professionInput.value = profession;
    storeProfession(profession);
    document.getElementById("summaryOutput").innerHTML = "No evaluation summary loaded.";
    document.getElementById("patchDetailOutput").innerHTML = `
        Click an operation in the evaluation tables to view the
        original rule, proposed rule, explanation, and verification details.
    `;
    document.getElementById("evaluationAOutput").innerHTML = "No Evaluation A results yet.";
    document.getElementById("evaluationBOutput").innerHTML = "No Evaluation B results yet.";
    document.getElementById("evaluationCOutput").innerHTML = "No philosopher review loaded.";
    window.latestDetailedResults = [];
    window.semanticPatchesForReview = [];
    renderIssueSidebars();

    if (!keepProfession) {
        document.getElementById("sleecInput").value = "";
        document.getElementById("useCase").value = "";
        updateSleecEditorHighlight();
        goToPatchStep(1);
    }
    refreshPatchWizard();
}

function onSpecificationInput() {
    const text = document.getElementById("sleecInput").value;
    if (text !== sleecPatchState.sleecText) {
        resetPatchWorkbench(true);
        sleecPatchState.sleecText = text;
    }
    updateSleecEditorHighlight();
}

async function diagnoseWFIs() {
    const sleecText = document.getElementById("sleecInput").value;

    if (!sleecText) {
        alert("Please enter SLEEC specification.");
        return;
    }

    resetPatchWorkbench(true);
    const version = workbenchVersion;
    const data = await postJSON("/api/sleec-patch/diagnose", {
        sleec_text: sleecText
    });

    if (version !== workbenchVersion) return;

    sleecPatchState.sleecText = sleecText;
    sleecPatchState.issues = orderedIssues(data.issues || []);
    sleecPatchState.rawDiagnosis = data;
    sleecPatchState.selectedIssue = sleecPatchState.issues[0] || null;
    sleecPatchState.verifiedPatches = [];
    sleecPatchState.deterministicCandidates = [];
    sleecPatchState.llmCandidates = [];
    sleecPatchState.failedPatches = [];
    sleecPatchState.issueResults = {};
    sleecPatchState.selectedPatchIndex = null;
    sleecPatchState.comparisonPatchIndexes = [];
    sleecPatchState.approvedPatchIndex = null;
    sleecPatchState.patchDecisions = {};
    sleecPatchState.log = null;
    sleecPatchState.manualVerification = null;

    renderIssues();
    renderIssueSidebars();
    if (sleecPatchState.selectedIssue) {
        renderSelectedIssue();
    } else {
        document.getElementById("selectedIssueOutput").innerHTML = "No issue selected.";
    }
    document.getElementById("deterministicOutput").innerHTML = "No deterministic repairs yet.";
    document.getElementById("llmOutput").innerHTML = "No GPT semantic repairs yet.";
    document.getElementById("patchOutput").innerHTML = "No verified patches yet.";
    document.getElementById("stakeholderDecisionOutput").innerHTML = "Select a verified patch to review.";
    document.getElementById("verificationSummaryOutput").innerHTML = "No verified resolution selected yet.";
    document.getElementById("logOutput").innerHTML = "No log yet.";
    const issueRunOutput = document.getElementById("issueRunOutput");
    if (issueRunOutput) issueRunOutput.innerHTML = "No issue run loaded.";
    refreshPatchWizard();
    goToPatchStep(4);
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

function refsToText(refs) {
    return (refs || [])
        .map(ref => {
            if (!ref) return "";

            const label = [ref.role, ref.id].filter(Boolean).join(": ");
            const text = ref.text || "";

            return label ? `${label}\n${text}` : text;
        })
        .filter(Boolean)
        .join("\n\n");
}

function renderIssues() {
    const out = document.getElementById("issuesOutput");

    if (!sleecPatchState.issues.length) {
        out.innerHTML = "<p>No WFIs detected.</p>";
        return;
    }

    const issue = sleecPatchState.selectedIssue || sleecPatchState.issues[0];
    const index = Math.max(0, selectedIssueIndex());
    const remaining = sleecPatchState.issues.length - index - 1;
    const status = issueRunStatus(issue);
    const artifactText = refsToText(issue.wfi_artifacts || []) || issue.diagnosis?.source_text || "";
    const directRuleText = refsToText(issue.diagnosis?.rule_references || issue.rule_references || []);
    const relatedRuleText = refsToText(issue.related_rules || []);
    const originalRuleText = (issue.original_rules || []).join("\n");

    out.innerHTML = `
        <div class="issue-card selected-issue first-issue-card">
            <div class="issue-header">
                <span class="issue-type">${escapeHtml(issueTypeLabel(issue.issue_type))}</span>
                <span class="issue-id">${escapeHtml(issueProgressText())}</span>
            </div>
            <div class="issue-status-row">
                <span class="badge ${status === "resolved" ? "good" : status === "attempted" ? "neutral" : "bad"}">
                    ${escapeHtml(status)}
                </span>
                <span class="badge neutral">${escapeHtml(remaining)} remaining after this</span>
            </div>

            <div class="issue-section">
                <strong>WFI Artifact(s)</strong>
                ${renderHighlightedCode(artifactText || "No concern/purpose artifact linked.")}
            </div>

            <div class="issue-section">
                <strong>Referenced Rule(s)</strong>
                ${renderHighlightedCode(directRuleText || originalRuleText || "No direct source rule linked.")}
            </div>

            <div class="issue-section">
                <strong>Related Rule(s)</strong>
                ${renderHighlightedCode(relatedRuleText || "No related rule inferred.")}
            </div>

            <div class="issue-section">
                <strong>Diagnosis Trace</strong>
                ${formatDiagnosisTrace(issue.diagnosis?.raw_report || issue.value, {
                    maxBlocks: 3,
                    maxChars: 650
                })}
            </div>

            <div class="center-actions">
                <button class="primary" onclick="goToPatchStep(5)">Resolve This Issue</button>
            </div>
        </div>
    `;
}

function renderSelectedIssue() {
    if (!sleecPatchState.selectedIssue) {
        document.getElementById("selectedIssueOutput").innerHTML = "No issue selected.";
        return;
    }

    const savedResult = currentIssueResult();
    const issue = sleecPatchState.selectedIssue;

    document.getElementById("selectedIssueOutput").innerHTML = `
        <div class="issue-card selected-issue">
            <div class="issue-header">
                <span class="issue-type">${escapeHtml(issueTypeLabel(issue.issue_type))}</span>
                <span class="issue-id">${escapeHtml(issueProgressText())}</span>
            </div>
            <div class="issue-status-row">
                <span class="badge ${savedResult ? "good" : "neutral"}">
                    ${savedResult ? "Resolution state loaded" : "Ready"}
                </span>
            </div>

            <p><strong>Selected WFI diagnosis trace</strong></p>
            ${formatDiagnosisTrace(issue.diagnosis?.raw_report || issue.value)}
        </div>
    `;
}

function selectIssue(index) {
    if (!sleecPatchState.issues[index]) return;
    workbenchVersion += 1;
    document.getElementById("manualResolutionOutput").innerHTML = "";
    sleecPatchState.selectedIssue = sleecPatchState.issues[index];
    const savedResult = currentIssueResult();

    renderSelectedIssue();
    restoreIssueResult(savedResult);
    renderIssues();
    renderIssueSidebars();
    refreshPatchWizard();
    goToPatchStep(
        !savedResult ? 5 : issueRunStatus(sleecPatchState.selectedIssue) === "resolved" ? 9 : 6
    );
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
    const manualOutput = document.getElementById("manualResolutionOutput");
    if (manualOutput) manualOutput.innerHTML = "";

    document.getElementById("logOutput").innerHTML = `
        <div class="metric-card">
            <h3>Verification running</h3>
            <p>Please wait. This may take several seconds.</p>
        </div>
    `;

    const version = ++workbenchVersion;
    const data = await postJSON(
        "/api/sleec-patch/generate-verified",
        {
            use_case: useCase,
            sleec_text: sleecPatchState.sleecText,
            issue: sleecPatchState.selectedIssue,
            max_attempts: 5
        }
    );

    if (version !== workbenchVersion) return;

    // save everything

    sleecPatchState.deterministicCandidates =
        data.deterministic_candidates || [];

    sleecPatchState.llmCandidates =
        data.llm_candidates || [];

    sleecPatchState.verifiedPatches =
        (data.verified_patches || []).filter(patchIsVerified);
    sleecPatchState.failedPatches =
    data.failed_patches || [];
    sleecPatchState.selectedPatchIndex =
        sleecPatchState.verifiedPatches.length ? 0 : null;
    sleecPatchState.comparisonPatchIndexes =
        sleecPatchState.verifiedPatches.slice(0, 2).map((_, index) => index);
    sleecPatchState.approvedPatchIndex = null;
    sleecPatchState.patchDecisions = {};
    sleecPatchState.resolutionChoice = null;

    sleecPatchState.log =
        data.log || {};

    sleecPatchState.issueResults[currentIssueKey()] = captureCurrentRunState(data);

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
    renderStakeholderDecision();

    renderLog();
    renderIssueRunOutput();
    renderVerificationSummary();
    renderIssues();
    renderIssueSidebars();
    refreshPatchWizard();
    goToPatchStep(6);
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

            <p><b>Patch ID:</b> ${escapeHtml(p.patch_id)}</p>

            <p><b>Repair:</b> ${escapeHtml(patchDisplayLabel(p))}</p>

            <p><b>Operation:</b> ${escapeHtml(p.operation)}</p>

            <p><b>Source:</b> ${escapeHtml(p.source)}</p>
            ${p.source_requirement_id ? `<p><b>Source concern:</b> ${escapeHtml(p.source_requirement_id)} — adds a rule.</p>` : ""}
            <p><b>Check result:</b> ${escapeHtml((p.candidate_status || "generated").replaceAll("_", " "))}</p>
            <p><b>Meaning review:</b> ${escapeHtml((p.semantic_review_status || "pending").replaceAll("_", " "))}</p>
            ${p.failure_reason ? `<p>${escapeHtml(p.failure_reason)}</p>` : ""}

            <p><b>Original Rule</b></p>

            <pre>${escapeHtml(p.original_rule || (p.source_requirement_id ? "Existing rules are preserved." : ""))}</pre>

            <p><b>Proposed Patch</b></p>

            <pre>${escapeHtml(p.proposed_rule || "")}</pre>

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
                ${sleecPatchState.log?.repair_notice ? `<p>${escapeHtml(sleecPatchState.log.repair_notice)}</p>` : ""}
                <button class="secondary" onclick="goToPatchStep(5)">Return to Issue Resolution</button>
            </div>
        `;
        renderStakeholderDecision();
        return;
    }

    let html = `
        <div class="score-legend" aria-label="Patch grade legend">
            <span><i class="legend-dot strong"></i>85-100 strong</span>
            <span><i class="legend-dot moderate"></i>70-84 moderate</span>
            <span><i class="legend-dot weak"></i>0-69 review carefully</span>
        </div>
    `;

sleecPatchState.verifiedPatches.forEach((p, index) => {

    const ranking = p.ranking || {};
    const isSelected = sleecPatchState.selectedPatchIndex === index;
    const rationale = p.ranking_rationale || ranking.rationale || [];
    const isLLM = (p.source || "").toLowerCase() === "llm";

    html += `
        <article class="patch-card selectable-patch ${isSelected ? "selected-patch" : ""}"
                 role="button"
                 tabindex="0"
                 onclick="selectPatchForReview(${index})"
                 onkeydown="if (event.key === 'Enter' || event.key === ' ') { event.preventDefault(); selectPatchForReview(${index}); }">

            <div class="patch-card-header">
                <div>
                    <h3>Rank #${escapeHtml(p.rank || "-")} - ${escapeHtml(patchDisplayLabel(p))}</h3>
                    <p><strong>${escapeHtml(p.patch_id)}</strong> - ${escapeHtml(p.operation)}</p>
                    <p><strong>Source:</strong> ${escapeHtml(p.source || "llm")}</p>
                </div>

                <span class="badge ${isLLM ? "neutral" : "good"}">
                    ${!patchIsVerified(p) ? "Edited · Requires verification" : p.semantic_review_status === "pending" || p.stakeholder_edited ? "Formally verified · Awaiting meaning review" : "Formally verified"}
                </span>
            </div>

            <p class="patch-summary">${escapeHtml(p.stakeholder_summary || "")}</p>
            ${renderInlineBadges(p.review_flags)}
            ${renderRegressionReport(currentPatchReport(p))}

            <dl class="score-list compact-score-list">
                ${scoreBadge("Overall", p.ranking_score || ranking.total_score || 0)}
                ${scoreBadge("Logical", ranking.logical_simplicity || 0)}
                ${scoreBadge("Semantic", ranking.semantic_clarity || 0)}
                ${scoreBadge("Interpretability", ranking.interpretability || 0)}
            </dl>

            ${renderRationaleList(rationale)}

            <div class="patch-actions">
                <span class="badge ${isSelected ? "good" : "neutral"}">
                    ${isSelected ? "Selected" : "Select patch"}
                </span>
            </div>

            <h4>Original Rule</h4>
            ${renderHighlightedCode(p.original_rule || "")}

            <h4>Proposed Patch</h4>
            ${renderHighlightedCode(p.proposed_rule || "")}

            <h4>Explanation</h4>
            <p class="patch-explanation">${escapeHtml(p.natural_language_explanation || "")}</p>
        </article>
    `;
});

    out.innerHTML = html;
}

function selectPatchForReview(index) {
    workbenchVersion += 1;
    sleecPatchState.selectedPatchIndex = index;
    sleecPatchState.approvedPatchIndex = index;

    if (!sleecPatchState.comparisonPatchIndexes.includes(index)) {
        sleecPatchState.comparisonPatchIndexes = [
            index,
            ...sleecPatchState.comparisonPatchIndexes
        ].slice(0, 3);
    }

    persistCurrentIssueUiState();
    renderVerifiedPatches();
    renderStakeholderDecision();
    goToPatchStep(8);
}

function toggleComparePatch(index, checked) {
    const current = sleecPatchState.comparisonPatchIndexes.filter(i => i !== index);

    if (checked) {
        current.push(index);
    }

    sleecPatchState.comparisonPatchIndexes = current.slice(0, 3);
    persistCurrentIssueUiState();
    renderVerifiedPatches();
    renderStakeholderDecision();
}

function approvePatch(index) {
    Object.keys(sleecPatchState.patchDecisions).forEach(key => {
        if (sleecPatchState.patchDecisions[key] === "approved") {
            sleecPatchState.patchDecisions[key] = "pending";
        }
    });

    sleecPatchState.patchDecisions[index] = "approved";
    sleecPatchState.approvedPatchIndex = index;
    sleecPatchState.selectedPatchIndex = index;

    renderVerifiedPatches();
    renderStakeholderDecision();
}

function rejectPatch(index) {
    sleecPatchState.patchDecisions[index] = "rejected";

    if (sleecPatchState.approvedPatchIndex === index) {
        sleecPatchState.approvedPatchIndex = null;
    }

    if (sleecPatchState.selectedPatchIndex === null) {
        sleecPatchState.selectedPatchIndex = index;
    }

    renderVerifiedPatches();
    renderStakeholderDecision();
}

function saveStakeholderEdit() {
    const index = sleecPatchState.selectedPatchIndex;
    const patch = sleecPatchState.verifiedPatches[index];
    if (!patch) return false;
    const previous = patch.proposed_rule || "";
    const proposed = document.getElementById("stakeholderProposedRule").value;
    patch.natural_language_explanation = document.getElementById("stakeholderExplanation").value;
    if (proposed === previous) return true;
    // The preview must contain one unambiguous edit target. This also avoids
    // claiming to edit an already deleted rule or silently checking old text.
    if (!previous || !patch.patched_sleec || patch.patched_sleec.split(previous).length !== 2) {
        alert("This patch cannot be edited here. Use Manual Resolution to edit its full specification.");
        return false;
    }
    patch.patched_sleec = patch.patched_sleec.replace(previous, () => proposed);
    patch.proposed_rule = proposed;
    patch.stakeholder_edited = true;
    patch.edit_verified = false;
    patch.edit_verification = null;
    sleecPatchState.resolutionChoice = null;
    persistCurrentIssueUiState();
    renderVerifiedPatches();
    renderStakeholderDecision();
    renderVerificationSummary();
    return true;
}

function onPatchEdit() {
    workbenchVersion += 1;
    const patch = sleecPatchState.verifiedPatches[sleecPatchState.selectedPatchIndex];
    if (patch) {
        patch.edit_verified = false;
        patch.edit_verification = null;
    }
    sleecPatchState.resolutionChoice = null;
    document.getElementById("patchVerificationOutput").textContent = "Unsaved edit. Save and verify before using this patch.";
    persistCurrentIssueUiState();
    updatePatchEditorHighlight();
    refreshPatchWizard();
}

function resetStakeholderEdit() {
    const index = sleecPatchState.selectedPatchIndex;
    const patch = sleecPatchState.verifiedPatches[index];

    if (!patch) return;

    document.getElementById("stakeholderProposedRule").value = patch.proposed_rule || "";
    document.getElementById("stakeholderExplanation").value = patch.natural_language_explanation || "";
    updatePatchEditorHighlight();
}

async function verifySleecTextForProceed(sleecText, outputId) {
    const version = ++workbenchVersion;
    const data = await postJSON("/api/sleec-patch/verify-edited-sleec", {
        original_sleec: sleecPatchState.sleecText,
        sleec_text: sleecText,
        issue: sleecPatchState.selectedIssue
    });
    if (version !== workbenchVersion) return null;
    const out = document.getElementById(outputId);
    if (out) {
        out.className = `verification-result ${data.valid ? "passed" : "failed"}`;
        out.innerHTML = data.valid
            ? `<span class="badge good">Formally verified</span><p>The selected issue is fixed and no new issues were detected. Meaning review is still required.</p>`
            : `<span class="badge bad">Not verified</span><p>${escapeHtml(data.failure_reason || data.error || "Verification failed.")}</p>`;
    }
    return {...data, verified_text: sleecText};
}

async function verifySelectedPatchEdit() {
    if (!saveStakeholderEdit()) return;
    const patch = sleecPatchState.verifiedPatches[sleecPatchState.selectedPatchIndex];
    if (!patch?.patched_sleec) return;
    const validation = await verifySleecTextForProceed(patch.patched_sleec, "patchVerificationOutput");
    if (!validation) return;
    patch.edit_verified = validation.valid === true;
    patch.edit_verification = validation;
    persistCurrentIssueUiState();
    renderVerificationSummary();
    refreshPatchWizard();
}

async function integrateSelectedPatchAndProceed() {
    const patch = sleecPatchState.verifiedPatches[sleecPatchState.selectedPatchIndex];

    if (!patch || !patch.patched_sleec) {
        alert("Select a patch with a generated SLEEC preview first.");
        return;
    }

    if (document.getElementById("stakeholderProposedRule").value !== (patch.proposed_rule || "") || !patchIsVerified(patch)) {
        alert("Save and verify the edited patch before using it.");
        return;
    }
    // Keep the experiment input unchanged for the next independent issue.
    // The chosen repair remains available in the handoff preview.

    sleecPatchState.approvedPatchIndex = sleecPatchState.selectedPatchIndex;
    sleecPatchState.patchDecisions[sleecPatchState.selectedPatchIndex] = "approved";
    sleecPatchState.resolutionChoice = {
        kind: "patch",
        patchIndex: sleecPatchState.selectedPatchIndex,
        patchId: patch.patch_id || "",
        operation: patch.operation || "",
        sleecText: patch.patched_sleec
    };
    sleecPatchState.issueResults[currentIssueKey()] = captureCurrentRunState();
    renderIssueRunOutput();
    renderIssues();
    renderIssueSidebars();
    renderVerificationSummary();
    refreshPatchWizard();
    goToPatchStep(9);
}

function showManualResolution() {
    if (!sleecPatchState.selectedIssue) {
        alert("Select one WFI first.");
        return;
    }

    const out = document.getElementById("manualResolutionOutput");
    if (!out) return;

    out.className = "manual-resolution";
    out.innerHTML = `
        <div class="manual-editor-shell">
            <label for="manualSleecEditor">Manual SLEEC Resolution</label>
            <div class="sleec-code-editor manual-editor">
                <pre id="manualSleecEditorHighlight" class="sleec-code-highlight" aria-hidden="true"></pre>
                <textarea id="manualSleecEditor"
                          spellcheck="false"
                          oninput="onManualEdit()"
                          onscroll="syncManualEditorScroll()">${escapeHtml(sleecPatchState.sleecText || document.getElementById("sleecInput").value || "")}</textarea>
            </div>
            <div id="manualVerificationOutput" class="verification-result empty">Edit the rules, then verify.</div>
            <div class="center-actions">
                <button class="secondary" onclick="verifyManualResolution()">Verify Manual Resolution</button>
                <button class="primary" onclick="integrateManualResolutionAndProceed()">Use Manual Resolution</button>
            </div>
        </div>
    `;

    const saved = sleecPatchState.manualVerification;
    if (saved?.verified_text) document.getElementById("manualSleecEditor").value = saved.verified_text;
    updateManualEditorHighlight();
}

function updateManualEditorHighlight() {
    const input = document.getElementById("manualSleecEditor");
    const highlight = document.getElementById("manualSleecEditorHighlight");

    if (!input || !highlight) return;

    highlight.innerHTML = highlightSleecCode(input.value) + "\n";
    syncManualEditorScroll();
}

function syncManualEditorScroll() {
    const input = document.getElementById("manualSleecEditor");
    const highlight = document.getElementById("manualSleecEditorHighlight");

    if (!input || !highlight) return;

    highlight.scrollTop = input.scrollTop;
    highlight.scrollLeft = input.scrollLeft;
}

async function verifyManualResolution() {
    const editor = document.getElementById("manualSleecEditor");
    if (!editor) return;

    const validation = await verifySleecTextForProceed(
        editor.value,
        "manualVerificationOutput"
    );

    if (!validation) return;
    sleecPatchState.manualVerification = validation;
    sleecPatchState.resolutionChoice = null;
    sleecPatchState.issueResults[currentIssueKey()] = captureCurrentRunState();
    renderVerificationSummary();
    refreshPatchWizard();
}

function onManualEdit() {
    workbenchVersion += 1;
    sleecPatchState.manualVerification = null;
    sleecPatchState.resolutionChoice = null;
    document.getElementById("manualVerificationOutput").textContent = "Edit changed. Verify again before using it.";
    persistCurrentIssueUiState();
    updateManualEditorHighlight();
    refreshPatchWizard();
}

function integrateManualResolutionAndProceed() {
    const editor = document.getElementById("manualSleecEditor");
    if (!editor) return;
    const verification = sleecPatchState.manualVerification;
    if (verification?.valid !== true || verification.verified_text !== editor.value) {
        alert("Please verify the current manual resolution before proceeding.");
        return;
    }
    sleecPatchState.resolutionChoice = {kind: "manual", sleecText: editor.value};
    sleecPatchState.issueResults[currentIssueKey()] = captureCurrentRunState();
    renderIssueRunOutput();
    renderIssues();
    renderVerificationSummary();
    refreshPatchWizard();
    goToPatchStep(9);
}

function proceedToNextSequentialIssue() {
    if (!hasVerifiedCurrentResolution()) {
        alert("Verify and integrate the current issue resolution before proceeding.");
        return;
    }

    const currentIndex = selectedIssueIndex();
    const nextIndex = currentIndex + 1;

    renderIssues();
    renderIssueSidebars();
    refreshPatchWizard();

    if (nextIndex >= sleecPatchState.issues.length) {
        goToPatchStep(10);
        return;
    }

    selectIssue(nextIndex);
    goToPatchStep(4);
}

function leaveIssueUnresolved() {
    // Moving on is not a successful repair and does not change stored results.
    const next = selectedIssueIndex() + 1;
    if (next >= sleecPatchState.issues.length) {
        goToPatchStep(10);
    } else {
        selectIssue(next);
        goToPatchStep(4);
    }
}

function renderVerificationSummary() {
    const out = document.getElementById("verificationSummaryOutput");
    if (!out) return;

    const choice = sleecPatchState.resolutionChoice;
    const selectedIssue = sleecPatchState.selectedIssue;
    const currentIndex = selectedIssueIndex();
    const isLastIssue = (
        currentIndex >= 0
        && currentIndex === sleecPatchState.issues.length - 1
    );

    if (!selectedIssue) {
        out.innerHTML = "No issue selected.";
        return;
    }

    if (!choice) {
        out.innerHTML = `
            <div class="verification-handoff-card">
                <div>
                    <span class="badge neutral">Waiting for resolution</span>
                    <h3>Finish one verified resolution before continuing</h3>
                    <p>Select a verified patch or complete a manual resolution, then come back here to move to the next issue.</p>
                </div>
                <div class="verification-handoff-actions">
                    <button class="primary" onclick="goToPatchStep(7)">Review Verified Patches</button>
                    <button class="secondary" onclick="goToPatchStep(5)">Back to Issue Resolution</button>
                </div>
            </div>
        `;
        return;
    }

    let verificationBadge = `<span class="badge neutral">Verification pending</span>`;
    let summaryTitle = "Resolved with selected patch";
    let summaryBody = "";
    let detailHtml = "";
    let canProceed = false;

    if (choice.kind === "patch") {
        const patch = sleecPatchState.verifiedPatches[choice.patchIndex];

        if (!patch) {
            out.innerHTML = `
                <div class="verification-handoff-card">
                    <span class="badge bad">Selected patch missing</span>
                    <p>Re-open the verified patch list and select a patch again.</p>
                </div>
            `;
            return;
        }

        const editWasRequired = Boolean(patch.stakeholder_edited);
        const editedVerification = patch.edit_verification;
        canProceed = hasVerifiedCurrentResolution();
        verificationBadge = canProceed
            ? `<span class="badge good">${editWasRequired ? "Edited patch verified" : "Generated patch verified"}</span>`
            : `<span class="badge bad">Edited patch not yet verified</span>`;
        summaryBody = `
            <p><strong>${escapeHtml(patch.patch_id || "Patch")}</strong> is selected for <strong>${escapeHtml(selectedIssue.id || "this issue")}</strong>.</p>
            <p>${escapeHtml(patch.stakeholder_summary || patch.natural_language_explanation || "")}</p>
        `;
        detailHtml = `
            <div class="verification-detail-grid">
                <div class="metric-card">
                    <h3>Chosen Patch</h3>
                    <p><strong>Operation:</strong> ${escapeHtml(patchDisplayLabel(patch))}</p>
                    <p><strong>Source:</strong> ${escapeHtml(patch.source || "llm")}</p>
                    <p><strong>Edited by user:</strong> ${editWasRequired ? "Yes" : "No"}</p>
                </div>
                <div class="metric-card">
                    <h3>Verification Result</h3>
                    <p><strong>Status:</strong> ${canProceed ? "Ready to continue" : "Needs re-verification"}</p>
                    <p><strong>Formal verification:</strong> ${patchIsVerified(patch) ? "Passed" : "Needs verification"}</p>
                    <p><strong>Edit re-check:</strong> ${editWasRequired ? (patch.edit_verified ? "Passed" : "Not passed yet") : "Not required"}</p>
                    ${editedVerification && !editedVerification.valid ? `<p><strong>Reason:</strong> ${escapeHtml(editedVerification.failure_reason || editedVerification.error || "")}</p>` : ""}
                </div>
            </div>
            ${renderRegressionReport(currentPatchReport(patch))}
        `;
    } else {
        summaryTitle = "Resolved with manual edit";
        canProceed = hasVerifiedCurrentResolution();
        verificationBadge = canProceed
            ? `<span class="badge good">Manual resolution verified</span>`
            : `<span class="badge bad">Manual resolution not verified</span>`;
        summaryBody = `
            <p><strong>${escapeHtml(selectedIssue.id || "This issue")}</strong> will use the manually edited SLEEC specification.</p>
            <p>The selected issue must be fixed, with valid syntax and no new issues, before continuing.</p>
        `;
        detailHtml = `
            <div class="verification-detail-grid">
                <div class="metric-card">
                    <h3>Resolution Type</h3>
                    <p><strong>Mode:</strong> Manual edit</p>
                    <p><strong>Saved for this issue:</strong> Yes</p>
                </div>
                <div class="metric-card">
                    <h3>Verification Result</h3>
                    <p><strong>Status:</strong> ${canProceed ? "Ready to continue" : "Needs verification"}</p>
                    <p><strong>Detector and syntax check:</strong> ${canProceed ? "Passed" : "Not passed yet"}</p>
                    ${
                        sleecPatchState.manualVerification && !sleecPatchState.manualVerification.valid
                            ? `<p><strong>Reason:</strong> ${escapeHtml(sleecPatchState.manualVerification.failure_reason || sleecPatchState.manualVerification.error || "")}</p>`
                            : ""
                    }
                </div>
            </div>
        `;
    }

    out.innerHTML = `
        <div class="verification-handoff-card ${canProceed ? "is-ready" : "is-blocked"}">
            <div class="verification-handoff-copy">
                ${verificationBadge}
                <h3>${escapeHtml(summaryTitle)}</h3>
                ${summaryBody}
                <p class="verification-progress-copy">
                    ${escapeHtml(issueProgressText())}
                    ${isLastIssue ? " is the final detected issue." : " is ready to hand off to the next issue."}
                </p>
            </div>
            <div class="verification-handoff-actions">
                <button class="${canProceed ? "next-issue-cta" : "secondary"}"
                        onclick="${canProceed ? "proceedToNextSequentialIssue()" : `goToPatchStep(${choice.kind === "patch" ? 8 : 5})`}">
                    ${canProceed ? (isLastIssue ? "Finish All Issues" : "Proceed to Next Issue") : "Finish Verification First"}
                </button>
                <button class="secondary" onclick="goToPatchStep(${choice.kind === "patch" ? 8 : 5})">
                    ${choice.kind === "patch" ? "Review Patch Edit" : "Review Manual Edit"}
                </button>
            </div>
        </div>
        ${detailHtml}
        <details><summary>Chosen resolution preview</summary>${renderHighlightedCode(choice.sleecText || "")}</details>
        <p>Each issue uses the original input. Human edits remain local previews and are not counted as automatically generated repairs.</p>
    `;
}

function applyApprovedPatchToEditor() {
    return integrateSelectedPatchAndProceed();
}

function renderStakeholderDecision() {
    const out = document.getElementById("stakeholderDecisionOutput");

    if (!out) return;

    if (!sleecPatchState.verifiedPatches.length) {
        const llmCount = sleecPatchState.llmCandidates.length;
        out.innerHTML = `
            <div class="metric-card">
                <h3>No Verified Patch Selected</h3>
                <p><strong>LLM candidates generated:</strong> ${escapeHtml(llmCount)}</p>
                <p><strong>Verified patches:</strong> 0</p>
                <p>Use manual resolution if no generated patch is suitable.</p>
            </div>
        `;
        return;
    }

    if (sleecPatchState.selectedPatchIndex === null) {
        sleecPatchState.selectedPatchIndex = 0;
    }

    const selectedPatch = sleecPatchState.verifiedPatches[sleecPatchState.selectedPatchIndex];
    const ranking = selectedPatch.ranking || {};

    out.innerHTML = `
        <div class="decision-editor single-decision-editor">
            <div>
                <h3>Selected Verified Patch</h3>
                <p>
                    <strong>${escapeHtml(selectedPatch.patch_id)}</strong>
                    - ${escapeHtml(patchDisplayLabel(selectedPatch))}
                    - Rank #${escapeHtml(selectedPatch.rank || "-")}
                </p>
                <p class="patch-summary">${escapeHtml(selectedPatch.stakeholder_summary || "")}</p>
                ${renderInlineBadges(selectedPatch.review_flags)}
                ${renderRegressionReport(currentPatchReport(selectedPatch))}
                ${renderRationaleList(
                    selectedPatch.ranking_rationale ||
                    (selectedPatch.ranking || {}).rationale ||
                    []
                )}
                <dl class="score-list compact-score-list">
                    ${scoreBadge("Overall", selectedPatch.ranking_score || ranking.total_score || 0)}
                    ${scoreBadge("Logical", ranking.logical_simplicity || 0)}
                    ${scoreBadge("Semantic", ranking.semantic_clarity || 0)}
                    ${scoreBadge("Interpretability", ranking.interpretability || 0)}
                </dl>
            </div>

            <div>
                <h3>Edit Patch</h3>
                <label for="stakeholderProposedRule">Proposed Rule</label>
                <div class="sleec-code-editor compact-editor">
                    <pre id="stakeholderProposedRuleHighlight" class="sleec-code-highlight" aria-hidden="true"></pre>
                    <textarea id="stakeholderProposedRule"
                              spellcheck="false"
                              oninput="onPatchEdit()"
                              onscroll="syncPatchEditorScroll()">${escapeHtml(selectedPatch.proposed_rule || "")}</textarea>
                </div>

                <label for="stakeholderExplanation">Explanation</label>
                <textarea id="stakeholderExplanation" class="plain-editor" spellcheck="true">${escapeHtml(selectedPatch.natural_language_explanation || "")}</textarea>

                <div id="patchVerificationOutput" class="verification-result empty">
                    ${selectedPatch.stakeholder_edited ? (patchIsVerified(selectedPatch) ? "Edited patch formally verified. Meaning review remains pending." : "Edited patch requires verification.") : "Generated patch formally verified. Re-verify after edits; meaning review remains separate."}
                </div>

                <div class="center-actions">
                    <button class="secondary" onclick="saveStakeholderEdit()">Save Edit</button>
                    <button class="secondary" onclick="verifySelectedPatchEdit()">Verify Edit</button>
                    <button class="primary" onclick="integrateSelectedPatchAndProceed()">Use Patch and Open Next-Issue Verification</button>
                </div>
            </div>
        </div>
    `;

    updatePatchEditorHighlight();
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
    resetPatchWorkbench(true);
    document.getElementById("sleecInput").value = "";
    updateSleecEditorHighlight();
    const version = workbenchVersion;
    let text = "";
    if (useCase === "Custom") {
        text = sessionStorage.getItem("sleecPatchCustomText") || "";
    } else if (useCase) {
        const data = await postJSON("/api/sleec-patch/load-usecase", {use_case: useCase});
        if (version !== workbenchVersion) return;
        text = data.sleec_text || "";
    }
    document.getElementById("sleecInput").value = text;
    sleecPatchState.sleecText = text;
    updateSleecEditorHighlight();
    refreshPatchWizard();
}

async function handleUseCaseSelection() {
    const select = document.getElementById("useCase");
    const details = document.getElementById("useCaseDetails");
    const description = document.getElementById("useCaseDescription");
    const useCase = select ? select.value : "";
    const descriptions = window.SLEEC_USE_CASE_DESCRIPTIONS || {};

    if (description) {
        description.textContent = descriptions[useCase] || "No detailed description is currently available.";
    }

    if (details) details.open = true;

    await loadSelectedUseCase();
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
            <td>${p.matched_corrected ? "Match" : "No match"}</td>
            <td>${escapeHtml(p.match_type || "-")}</td>
            <td>${Math.round((Number(p.match_confidence) || 0) * 100)}%</td>
            <td>${escapeHtml(p.match_reason || "")}</td>
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
                    <th>Type</th>
                    <th>Confidence</th>
                    <th>Reason</th>
                </tr>
            </thead>
            <tbody>
                ${patchRows || `<tr><td colspan="8">No patch results.</td></tr>`}
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
        reviewer: "SLEEC Expert",
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
        reviewer: "SLEEC Expert",
        decision: decision,
        comment: comment || ""
    });

    alert("Review saved.");
}

document.addEventListener("DOMContentLoaded", () => {
    const professionInput = document.getElementById("userProfession");
    let storedProfession = "";
    try {
        storedProfession = sessionStorage.getItem("sleecPatchProfession") || "";
    } catch (error) {
        storedProfession = "";
    }
    if (professionInput && storedProfession && !professionInput.value.trim()) {
        professionInput.value = storedProfession;
        sleecPatchState.userProfession = storedProfession;
    }

    const customText = sessionStorage.getItem("sleecPatchCustomText");
    const customUseCase = sessionStorage.getItem("sleecPatchCustomUseCase");
    const useCaseSelect = document.getElementById("useCase");
    const sleecInput = document.getElementById("sleecInput");

    if (customText && sleecInput) {
        if (useCaseSelect && customUseCase && !Array.from(useCaseSelect.options).some(option => option.value === customUseCase)) {
            const option = document.createElement("option");
            option.value = customUseCase;
            option.textContent = customUseCase;
            useCaseSelect.prepend(option);
            useCaseSelect.value = customUseCase;
        }

        sleecInput.value = customText;
        sleecPatchState.sleecText = customText;
    }

    updateSleecEditorHighlight();
    if (useCaseSelect && useCaseSelect.value) {
        const description = document.getElementById("useCaseDescription");
        const details = document.getElementById("useCaseDetails");
        const descriptions = window.SLEEC_USE_CASE_DESCRIPTIONS || {};
        if (description) description.textContent = descriptions[useCaseSelect.value] || "";
        if (details && description && description.textContent) details.open = true;
    }

    if (!window.SleecWizard) return;

    patchWizard = window.SleecWizard.init({
        root: document,
        total: 10,
        labels: WIZARD_STEP_LABELS,
        canAdvance: canAdvancePatchWizard,
        onStepChange: updateWorkflowHeader,
        onRestart: () => resetPatchWorkbench()
    });

    updateWorkflowHeader();
    if (!customText && useCaseSelect?.value) handleUseCaseSelection();
});
