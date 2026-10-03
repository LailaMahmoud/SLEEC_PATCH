// Offline browser-state checks for the production report script.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");
const vm = require("node:vm");

function setup() {
    const elements = new Map();
    const pending = [];
    const element = id => {
        if (!elements.has(id)) elements.set(id, {
            value: "", checked: false, innerHTML: "", textContent: "", className: "", disabled: false,
            listeners: {}, classList: {add() {}, remove() {}}, querySelectorAll: () => [],
            addEventListener(type, fn) { this.listeners[type] = fn; }
        });
        return elements.get(id);
    };
    let start;
    const context = vm.createContext({URLSearchParams, console,
        document: {getElementById: element, addEventListener(_name, fn) { start = fn; }},
        window: {clearTimeout() {}, setTimeout() {}},
        fetch: (url, options) => new Promise(resolve => pending.push({url, options, resolve}))
    });
    vm.runInContext(fs.readFileSync(path.join(__dirname, "../SLEECpatch/app/static/js/sleec_patch_report.js"), "utf8"), context);
    start();
    return {context, element, pending};
}

function response(useCase, patches = 1, issueCount = 9) {
    const payload = {status: "OK", use_case: useCase,
        evaluation_details: Array.from({length: patches}, () => ({use_case: useCase, verified: 1})),
        report_metrics: {total_patch_rows: patches, avg_run_time_seconds: null},
        evaluation_summary: [{use_case: useCase, total_records: patches, repair_run_count: 1}],
        recorded_diagnoses: [{use_case: useCase, run_id: "run-1", status: "recorded", issue_count: issueCount}],
        philosopher_review_metrics: {overall: {accepted: 0}}, philosopher_review_summary: {accepted: 99}};
    return {ok: true, json: async () => payload};
}

const flush = () => new Promise(resolve => setImmediate(resolve));

test("a late response cannot overwrite the newly selected use case", async () => {
    const {element, pending} = setup();
    element("reportUseCase").value = "DAISY";
    const current = element("reportUseCase").listeners.change();
    assert.match(pending[1].url, /use_case=DAISY/);
    assert.equal(pending[1].options.cache, "no-store");
    pending[1].resolve(response("DAISY", 2));
    await current;
    pending[0].resolve(response("ALL", 20));
    await flush();
    assert.equal(element("statPatches").textContent, 2);
    assert.match(element("reportScope").textContent, /^Showing DAISY/);
    assert.equal(element("loadReportButton").disabled, false);
});

test("changing filters clears previous values and failed loads remain empty", async () => {
    const {element, pending} = setup();
    pending[0].resolve(response("ALL", 20));
    await flush();
    element("reportUseCase").value = "DAISY";
    const current = element("reportUseCase").listeners.change();
    assert.equal(element("statPatches").textContent, 0);
    pending[1].resolve({ok: false, status: 500, json: async () => ({status: "ERROR", error: "Database unavailable"})});
    await current;
    assert.equal(element("statPatches").textContent, 0);
    assert.match(element("reportScope").textContent, /Could not load results for DAISY/);
});

test("patch count, diagnosis count and use-case count are shown separately", async () => {
    const {element, pending} = setup();
    pending[0].resolve(response("DAISY", 18, 9));
    await flush();
    assert.equal(element("statPatches").textContent, 18);
    assert.equal(element("summaryCount").textContent, "1 use case");
    assert.match(element("diagnosisOutput").innerHTML, /<td\b[^>]*>9<\/td>/);
    assert.match(element("summaryOutput").innerHTML, />Patches</);
    assert.equal(element("statTime").textContent, "–");
    assert.doesNotMatch(element("expertOutput").innerHTML, /99/);
});

test("missing recorded diagnosis is not presented as zero issues", async () => {
    const {element, pending} = setup();
    const result = response("DAISY");
    const payload = await result.json();
    payload.recorded_diagnoses[0] = {use_case: "DAISY", status: "unavailable", issue_count: null};
    pending[0].resolve({ok: true, json: async () => payload});
    await flush();
    assert.match(element("diagnosisOutput").innerHTML, /Not recorded/);
    assert.doesNotMatch(element("diagnosisOutput").innerHTML, /<td\b[^>]*>0<\/td>/);
});
