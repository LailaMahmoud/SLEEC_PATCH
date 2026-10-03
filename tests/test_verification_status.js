// Exercise the actual verification UI, with unrelated navigation stubbed out.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function setup(response) {
    const elements = new Map();
    const element = id => {
        if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', textContent: '', className: ''});
        return elements.get(id);
    };
    const context = vm.createContext({console, alert() {},
        document: {getElementById: element, addEventListener() {}}, window: {},
        sessionStorage: {getItem() { return null; }}, response});
    const run = code => vm.runInContext(code, context);
    run(fs.readFileSync(path.join(__dirname, '../SLEECpatch/app/static/js/sleec_patch_workbench.js'), 'utf8'));
    run(`postJSON = async () => response;
         sleecPatchState.sleecText = 'original';
         sleecPatchState.selectedIssue = {id: 'concerns_1', issue_type: 'concerns', value: 'c1'};
         sleecPatchState.issues = [sleecPatchState.selectedIssue];
         renderStakeholderDecision = renderIssueRunOutput = renderVerificationSummary = renderIssues =
             renderIssueSidebars = refreshPatchWizard = goToPatchStep = () => {};`);
    return {run, element};
}

const confirmed = {patch_id:'p1', operation:'deadline_refinement', source:'deterministic', verified:true,
    formally_verified:true, candidate_status:'formally_verified', proposed_rule:'R1 when Start then Act'};

test('automatic verified candidates remain selectable and agree with run count', async () => {
    const h = setup({verified_patches:[confirmed], deterministic_candidates:[confirmed],
        log:{verified_patch_count:1,successful:true}});
    await h.run('generateVerifiedPatches()');
    assert.equal(h.run('sleecPatchState.verifiedPatches.length'), 1);
    assert.equal(h.run('patchIsVerified(sleecPatchState.verifiedPatches[0])'), true);
    assert.match(h.element('patchOutput').innerHTML, /Formally verified/);
    assert.match(h.element('deterministicOutput').innerHTML, /formally verified/);
});

test('failed repair renders no verified patch with its reason and zero count', async () => {
    const rejected = {...confirmed, verified:false, formally_verified:false, candidate_status:'rejected',
        failure_reason:'The selected issue remains in the patched specification.', verification_cache_hit:true};
    const h = setup({verified_patches:[], failed_patches:[rejected], deterministic_candidates:[rejected],
        log:{verified_patch_count:0,failed_patch_count:1,successful:false}});
    await h.run('generateVerifiedPatches()');
    assert.equal(h.run('sleecPatchState.verifiedPatches.length'), 0);
    assert.match(h.element('patchOutput').innerHTML, /No verified patch found/);
    assert.match(h.element('deterministicOutput').innerHTML, /selected issue remains/);
    assert.match(h.element('deterministicOutput').innerHTML, /reused completed analysis/);
    assert.equal(h.run('escapeHtml(0)'), '0');
});

test('syntax-only manual success must not be shown as formal verification', async () => {
    const h = setup({valid:true});
    const result = await h.run("verifySleecTextForProceed('unchanged', 'manualVerificationOutput')");
    assert.equal(result.valid, false);
    assert.match(h.element('manualVerificationOutput').innerHTML, /Not verified/);
});

test('manual success requires both selected issue fixed and regression passed', async () => {
    for (const [fixed, regression, expected] of [[true,true,true],[false,true,false],[true,false,false]]) {
        const h = setup({valid:true,regression_report:{selected_issue_fixed:fixed,regression_passed:regression}});
        const result = await h.run("verifySleecTextForProceed('changed', 'manualVerificationOutput')");
        assert.equal(result.valid, expected);
        assert.match(h.element('manualVerificationOutput').innerHTML, expected ? /Formally verified/ : /Not verified/);
    }
});
