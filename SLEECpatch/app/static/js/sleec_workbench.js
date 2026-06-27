let currentResult = null;

function getRules() {
    return document
        .getElementById("rulesInput")
        .value
        .split("\n")
        .map(x => x.trim())
        .filter(x => x.length > 0);
}

async function analyzeSingle() {

    let rules = getRules();

    const stakeholder =
        document.getElementById("stakeholder").value;

    const useCase =
        document.getElementById("useCase").value;

    // No manual rules entered
    if (rules.length === 0) {

        const response = await fetch(
            "/api/sleec/load-use-case",
            {
                method: "POST",
                headers: {
                    "Content-Type": "application/json"
                },
                body: JSON.stringify({
                    use_case: useCase
                })
            }
        );

        const data = await response.json();

        rules = data.rules;
    }

    const response = await fetch(
        "/api/sleec/analyze-single",
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                stakeholder: stakeholder,
                use_case: useCase,
                rules: rules
            })
        }
    );

    currentResult = await response.json();

    renderAll(currentResult);
}

function renderAll(result) {
    document.getElementById("sleecOutput").innerText =
        result.sleec_text || "";

    renderMapping(result.mapping || {});

    renderRelationships(result.relationships || []);

    renderIssues(result.detections || {});

    renderPatches(result.patches || []);
}

function renderMapping(mapping) {
    const out = document.getElementById("mappingOutput");
    out.innerHTML = "";

    Object.entries(mapping).forEach(([nl, formal]) => {
        out.innerHTML += `
            <div class="row">
                <span>${nl}</span>
                <strong>${formal}</strong>
            </div>
        `;
    });
}

function renderRelationships(relationships) {
    const out = document.getElementById("relationshipOutput");
    out.innerHTML = "";

    if (!relationships || relationships.length === 0) {
        out.innerHTML = `<p class="muted">No SLEEC relationships detected.</p>`;
        return;
    }

    relationships.forEach((r, i) => {
        out.innerHTML += `
            <div class="box">
                <h4>Relationship ${i + 1}</h4>
                <p>${r.formal}</p>
                <button onclick="validateRelationship(${i}, true)">Agree</button>
                <button onclick="validateRelationship(${i}, false)">Reject</button>
            </div>
        `;
    });
}

function validateRelationship(index, value) {
    if (!currentResult.relationships) {
        currentResult.relationships = [];
    }

    if (!currentResult.relationships[index]) {
        currentResult.relationships[index] = {};
    }

    currentResult.relationships[index].validated = value;

    alert(value ? "Relationship accepted" : "Relationship rejected");
}

function renderIssues(issues) {
    const out = document.getElementById("issuesOutput");
    out.innerHTML = "";

    Object.entries(issues).forEach(([type, items]) => {
        out.innerHTML += `
            <div class="box">
                <h4>${type}</h4>
                <strong>${items.length}</strong>
                <pre>${JSON.stringify(items, null, 2)}</pre>
            </div>
        `;
    });
}

function renderPatches(patches) {
    const out = document.getElementById("patchOutput");
    out.innerHTML = "";

    if (!patches || patches.length === 0) {
        out.innerHTML = `<p class="muted">No GPT patches generated.</p>`;
        return;
    }

    patches.forEach((p, i) => {
        out.innerHTML += `
            <div class="box patch" data-index="${i}" id="patch-${i}">
                <h4>${p.patch_id} — ${p.issue_type}</h4>

                <label>Original Rule</label>
                <textarea rows="3" readonly>${p.original_rule}</textarea>

                <label>GPT Proposed Patch</label>
                                
                <textarea id="patchText-${i}" rows="4" disabled>${
                    p.proposed_rule || p.patch || p.resolution || p.suggested_rule || ""
                }</textarea>
                <p>${p.natural_language_explanation}</p>

                <label>
                    <input
                        type="checkbox"
                        ${p.selected ? "checked" : ""}
                        onchange="selectPatch(${i}, this.checked)">
                    Select this patch
                </label>

                <div class="patch-actions">
                    <button class="secondary" onclick="enablePatchEdit(${i})">
                        Edit
                    </button>

                    <button class="success" onclick="savePatchEdit(${i})">
                        Save Edit
                    </button>

                    <button class="danger" onclick="deletePatch(${i})">
                        Delete
                    </button>
                </div>
            </div>
        `;
    });
    //console.log("PATCH:", p);
}


function enablePatchEdit(index) {
    const textarea = document.getElementById(`patchText-${index}`);
    textarea.disabled = false;
    textarea.focus();
}

function savePatchEdit(index) {
    const textarea = document.getElementById(`patchText-${index}`);

    currentResult.patches[index].proposed_rule = textarea.value;
    currentResult.patches[index].edited_by_stakeholder = true;

    textarea.disabled = true;

    alert("Patch edit saved.");
}

function deletePatch(index) {
    currentResult.patches.splice(index, 1);
    renderPatches(currentResult.patches);
}



function editPatch(index, value) {
    currentResult.patches[index].proposed_rule = value;
}

function selectPatch(index, checked) {
    currentResult.patches[index].selected = checked;
}

async function savePatches() {
    if (!currentResult) {
        alert("Run analysis first.");
        return;
    }

    const stakeholder = document.getElementById("stakeholder").value;
    const useCase = document.getElementById("useCase").value;

    const selected = currentResult.patches.filter(p => p.selected);

    const response = await fetch("/api/sleec/save-patches", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            stakeholder: stakeholder,
            use_case: useCase,
            patches: selected
        })
    });

    const data = await response.json();

    alert("Saved to: " + data.path);
}

async function approveResolution() {
    const stakeholder = document.getElementById("stakeholder").value;
    const useCase = document.getElementById("useCase").value;

    const response = await fetch("/api/sleec/approve", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            stakeholder: stakeholder,
            use_case: useCase
        })
    });

    const data = await response.json();

    alert("Approved. Saved to: " + data.path);
}


function normalizeForCompare(items) {
    return (items || []).map((r, i) => ({
        id: r.id || r.target_rule_id || r.patch_id || `p${i + 1}`,
        condition: r.condition || r.proposed_rule || r.patch || "",
        action: r.action || "",
        defeater: r.defeater || ""
    }));
}
async function compareWithExpert(mode = "final") {
    if (!currentResult) {
        alert("Run analysis first.");
        return;
    }

    const expertFile = document.getElementById("expertFile").value.trim();

    let uscRules = [];

    if (mode === "rules") {
        uscRules = currentResult.rules || [];
    }
    else if (mode === "final") {
        uscRules = currentResult.final_rules || [];
    }
    else if (mode === "selected") {
        uscRules = (currentResult.patches || []).filter(p => p.selected);
    }
    uscRules = normalizeForCompare(uscRules);

    const response = await fetch("/api/sleec/compare", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({
            expert_file: expertFile,
            usc_rules: uscRules
        })
    });

    const comparison = await response.json();

    if (!response.ok) {
        alert(comparison.error || "Comparison failed");
        return;
    }

    renderComparison(comparison);
}

function renderComparison(c) {
    const out = document.getElementById("comparisonOutput");

    if (!out) {
        alert("Missing div: comparisonOutput");
        return;
    }

    out.innerHTML = "";

    Object.entries(c).forEach(([key, value]) => {
        out.innerHTML += `
            <div class="box metric">
                <small>${key.replaceAll("_", " ")}</small>
                <strong>${JSON.stringify(value, null, 2)}</strong>
            </div>
        `;
    });
}






async function applySelectedPatches() {
    if (!currentResult) {
        alert("Run analysis first.");
        return;
    }

    const selectedPatches =
        currentResult.patches.filter(
            p => p.selected
        );

    if (selectedPatches.length === 0) {
        alert("Select at least one patch.");
        return;
    }

    const response = await fetch(
        "/api/sleec/apply-patches",
        {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                rules: currentResult.rules,
                patches: selectedPatches
            })
        }
    );

    const data = await response.json();

    currentResult.final_rules =
        data.final_rules;

    renderFinalRules(
        data.final_rules
    );
}

function renderFinalRules(rules) {
    const out =
        document.getElementById(
            "finalRulesOutput"
        );

    let html = `
        <table>
            <thead>
                <tr>
                    <th>ID</th>
                    <th>Condition</th>
                    <th>Action</th>
                    <th>Defeater</th>
                </tr>
            </thead>
            <tbody>
    `;

    rules.forEach(r => {
        html += `
            <tr>
                <td>${r.id}</td>
                <td>${r.condition}</td>
                <td>${r.action}</td>
                <td>${r.defeater || ""}</td>
            </tr>
        `;
    });

    html += `
            </tbody>
        </table>
    `;

    out.innerHTML = html;
}




async function runAllUseCases() {
    const response = await fetch("/api/sleec/run-all-use-cases", {
        method: "POST"
    });

    const data = await response.json();

    renderAllUseCases(data);
}

function renderAllUseCases2(data) {
    const out = document.getElementById("allUseCasesOutput");
    out.innerHTML = "";

    Object.entries(data).forEach(([useCase, result]) => {
        out.innerHTML += `
            <div class="box">
                <h3>${useCase}</h3>
                <p><strong>Rules:</strong> ${result.rules_count}</p>
                <p><strong>Patches:</strong> ${result.patches_count}</p>
                <pre>${JSON.stringify(result.comparison, null, 2)}</pre>
            </div>
        `;
    });
}


function renderAllUseCases(data) {
    const tbody = document.querySelector("#evaluationTable tbody");

    tbody.innerHTML = "";

    Object.entries(data).forEach(([useCase, r]) => {
        tbody.innerHTML += `
            <tr>
                <td>${useCase}</td>
                <td>${r.rules_count}</td>
                <td>${r.issues_count}</td>
                <td>${r.patches_count}</td>
                <td>${r.similarity}</td>
            </tr>
        `;
    });
}