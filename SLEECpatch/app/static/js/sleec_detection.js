function runWithLoader(work, text) {
    if (window.withLoader) {
        return window.withLoader(work, text);
    }
    return work();
}

async function runDetectionByUseCase() {

    const useCase = document.getElementById("useCase").value;

    const response = await runWithLoader(() => fetch("/api/sleec-detection/by-usecase", {
            method: "POST",
            headers: {
                "Content-Type": "application/json"
            },
            body: JSON.stringify({
                use_case: useCase
            })
        }),
        "Running SLEEC detection..."
    );

    const data = await response.json();

    if (data.status === "error") {
        alert(data.message);
        return;
    }

    document.getElementById("sleecText").innerText =
        data.sleec_input;

    renderDetectionResults(data.detections);
}


function renderDetectionResults(detections) {

    const summary = document.getElementById("summary");
    const results = document.getElementById("results");

    summary.innerHTML = "";
    results.innerHTML = "";

    Object.entries(detections).forEach(([type, result]) => {

        const count = result.count || 0;

        const statusClass = result.success ? "ok" : "fail";

        summary.innerHTML += `
            <div class="summary-card ${statusClass}">
                <h3>${formatName(type)}</h3>
                <strong>${count}</strong>
                <small>${result.success ? "OK" : "Failed"}</small>
            </div>
        `;

        results.innerHTML += `
            <div class="result-card">
                <h3>${formatName(type)}</h3>

                <p>
                    <strong>Status:</strong>
                    ${result.success ? "Success" : "Failed"}
                </p>

                <p>
                    <strong>Message:</strong>
                    ${result.message || ""}
                </p>

                <pre>${JSON.stringify(result.findings || [], null, 2)}</pre>
            </div>
        `;
    });
}


function formatName(text) {
    return text
        .replaceAll("_", " ")
        .replace(/\b\w/g, c => c.toUpperCase());
}
