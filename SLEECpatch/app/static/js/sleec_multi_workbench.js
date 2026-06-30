let currentResult = null;

function runWithLoader(work, text) {
    if (window.withLoader) {
        return window.withLoader(work, text);
    }
    return work();
}

function collectMultiStakeholderRules() {

    const stakeholders = ["S1", "S2", "S3", "S4", "S5"];

    const stakeholdersRules = {};

    stakeholders.forEach(sid => {

        const textarea = document.getElementById(`rules-${sid}`);

        const rules = textarea.value
            .split("\n")
            .map(x => x.trim())
            .filter(x => x.length > 0);

        if (rules.length > 0) {
            stakeholdersRules[sid] = rules;
        }
    });

    return stakeholdersRules;
}


function renderAll(result) {
    document.getElementById("sleecOutput").innerText =
        result.sleec_text || result.combined_sleec || result.combined_sleec_text || "";

    renderMapping(result.mapping || result.combined_mapping || {});

    renderRelationships(result.relationships || []);

    renderIssues(
        result.detections ||
        result.issues ||
        result.cross_stakeholder_issues ||
        {}
    );

    renderPatches(
        result.patches ||
        result.resolution_patches ||
        []
    );
}


function renderMapping(mapping) {
    const out = document.getElementById("mappingOutput");
    out.innerHTML = "";

    if (!mapping || Object.keys(mapping).length === 0) {
        out.innerHTML = `<p class="muted">No mapping generated.</p>`;
        return;
    }

    Object.entries(mapping).forEach(([nl, formal]) => {
        out.innerHTML += `
            <div class="row">
                <span>${nl}</span>
                <strong>${formal}</strong>
            </div>
        `;
    });
}

async function analyzeMulti() {
    const useCase = document.getElementById("useCase").value;

    const stakeholdersRules = {};

    document.querySelectorAll("textarea[id^='rules-']").forEach(textarea => {
        const sid = textarea.id.replace("rules-", "");

        stakeholdersRules[sid] = textarea.value
            .split("\n")
            .map(x => x.trim())
            .filter(Boolean);
    });

    console.log("SENDING:", stakeholdersRules);

    const response = await runWithLoader(() => fetch("/api/sleec/analyze-multiple", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                use_case: useCase,
                stakeholders_rules: stakeholdersRules
            })
        }),
        "Analysing multi-stakeholder rules..."
    );

    currentResult = await response.json();

    console.log("RESULT:", currentResult);

    if (!response.ok) {
        alert(currentResult.error || "Multi analysis failed");
        return;
    }

    renderAll(currentResult);
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
                <pre>${JSON.stringify(r, null, 2)}</pre>
            </div>
        `;
    });
}

function renderIssues(issues) {
    const out = document.getElementById("issuesOutput");
    out.innerHTML = "";

    if (!issues || Object.keys(issues).length === 0) {
        out.innerHTML = `<p class="muted">No cross-stakeholder issues detected.</p>`;
        return;
    }

    Object.entries(issues).forEach(([type, items]) => {
        out.innerHTML += `
            <div class="box">
                <h4>${type}</h4>
                <strong>${Array.isArray(items) ? items.length : 1}</strong>
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
            <div class="box patch" id="patch-${i}">
                <h4>${p.patch_id} — ${p.issue_type}</h4>

                <label>Original Rule</label>
                <textarea rows="3" readonly>${p.original_rule}</textarea>

                <label>GPT Proposed Patch</label>
                <textarea id="patchText-${i}" rows="4" disabled>${p.proposed_rule || p.patch || p.resolution || p.suggested_rule || ""}</textarea>
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

function selectPatch(index, checked) {
    currentResult.patches[index].selected = checked;
}

async function savePatches() {
    if (!currentResult) {
        alert("Run analysis first.");
        return;
    }

    const useCase = document.getElementById("useCase").value;

    const selected = currentResult.patches.filter(p => p.selected);

    const response = await runWithLoader(() => fetch("/api/sleec/save-patches", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                stakeholder: "MULTI",
                use_case: useCase,
                patches: selected
            })
        }),
        "Saving selected patches..."
    );

    const data = await response.json();

    alert("Saved to: " + data.path);
}

async function applySelectedPatches() {
    if (!currentResult) {
        alert("Run analysis first.");
        return;
    }

    const selectedPatches = currentResult.patches.filter(p => p.selected);

    if (selectedPatches.length === 0) {
        alert("Select at least one patch.");
        return;
    }

    const response = await runWithLoader(() => fetch("/api/sleec/apply-patches", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                rules: currentResult.rules,
                patches: selectedPatches
            })
        }),
        "Applying selected patches..."
    );

    const data = await response.json();

    currentResult.final_rules = data.final_rules;

    renderFinalRules(data.final_rules);
}

function renderFinalRules(rules) {
    const out = document.getElementById("finalRulesOutput");

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

async function approveResolution() {
    const stakeholder = document.getElementById("approvalStakeholder").value;
    const useCase = document.getElementById("useCase").value;

    const response = await runWithLoader(() => fetch("/api/sleec/approve", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                stakeholder: stakeholder,
                use_case: useCase
            })
        }),
        "Saving approval..."
    );

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

    if (mode === "final") {
        uscRules = currentResult.final_rules || currentResult.rules || [];
    } else if (mode === "patches") {
        uscRules = currentResult.patches || [];
    } else if (mode === "selected") {
        uscRules = (currentResult.patches || []).filter(p => p.selected);
    }

    uscRules = normalizeForCompare(uscRules);

    const response = await runWithLoader(() => fetch("/api/sleec/compare", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({
                expert_file: expertFile,
                usc_rules: uscRules
            })
        }),
        "Comparing with expert reference..."
    );

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
        alert("Missing HTML element: comparisonOutput");
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
