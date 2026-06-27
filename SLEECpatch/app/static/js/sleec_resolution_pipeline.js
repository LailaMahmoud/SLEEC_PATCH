let pipelineState = {
    nlRules: [],
    sleecText: "",
    relations: [],
    analysis: {},
    patches: [],
    validatedPatches: [],
    finalSleec: ""
};

function getNlRules() {
    return document
        .getElementById("nlInput")
        .value
        .split("\n")
        .map(x => x.trim())
        .filter(Boolean);
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


function changePipelineMode() {
    const mode = document.getElementById("pipelineMode").value;

    document.getElementById("singleStakeholderBox").style.display =
        mode === "single" ? "block" : "none";

    document.getElementById("multiStakeholderBox").style.display =
        mode === "multi" ? "block" : "none";
}

function getPipelineMode() {
    return document.getElementById("pipelineMode").value;
}

function getUseCase() {
    return document.getElementById("useCase").value;
}

function getStakeholder() {
    return document.getElementById("stakeholder").value;
}

function getMultiStakeholderRules() {
    return {
        S1: document.getElementById("rulesInputS1").value.split("\n").map(x => x.trim()).filter(Boolean),
        S2: document.getElementById("rulesInputS2").value.split("\n").map(x => x.trim()).filter(Boolean),
        S3: document.getElementById("rulesInputS3").value.split("\n").map(x => x.trim()).filter(Boolean),
        S4: document.getElementById("rulesInputS4").value.split("\n").map(x => x.trim()).filter(Boolean),
        S5: document.getElementById("rulesInputS5").value.split("\n").map(x => x.trim()).filter(Boolean)
    };
}


async function step1NlToSleec() {
    const mode = getPipelineMode();
    const useCase = getUseCase();

    let payload = {
        mode: mode,
        use_case: useCase
    };

    if (mode === "single") {
        const nlRules = getNlRules();

        if (nlRules.length === 0) {
            alert("Please enter rules or load a use case.");
            return;
        }

        payload.stakeholder = getStakeholder();
        payload.nl_rules = nlRules;
    }

    if (mode === "multi") {
        payload.stakeholders_rules = getMultiStakeholderRules();

        const totalRules = Object.values(payload.stakeholders_rules)
            .reduce((sum, arr) => sum + arr.length, 0);

        if (totalRules === 0) {
            alert("Please enter rules for stakeholders or load a use case.");
            return;
        }
    }

    const data = await postJSON("/api/pipeline/nl-to-sleec", payload);

    pipelineState.mode = mode;
    pipelineState.useCase = useCase;
    pipelineState.sleecText = data.sleec_text;
    pipelineState.rules = data.rules || [];

    document.getElementById("sleecOutput").innerText = data.sleec_text;
}

async function loadUseCaseRules() {
    const useCase = getUseCase();
    const mode = getPipelineMode();

    const data = await postJSON("/api/pipeline/load-use-case", {
        use_case: useCase
    });

    const text = data.rules.join("\n");

    if (mode === "single") {
        document.getElementById("nlInput").value = text;
    } else {
        document.getElementById("rulesInputS1").value = text;
        document.getElementById("rulesInputS2").value = text;
        document.getElementById("rulesInputS3").value = text;
        document.getElementById("rulesInputS4").value = text;
        document.getElementById("rulesInputS5").value = text;
    }
}
// Step 1
async function step1NlToSleec1() {
    const nlRules = getNlRules();

    if (nlRules.length === 0) {
        alert("Please enter natural language rules.");
        return;
    }

    const data = await postJSON("/api/pipeline/nl-to-sleec", {
        nl_rules: nlRules
    });

    pipelineState.nlRules = nlRules;
    pipelineState.sleecText = data.sleec_text;

    document.getElementById("sleecOutput").innerText =
        data.sleec_text;
}

// Step 2
async function step2ExtractRelations() {
    if (!pipelineState.sleecText) {
        alert("Convert NL to SLEEC first.");
        return;
    }

    const data = await postJSON("/api/pipeline/extract-relations", {
        sleec_text: pipelineState.sleecText
    });

    pipelineState.relations = data.relations || [];

    renderRelations();
}

function renderRelations() {
    const out = document.getElementById("relationsOutput");

    let html = `
        <table>
            <thead>
                <tr>
                    <th>Accept</th>
                    <th>Source</th>
                    <th>Relation</th>
                    <th>Target</th>
                    <th>Explanation</th>
                </tr>
            </thead>
            <tbody>
    `;

    pipelineState.relations.forEach((r, i) => {
        html += `
            <tr>
                <td>
                    <input type="checkbox"
                           onchange="toggleRelation(${i}, this.checked)">
                </td>
                <td>${r.source}</td>
                <td>${r.relation}</td>
                <td>${r.target}</td>
                <td>${r.explanation || ""}</td>
            </tr>
        `;
    });

    html += `
            </tbody>
        </table>
    `;

    out.innerHTML = html;
}

function toggleRelation(index, checked) {
    pipelineState.relations[index].accepted = checked;
}

// Step 3
async function step3Analyse() {
    const accepted = pipelineState.relations.filter(r => r.accepted);

    if (accepted.length === 0) {
        alert("No semantic relations accepted. Analysis will run without candidate filters.");
    }

    const data = await postJSON("/api/pipeline/analyse", {
        sleec_text: pipelineState.sleecText,
        relations: pipelineState.relations
    });

    pipelineState.analysis = data;

    renderAnalysis(data.structured || {});
}

function renderAnalysis(structured) {
    const out = document.getElementById("analysisOutput");

    let html = "";

    Object.entries(structured).forEach(([type, items]) => {
        html += `
            <div class="card">
                <h3>${type}</h3>
                <p><strong>Count:</strong> ${items.length}</p>
                <pre>${JSON.stringify(items, null, 2)}</pre>
            </div>
        `;
    });

    out.innerHTML = html || "No issues detected.";
}

// Step 4
async function step4GeneratePatches() {
    const issues = pipelineState.analysis.structured || {};

    const data = await postJSON("/api/pipeline/generate-patches", {
        sleec_text: pipelineState.sleecText,
        issues: issues,
        relations: pipelineState.relations
    });

    pipelineState.patches = data.patches || [];

    renderPatches();
}

function renderPatches() {
    const out = document.getElementById("patchOutput");

    if (!pipelineState.patches.length) {
        out.innerHTML = "No patches generated.";
        return;
    }

    let html = "";

    pipelineState.patches.forEach((p) => {
        html += `
            <div class="card">
                <h3>${p.id} — ${p.issue_type}</h3>
                <p><strong>Operation:</strong> ${p.operation}</p>
                <p><strong>Target Rule:</strong> ${p.target_rule_id || ""}</p>
                <p><strong>Original:</strong></p>
                <pre>${p.original_rule || ""}</pre>
                <p><strong>Proposed:</strong></p>
                <pre>${p.proposed_rule || ""}</pre>
                <p>${p.explanation || ""}</p>
            </div>
        `;
    });

    out.innerHTML = html;
}

// Step 5
async function step5ValidatePatches() {
    if (!pipelineState.patches.length) {
        alert("Generate patches first.");
        return;
    }

    const data = await postJSON("/api/pipeline/validate-patches", {
        sleec_text: pipelineState.sleecText,
        patches: pipelineState.patches,
        relations: pipelineState.relations
    });

    pipelineState.validatedPatches = data.patches || [];

    renderValidatedPatches();
}


function sleecToNatural(ruleText) {
    if (!ruleText) return "";

    let text = ruleText.trim();

    // remove rule id: r1, r2, etc.
    text = text.replace(/^r\d+\s+/i, "");

    // convert keywords
    text = text.replace(/\bwhen\b/i, "When");
    text = text.replace(/\bthen\b/i, ", then");
    text = text.replace(/\bunless\b/i, ", unless");

    // remove braces
    text = text.replace(/[{}]/g, "");

    // make not easier to read
    text = text.replace(/\bnot\s+/gi, "do not ");

    return text;
}


function renderValidatedPatches() {
    const out = document.getElementById("validatedPatchOutput");

    if (!pipelineState.validatedPatches.length) {
        out.innerHTML = "<p>No validated patches yet.</p>";
        return;
    }

    let html = `<div class="patch-grid">`;

    pipelineState.validatedPatches.forEach((p, i) => {

        const status = p.valid
            ? `<span class="badge good">Valid</span>`
            : `<span class="badge bad">Invalid</span>`;

        html += `
            <div class="patch-card" id="patch-card-${i}">
                <h3>${p.id} — ${p.issue_type}</h3>

                <div class="patch-status">
                    ${status}
                </div>

                <label>Original Rule</label>
                <textarea rows="4" readonly>${sleecToNatural(p.original_rule || "")}</textarea>

                <label>GPT Proposed Patch</label>
                <textarea id="validatedPatchText-${i}" rows="5" disabled>${sleecToNatural(p.proposed_rule || "")}</textarea>

                <p class="patch-explanation">
                    ${p.explanation || ""}
                </p>

                <label class="select-row">
                    <input
                        type="checkbox"
                        ${p.selected ? "checked" : ""}
                        ${p.valid ? "" : "disabled"}
                        onchange="selectValidatedPatch('${p.id}', this.checked)">
                    Select this patch
                </label>

                <div class="patch-actions">
                    <button class="secondary" onclick="enableValidatedPatchEdit(${i})">
                        Edit
                    </button>

                    <button class="success" onclick="saveValidatedPatchEdit(${i})">
                        Save Edit
                    </button>

                    <button class="danger" onclick="deleteValidatedPatch(${i})">
                        Delete
                    </button>
                </div>
            </div>
        `;
    });

    html += `</div>`;

    out.innerHTML = html;
}

function enableValidatedPatchEdit(index) {
    const textarea = document.getElementById(`validatedPatchText-${index}`);
    textarea.disabled = false;
    textarea.focus();
}


function saveValidatedPatchEdit(index) {
    const textarea = document.getElementById(`validatedPatchText-${index}`);

    pipelineState.validatedPatches[index].natural_proposed_rule = textarea.value;
    pipelineState.validatedPatches[index].edited_by_human = true;

    textarea.disabled = true;

    alert("Patch edit saved.");
}


function deleteValidatedPatch(index) {
    pipelineState.validatedPatches[index].deleted = true;

    pipelineState.validatedPatches.splice(index, 1);

    renderValidatedPatches();

    alert("Patch deleted.");
}


async function selectValidatedPatch(patchId, checked) {

    pipelineState.validatedPatches.forEach(p => {
        p.selected = false;
    });

    const selected = pipelineState.validatedPatches.find(
        p => String(p.id) === String(patchId)
    );

    if (!selected || !checked) {
        renderValidatedPatches();
        return;
    }

    selected.selected = true;

    const data = await postJSON("/api/pipeline/select-patch", {
        sleec_text: pipelineState.sleecText,
        patches: pipelineState.validatedPatches,
        patch_id: patchId
    });

    if (!data.selected_patch) {
        alert(data.error || "Patch not found.");
        return;
    }

    pipelineState.finalSleec = data.final_sleec;

    document.getElementById("finalOutput").innerHTML = `
        <h3>Selected Patch</h3>

        <div class="card">
            <p><strong>Patch:</strong> ${data.selected_patch.id}</p>
            <p><strong>Issue:</strong> ${data.selected_patch.issue_type}</p>

            <p><strong>Natural Language Patch:</strong></p>
            <pre>${
                data.selected_patch.natural_proposed_rule ||
                sleecToNatural(data.selected_patch.proposed_rule || "")
            }</pre>
        </div>

        <h3>Final Refined Rules</h3>
        <pre>${data.final_sleec || "No final SLEEC generated."}</pre>
    `;

    renderValidatedPatches();
}

function renderValidatedPatchess() {
    const out = document.getElementById("validatedPatchOutput");

    let html = `
        <table>
            <thead>
                <tr>
                    <th>Select</th>
                    <th>Patch</th>
                    <th>Issue</th>
                    <th>Status</th>
                    <th>Explanation</th>
                </tr>
            </thead>
            <tbody>
    `;

    pipelineState.validatedPatches.forEach((p) => {
        const status = p.valid
            ? `<span class="badge good">Valid</span>`
            : `<span class="badge bad">Invalid</span>`;

        html += `
            <tr>
                <td>
                    <button class="primary"
                        ${p.valid ? "" : "disabled"}
                        onclick="selectFinalPatch('${p.id}')">
                        Select
                    </button>
                </td>
                <td>${p.id}</td>
                <td>${p.issue_type}</td>
                <td>${status}</td>
                <td>${p.explanation || ""}</td>
            </tr>
        `;
    });

    html += "</tbody></table>";

    out.innerHTML = html;
}

// Step 6
async function selectFinalPatch(patchId) {

   // console.log("PATCH ID:", patchId);
    //console.log("PATCHES:", pipelineState.validatedPatches);

    const data = await postJSON("/api/pipeline/select-patch", {
        patches: pipelineState.validatedPatches,
        patch_id: patchId
    });

    console.log("SELECT RESULT:", data);

    if (!data.selected_patch) {
        document.getElementById("finalOutput").innerHTML = `
            <h3>No patch selected</h3>
            <pre>${data.error || "Patch ID not found"}</pre>
        `;
        return;
    }

    pipelineState.finalSleec = data.final_sleec;

    document.getElementById("finalOutput").innerHTML = `
        <h3>Selected Patch</h3>
        <pre>${JSON.stringify(data.selected_patch, null, 2)}</pre>

        <h3>Final SLEEC</h3>
        <pre>${data.final_sleec || "No final SLEEC generated."}</pre>
    `;
}