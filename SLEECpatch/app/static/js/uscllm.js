let addedCount = 0;
let editedCount = 0;
let deletedCount = 0;

async function runResolution() {
    try {
        const checkedBoxes = document.querySelectorAll('input[name="usecase"]:checked');
        const stakeholder = document.getElementById("stakeholder").value;

        const selected = [];
        checkedBoxes.forEach(box => selected.push(box.value));

        const response = await fetch("/run-resolution", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                stakeholder: stakeholder,
                selected_use_cases: selected
            })
        });

        if (!response.ok) {
            throw new Error("Resolution failed");
        }

        const data = await response.json();

        console.log("FULL RESPONSE:", data);

        const tbody = document.querySelector("#resultTable tbody");

        if (!tbody) {
            alert("Table not found. Add table with id='resultTable'");
            return;
        }

        tbody.innerHTML = "";

        Object.entries(data.results).forEach(([usecase, result]) => {

            result.rules.forEach(rule => {

                tbody.innerHTML += `
                    <tr>
                        <td>${rule.id}</td>
                        <td contenteditable="true">${rule.condition}</td>
                        <td contenteditable="true">${rule.action}</td>
                        <td contenteditable="true">${rule.defeater || ""}</td>
                        <td>
                            <button onclick="deleteRule(this)">Delete</button>
                        </td>
                    </tr>
                `;

            });

        });

        document.getElementById("rulesCount").innerText =
            Object.values(data.results)[0].resolved_count;

        alert("Resolution completed successfully");

    } catch (error) {
        console.error(error);
        alert("Resolution failed");
    }
}


//run_resolution2



// ==================================
// Approve Results
// ==================================
async function approveResults() {
    try {
        const stakeholder = document.getElementById("stakeholder").value;
        const useCase = getSelectedUseCase();

        const response = await fetch("/approve-results", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                stakeholder: stakeholder,
                use_case: useCase
            })
        });

        if (!response.ok) {
            throw new Error("Approval failed");
        }

    } catch (error) {
        console.error(error);
        alert("Failed to approve results.");
    }
}


// ==================================
// Save Rules
// ==================================
async function saveRules() {
    try {
        const stakeholder = document.getElementById("stakeholder").value;

        const rows = document.querySelectorAll("#resultTable tbody tr");

        let rules = [];

        rows.forEach(row => {
            let cells = row.querySelectorAll("td");

            rules.push({
                id: cells[0].innerText,
                condition: cells[1].innerText,
                action: cells[2].innerText,
                defeater: cells[3].innerText
            });
        });

        const useCase = getSelectedUseCase();

        const response = await fetch("/save-rules", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                stakeholder: stakeholder,
                use_case: useCase,
                rules: rules
            })
        });

        if (!response.ok) {
            throw new Error("Save failed");
        }

        alert("Rules saved successfully");

    } catch (error) {
        console.error(error);
        alert("Failed to save rules.");
    }
}


// ==================================
// Helper: Get selected use case
// ==================================
function getSelectedUseCase() {
    const checked = document.querySelector('input[name="usecase"]:checked');
    return checked ? checked.value : null;
}


// ==================================
// Export Excel
// ==================================
function exportExcel() {
    const stakeholder = document.getElementById("stakeholder").value;
    const useCase = getSelectedUseCase();

    if (!useCase) {
        alert("Please select a use case.");
        return;
    }

    window.location.href = `/export-excel/${stakeholder}/${useCase}`;
}


// ==================================
// Delete Row (UI only)
// ==================================
function deleteRule(button) {
    const row = button.closest("tr");
    if (row) row.remove();
}




//database




async function saveRequirement_() {

    const reqCode =
        document.getElementById("newReqId").value;

    const reqText =
        document.getElementById("newReqText").value;

    const selected =
        document.querySelector(
            'input[name="usecase"]:checked'
        );

    await fetch('/add-requirement', {

        method: 'POST',

        headers: {
            'Content-Type': 'application/json'
        },

        body: JSON.stringify({

            usecase: selected.value,
            req_code: reqCode,
            req_text: reqText

        })

    });

    loadRequirements();

}




function addRequirement() {

    document.getElementById(
        "addModal"
    ).style.display = "block";

    document.getElementById(
        "newReqId"
    ).value = "";

    document.getElementById(
        "newReqText"
    ).value = "";
}


async function saveRequirement() {

    const reqCode =
        document.getElementById(
            "newReqId"
        ).value.trim();

    const reqText =
        document.getElementById(
            "newReqText"
        ).value.trim();

    const selected =
        document.querySelector(
            'input[name="usecase"]:checked'
        );

    if (!selected) {
        alert("Select a use case");
        return;
    }

    if (!reqCode || !reqText) {
        alert("Enter patch  code and text");
        return;
    }

    const response =
        await fetch(
            "/add-requirement",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({

                    usecase:
                        selected.value,

                    req_code:
                        reqCode,

                    req_text:
                        reqText

                })
            }
        );

    const result =
        await response.json();

    if (result.success) {

        alert(
            "patch added"
        );
        addedCount++;

        document.getElementById(
            "addModal"
        ).style.display =
            "none";
            document.getElementById(
        "addedCount"
        ).innerText = addedCount;    

        loadRequirements();

    } else {

        alert(
            result.error ||
            "Failed"
        );
    }
}


async function editRequirement(id) {

    const newText =
        prompt(
            "Enter updated patch "
        );

    if (
        !newText ||
        newText.trim() === ""
    ) {
        return;
    }

    const response =
        await fetch(
            "/update-requirement",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({

                    id: id,

                    req_text:
                        newText

                })
            }
        );

    const result =
        await response.json();

    if (result.success) {

        alert(
            "patch  updated"
        );
        editedCount++;

    document.getElementById(
        "editedCount"
    ).innerText = editedCount;

        loadRequirements();

    } else {

        alert(
            result.error ||
            "Update failed"
        );
    }
}


async function deleteRequirement(id) {

    const ok =
        confirm(
            "Delete this patch ?"
        );

    if (!ok) {
        return;
    }

    const response =
        await fetch(
            "/delete-requirement",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({

                    id: id

                })
            }
        );

    const result =
        await response.json();

    if (result.success) {

        alert(
            "patch  deleted"
        );
     deletedCount++;

    document.getElementById(
        "deletedCount"
    ).innerText = deletedCount;

        loadRequirements();

    } else {

        alert(
            result.error ||
            "Delete failed"
        );
    }
}




async function loadRequirements() {

    const selected =
        document.querySelector(
            'input[name="usecase"]:checked'
        );

    if(!selected){
        alert("Select a use case");
        return;
    }

    const response =
        await fetch(
            '/get-requirements?usecase=' +
            selected.value
        );

    const data =
        await response.json();

    let html = "";

    data.forEach(req => {
        html += `
        <tr>
            <td>${req.req_code}</td>
            <td>${req.req_text}</td>
            <td>${req.status}</td>
            <td>
    <button onclick="editRequirement(${req.id})">
        Edit
    </button>

    <button onclick="deleteRequirement(${req.id})">
        Delete
    </button>
</td>
        </tr>
        `;
    });

    document.getElementById(
        "requirementsBody"
    ).innerHTML = html;

}



async function loadActivitySummary() {
    const res = await fetch("/activity-summary");
    const data = await res.json();

    document.getElementById("addedCount").innerText = data.added;
    document.getElementById("editedCount").innerText = data.edited;
    document.getElementById("deletedCount").innerText = data.deleted;
}



/*

Example: ADD requirement

Inside /add-requirement after insert:
cur.execute("""
    UPDATE activity_summary
    SET added = added + 1
    WHERE id = 1
""")


EDIT:
cur.execute("""
    UPDATE activity_summary
    SET edited = edited + 1
    WHERE id = 1
""")

DELETE:
cur.execute("""
    UPDATE activity_summary
    SET deleted = deleted + 1
    WHERE id = 1
""")

conn.commit()


CREATE TABLE IF NOT EXISTS activity_summary (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    added INTEGER DEFAULT 0,
    edited INTEGER DEFAULT 0,
    deleted INTEGER DEFAULT 0
);

await loadActivitySummary();
*/


