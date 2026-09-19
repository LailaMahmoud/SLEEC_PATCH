let sleecPatchState = {
    userProfession: "",
    sleecText: "",
    originalSleecText: "",
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
        "purpose_blocking",
        "redundancies",
        "conflicts",
        "situational_conflicts",
        "concerns"
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
    if (url.includes("clear-persisted-data")) return "Clearing saved SLEEC-PATCH data...";
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

function updateWorkflowHeader(step) {
    const useCasePill = document.getElementById("headerUseCase");
    const issuePill = document.getElementById("headerIssueProgress");
    const useCase = document.getElementById("useCase")?.value || "";
    const activeStep = step || patchWizard?.getCurrentStep?.() || 1;

    if (useCasePill) {
        useCasePill.textContent = useCase || "No use case selected";
        useCasePill.classList.toggle("is-live", Boolean(useCase));
        useCasePill.classList.toggle("muted", !useCase);
    }

    if (issuePill) {
        const hasIssue = Boolean(sleecPatchState.selectedIssue);
        issuePill.textContent = hasIssue ? issueProgressText() : "No issue run";
        issuePill.classList.toggle("is-live", hasIssue && activeStep >= 4);
        issuePill.classList.toggle("muted", !hasIssue || activeStep < 4);
    }
}

function saveUserProfession() {
    const input = document.getElementById("userProfession");
    sleecPatchState.userProfession = (input?.value || "").trim();
    refreshPatchWizard();
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

function resolutionChoiceVerified(result) {
    if (!result || !result.resolutionChoice) return false;

    if (result.resolutionChoice.kind === "manual") {
        return Boolean(result.manualVerification && result.manualVerification.valid);
    }

    if (result.resolutionChoice.kind === "patch") {
        const patch = (result.verifiedPatches || [])[result.resolutionChoice.patchIndex];

        if (!patch) return false;
        if (patch.stakeholder_edited) return Boolean(patch.edit_verified);
        return Boolean(patch.verified || (result.log && result.log.successful));
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
    if (step === 3) return Boolean(sleecPatchState.sleecText || document.getElementById("sleecInput")?.value.trim());
    if (step === 4) return Boolean(sleecPatchState.selectedIssue);
    if (step === 5) return hasGeneratedPatches() || hasVerifiedCurrentResolution();
    if (step === 6) return hasGeneratedPatches();
    if (step === 7) {
        return (
            sleecPatchState.verifiedPatches.length > 0
            || (
                sleecPatchState.selectedIssue
                && issueRunStatus(sleecPatchState.selectedIssue) === "attempted"
                && sleecPatchState.verifiedPatches.length === 0
            )
        );
    }   
    if (step === 8) {
        return (
            hasVerifiedCurrentResolution()
            || (
                sleecPatchState.selectedIssue
                && issueRunStatus(sleecPatchState.selectedIssue) === "attempted"
                && sleecPatchState.verifiedPatches.length === 0
            )
        );
    }    
    if (step === 9) return true;
    if (step === 10) return true;
    return false;
}

function resetPatchWorkbench() {
    sleecPatchState = {
        userProfession: "",
        sleecText: "",
        originalSleecText: "",
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
    if (professionInput) professionInput.value = "";
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

    goToPatchStep(1);
    refreshPatchWizard();
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
    sleecPatchState.originalSleecText = sleecText;
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
    const artifactText = refsToText(issue.wfi_artifacts || []);
    const directRuleText = refsToText(issue.rule_references || []);
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
                ${formatDiagnosisTrace(shortIssueText(issue.value), {
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
            ${formatDiagnosisTrace(issue.value)}
        </div>
    `;
}

function selectIssue(index) {
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

    const data = await postJSON(
        "/api/sleec-patch/generate-verified",
        {
            use_case: useCase,
            sleec_text: sleecPatchState.originalSleecText,
            issue: sleecPatchState.selectedIssue,
            max_attempts: 1
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

            <p><b>Original Rule</b></p>

            <pre>${escapeHtml(p.original_rule || "")}</pre>

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
                    ${isLLM ? "Persisted for philosopher" : "Deterministic"}
                </span>
            </div>

            <p class="patch-summary">${escapeHtml(p.stakeholder_summary || "")}</p>
            ${renderInlineBadges(p.review_flags)}
            ${renderRegressionReport(p.regression_report)}

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

    if (!patch) return;

    const previousProposed = patch.proposed_rule || "";
    const proposed = document.getElementById("stakeholderProposedRule").value.trim();
    const explanation = document.getElementById("stakeholderExplanation").value.trim();

    if (!proposed) {
        alert("The proposed rule cannot be empty.");
        return;
    }

    patch.proposed_rule = proposed;
    patch.natural_language_explanation = explanation;
    patch.stakeholder_edited = true;

    if (patch.patched_sleec && previousProposed && patch.patched_sleec.includes(previousProposed)) {
        patch.patched_sleec = patch.patched_sleec.replace(previousProposed, proposed);
    } else if (patch.patched_sleec && patch.original_rule && patch.patched_sleec.includes(patch.original_rule)) {
        patch.patched_sleec = patch.patched_sleec.replace(patch.original_rule, proposed);
    }

    if (!sleecPatchState.patchDecisions[index]) {
        sleecPatchState.patchDecisions[index] = "edited";
    }
    patch.edit_verified = false;
    patch.edit_verification = null;
    sleecPatchState.resolutionChoice = null;

    persistCurrentIssueUiState();
    renderVerifiedPatches();
    renderStakeholderDecision();
    renderVerificationSummary();
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
    const data = await postJSON("/api/sleec-patch/verify-edited-sleec", {
        sleec_text: sleecText
    });

    const out = document.getElementById(outputId);
    if (out) {
        out.className = `verification-result ${data.valid ? "passed" : "failed"}`;
        out.innerHTML = data.valid
            ? `<span class="badge good">Verified</span><p>The edited specification passed SLEEC syntax and detector checks.</p>`
            : `<span class="badge bad">Not verified</span><p>${escapeHtml(data.failure_reason || data.error || "Verification failed.")}</p>`;
    }

    return data;
}

async function verifySelectedPatchEdit() {
    const index = sleecPatchState.selectedPatchIndex;
    const patch = sleecPatchState.verifiedPatches[index];

    if (!patch) return;

    saveStakeholderEdit();

    const editedPatch = sleecPatchState.verifiedPatches[index];
    const candidateSleec = editedPatch.patched_sleec || sleecPatchState.sleecText;
    const validation = await verifySleecTextForProceed(
        candidateSleec,
        "patchVerificationOutput"
    );

    editedPatch.edit_verified = Boolean(validation.valid);
    editedPatch.edit_verification = validation;
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

    if (patch.stakeholder_edited && !patch.edit_verified) {
        alert("Please verify the edited patch before integrating it.");
        return;
    }

    const input = document.getElementById("sleecInput");
    input.value = patch.patched_sleec;
    sleecPatchState.sleecText = patch.patched_sleec;
    updateSleecEditorHighlight();

    sleecPatchState.approvedPatchIndex = sleecPatchState.selectedPatchIndex;
    sleecPatchState.patchDecisions[sleecPatchState.selectedPatchIndex] = "approved";
    sleecPatchState.resolutionChoice = {
        kind: "patch",
        patchIndex: sleecPatchState.selectedPatchIndex,
        patchId: patch.patch_id || "",
        operation: patch.operation || ""
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
                          oninput="updateManualEditorHighlight()"
                          onscroll="syncManualEditorScroll()">${escapeHtml(sleecPatchState.sleecText || document.getElementById("sleecInput").value || "")}</textarea>
            </div>
            <div id="manualVerificationOutput" class="verification-result empty">Edit the rules, then verify.</div>
            <div class="center-actions">
                <button class="secondary" onclick="verifyManualResolution()">Verify Manual Resolution</button>
                <button class="primary" onclick="integrateManualResolutionAndProceed()">Use Manual Resolution</button>
            </div>
        </div>
    `;

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
        editor.value.trim(),
        "manualVerificationOutput"
    );

    sleecPatchState.manualVerification = validation;
    sleecPatchState.resolutionChoice = null;
    sleecPatchState.issueResults[currentIssueKey()] = captureCurrentRunState();
    renderVerificationSummary();
    refreshPatchWizard();
}

function integrateManualResolutionAndProceed() {
    const editor = document.getElementById("manualSleecEditor");
    if (!editor) return;

    if (!sleecPatchState.manualVerification || !sleecPatchState.manualVerification.valid) {
        alert("Please verify the manual resolution before proceeding.");
        return;
    }

    const input = document.getElementById("sleecInput");
    input.value = editor.value.trim();
    sleecPatchState.sleecText = input.value;
    updateSleecEditorHighlight();
    sleecPatchState.resolutionChoice = {
        kind: "manual"
    };
    sleecPatchState.issueResults[currentIssueKey()] = captureCurrentRunState();
    renderIssueRunOutput();
    renderIssues();
    renderIssueSidebars();
    renderVerificationSummary();
    refreshPatchWizard();
    goToPatchStep(9);
}

function proceedToNextSequentialIssue() {
    const selectedIssue = sleecPatchState.selectedIssue;

    const verifiedResolution = hasVerifiedCurrentResolution();

    const attemptedUnresolved = Boolean(
        selectedIssue
        && issueRunStatus(selectedIssue) === "attempted"
        && sleecPatchState.verifiedPatches.length === 0
    );

    if (!verifiedResolution && !attemptedUnresolved) {
        alert(
            "Run the current issue and complete verification before proceeding."
        );
        return;
    }

    // Preserve the current issue result before moving on.
    persistCurrentIssueUiState();

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
    const noVerifiedPatch = (
        sleecPatchState.verifiedPatches.length === 0
        && issueRunStatus(selectedIssue) === "attempted"
    );

    if (noVerifiedPatch) {
        out.innerHTML = `
            <div class="verification-handoff-card is-ready">
                <div class="verification-handoff-copy">
                    <span class="badge neutral">Attempted — unresolved</span>
                    <h3>No formally verified patch found</h3>
                    <p>
                        This issue was attempted, but no generated candidate
                        passed formal verification. It remains unresolved and
                        the evaluation can continue to the next issue.
                    </p>
                    <p class="verification-progress-copy">
                        ${escapeHtml(issueProgressText())}
                    </p>
                </div>

                <div class="verification-handoff-actions">
                    <button class="next-issue-cta"
                            onclick="proceedToNextSequentialIssue()">
                        ${isLastIssue ? "Finish All Issues" : "Proceed to Next Issue"}
                    </button>

                    <button class="secondary"
                            onclick="goToPatchStep(5)">
                        Back to Issue Resolution
                    </button>
                </div>
            </div>
        `;
        return;
    }

    out.innerHTML = `
        <div class="verification-handoff-card">
            <div>
                <span class="badge neutral">Waiting for resolution</span>
                <h3>Finish one verified resolution before continuing</h3>
                <p>
                    Select a verified patch or complete a manual resolution,
                    then come back here to move to the next issue.
                </p>
            </div>
            <div class="verification-handoff-actions">
                <button class="primary" onclick="goToPatchStep(7)">
                    Review Verified Patches
                </button>
                <button class="secondary" onclick="goToPatchStep(5)">
                    Back to Issue Resolution
                </button>
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
        canProceed = editWasRequired ? Boolean(patch.edit_verified) : true;
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
                    <p><strong>Formal verification:</strong> ${patch.verified ? "Passed" : "Failed"}</p>
                    <p><strong>Edit re-check:</strong> ${editWasRequired ? (patch.edit_verified ? "Passed" : "Not passed yet") : "Not required"}</p>
                    ${editedVerification && !editedVerification.valid ? `<p><strong>Reason:</strong> ${escapeHtml(editedVerification.failure_reason || editedVerification.error || "")}</p>` : ""}
                </div>
            </div>
            ${renderRegressionReport(patch.regression_report)}
        `;
    } else {
        summaryTitle = "Resolved with manual edit";
        canProceed = Boolean(
            sleecPatchState.manualVerification
            && sleecPatchState.manualVerification.valid
        );
        verificationBadge = canProceed
            ? `<span class="badge good">Manual resolution verified</span>`
            : `<span class="badge bad">Manual resolution not verified</span>`;
        summaryBody = `
            <p><strong>${escapeHtml(selectedIssue.id || "This issue")}</strong> will use the manually edited SLEEC specification.</p>
            <p>The detector and syntax checks must pass before you continue to the next issue.</p>
        `;
        detailHtml = `
            <div class="verification-detail-grid">
                <div class="metric-card">
                    <h3>Resolution Type</h3>
                    <p><strong>Mode:</strong> Manual edit</p>
                    <p><strong>Integrated into editor:</strong> Yes</p>
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
    `;
}

function applyApprovedPatchToEditor() {
    const patch = sleecPatchState.verifiedPatches[sleecPatchState.approvedPatchIndex];

    if (!patch || !patch.patched_sleec) {
        alert("Approve a patch with a generated SLEEC preview first.");
        return;
    }

    const input = document.getElementById("sleecInput");
    input.value = patch.patched_sleec;
    sleecPatchState.sleecText = patch.patched_sleec;
    updateSleecEditorHighlight();
    alert("Approved patch loaded into the SLEEC editor.");
}

function renderStakeholderDecision() {
    const out = document.getElementById("stakeholderDecisionOutput");

    if (!out) return;

    if (!sleecPatchState.verifiedPatches.length) {
        const llmCount = sleecPatchState.llmCandidates.length;
        out.innerHTML = `
            <div class="metric-card">
                <h3>No Verified Patch Selected</h3>
                <p><strong>LLM patches persisted immediately:</strong> ${escapeHtml(llmCount)}</p>
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
                ${renderRegressionReport(selectedPatch.regression_report)}
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
                              oninput="updatePatchEditorHighlight()"
                              onscroll="syncPatchEditorScroll()">${escapeHtml(selectedPatch.proposed_rule || "")}</textarea>
                </div>

                <label for="stakeholderExplanation">Explanation</label>
                <textarea id="stakeholderExplanation" class="plain-editor" spellcheck="true">${escapeHtml(selectedPatch.natural_language_explanation || "")}</textarea>

                <div id="patchVerificationOutput" class="verification-result empty">
                    This generated patch has already passed SLEEC verification. Re-verify after edits.
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

    if (useCase === "Custom") {
        const customText = sessionStorage.getItem("sleecPatchCustomText") || "";
        document.getElementById("sleecInput").value = customText;
        updateSleecEditorHighlight();
        return;
    }

    const data = await postJSON("/api/sleec-patch/load-usecase", {
        use_case: useCase
    });

    console.log("LOAD RESPONSE:", data);

    document.getElementById("sleecInput").value = data.sleec_text || "";
    sleecPatchState.sleecText = data.sleec_text || "";
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

async function clearPersistedData() {
    const confirmed = window.confirm(
        "Administrator reset: clear all saved patch results, candidate runs, verifications, and philosopher reviews so the workflow starts again from scratch?"
    );

    if (!confirmed) return;

    const data = await postJSON("/api/sleec-patch/clear-persisted-data", {});

    sessionStorage.removeItem("sleecPatchCustomText");
    sessionStorage.removeItem("sleecPatchCustomUseCase");
    resetPatchWorkbench();

    alert(
        "Administrator reset complete. Removed "
        + (data.cleared?.total_rows_deleted || 0)
        + " saved database row(s)."
    );
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

document.addEventListener("DOMContentLoaded", () => {
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
        labels: [
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
        ],
        canAdvance: canAdvancePatchWizard,
        onStepChange: updateWorkflowHeader,
        onRestart: resetPatchWorkbench
    });

    updateWorkflowHeader();
});
