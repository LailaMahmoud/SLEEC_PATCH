

<javascript>

async function runResolution() {

    const checkedBoxes = document.querySelectorAll(
        'input[name="usecase"]:checked'
    );

    const stakeholder =
    document.getElementById(
    "stakeholder"
    ).value;

    const selected = [];

    checkedBoxes.forEach(box => {
        selected.push(box.value);
    });

    const response = await fetch('/run-resolution', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json'
        },
        body: JSON.stringify({
            stakeholder: stakeholder,

            selected_use_cases: selected
        })
    });

    const data = await response.json();

    document.getElementById('output').innerText =
    

    //ggggg

    // ==================================
    // Populate Table Here
    // ==================================

    const tbody = document.querySelector(
            "#resultTable tbody"
        );

    tbody.innerHTML = "";

    Object.entries(
        data.results
    ).forEach(

        ([usecase, rules]) => {

            rules.forEach(rule => {

                tbody.innerHTML += `

                <tr class="rule-row">

                    <td>${rule.id}</td>

                    <td contenteditable="true">
                        ${rule.condition}
                    </td>

                    <td contenteditable="true">
                        ${rule.action}
                    </td>

                    <td contenteditable="true">
                        ${rule.defeater || ""}
                    </td>

                    <td>

                        <button
                            onclick="deleteRule(this)">
                            Delete
                        </button>

                    </td>

                </tr>

                `;
            });

        }

    );
}
///ggg


async function approveResults(){

    const stakeholder =
    document.getElementById(
        "stakeholder"
    ).value;

    await fetch(
        "/approve-results",
        {
            method:"POST",

            headers:{
                "Content-Type":
                "application/json"
            },

            body:JSON.stringify({

                stakeholder:
                    stakeholder,

                use_case:
                    currentUseCase

            })
        }
    );
}




async function saveRules() {

    const stakeholder =
        document.getElementById(
            "stakeholder"
        ).value;

    let rows =
        document.querySelectorAll(
            "#resultTable tbody tr"
        );

    let rules = [];

    rows.forEach(row => {

        let cells =
            row.querySelectorAll("td");

        rules.push({

            id:
                cells[0].innerText,

            condition:
                cells[1].innerText,

            action:
                cells[2].innerText,

            defeater:
                cells[3].innerText

        });

    });

    const useCase =
        getSelectedUseCase();

    const response =
        await fetch(
            "/save-rules",
            {
                method: "POST",

                headers: {
                    "Content-Type":
                        "application/json"
                },

                body: JSON.stringify({

                    stakeholder:
                        stakeholder,

                    use_case:
                        useCase,

                    rules:
                        rules

                })
            }
        );

    const result =
        await response.json();

    alert(
        "Rules saved successfully"
    );
}



function getSelectedUseCase() {

    const checked =

        document.querySelector(
            'input[name="usecase"]:checked'
        );

    if (!checked)
        return null;

    return checked.value;
}



function exportExcel() {

    const stakeholder =
        document.getElementById(
            "stakeholder"
        ).value;

    const useCase =
        getSelectedUseCase();

    if (!useCase) {

        alert(
            "Please select a use case."
        );

        return;
    }

    window.location.href =

        `/export-excel/${
            stakeholder
        }/${
            useCase
        }`;
}





function deleteRule(button){

    let row =
        button.closest("tr");

    row.remove();
}


</javascriptscript>