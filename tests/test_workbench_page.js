// Offline checks for the restored ten-screen workbench's verification and state.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const test = require('node:test');
const vm = require('node:vm');

function setup() {
    const elements = new Map(), pending = [], alerts = [];
    const element = id => {
        if (!elements.has(id)) elements.set(id, {value: '', innerHTML: '', textContent: '', className: '', style: {},
            replaceChildren() {}, append() {}, addEventListener() {},
            classList: {toggle() {}, add() {}, remove() {}}, scrollTop: 0, scrollLeft: 0});
        return elements.get(id);
    };
    const context = vm.createContext({console, alert: message => alerts.push(message),
        document: {getElementById: element, createElement: () => element(Symbol()), addEventListener() {}},
        sessionStorage: {getItem() { return null; }},
        window: {withLoader: fn => fn()}});
    const run = code => vm.runInContext(code, context);
    run(fs.readFileSync(path.join(__dirname, '../SLEECpatch/app/static/js/sleec_patch_workbench.js'), 'utf8'));
    context.request = (url, data) => new Promise(resolve => pending.push({url, data, resolve}));
    run('postJSON = request');
    const state = () => run('sleecPatchState');
    function diagnosed() {
        element('useCase').value = 'DAISY';
        element('sleecInput').value = 'original input\n';
        state().sleecText = element('sleecInput').value;
        state().issues = [{id: 'concerns_1', issue_type: 'concerns', value: 'first'},
                          {id: 'concerns_2', issue_type: 'concerns', value: 'second'}];
        state().selectedIssue = state().issues[0];
        state().rawDiagnosis = {status: 'OK'};
    }
    return {context, run, element, pending, alerts, state, diagnosed};
}

function candidate(extra = {}) {
    return {patch_id: 'p1', verified: true, formally_verified: true, original_rule: 'old',
        proposed_rule: 'new', patched_sleec: 'new specification', source: 'llm', ...extra};
}
function setPatch(h, patch = candidate()) {
    h.state().verifiedPatches = [patch];
    h.state().selectedPatchIndex = 0;
    h.element('stakeholderProposedRule').value = patch.proposed_rule;
    return patch;
}

test('a successful run does not certify an unverified patch', () => {
    const h = setup(); h.diagnosed();
    const p = setPatch(h, candidate({verified: false, formally_verified: false}));
    h.state().log = {successful: true};
    h.state().resolutionChoice = {kind: 'patch', patchIndex: 0, sleecText: p.patched_sleec};
    h.run('persistCurrentIssueUiState()');
    assert.equal(h.run('hasVerifiedCurrentResolution()'), false);
    h.run('integrateSelectedPatchAndProceed()');
    assert.equal(h.alerts.length, 1);
});

test('selected repair preserves the original input for the next independent issue', async () => {
    const h = setup(); h.diagnosed(); setPatch(h);
    h.run('integrateSelectedPatchAndProceed()');
    assert.equal(h.run('hasVerifiedCurrentResolution()'), true);
    h.run('proceedToNextSequentialIssue()');
    assert.equal(h.state().selectedIssue.id, 'concerns_2');
    assert.equal(h.state().sleecText, 'original input\n');
    assert.equal(h.element('sleecInput').value, 'original input\n');
    const promise = h.run('generateVerifiedPatches()');
    assert.equal(h.pending[0].data.sleec_text, 'original input\n');
    h.pending[0].resolve({}); await promise;
});

test('unsaved patch edits and edits after verification cannot reuse approval', async () => {
    const h = setup(); h.diagnosed(); const patch = setPatch(h);
    h.element('stakeholderProposedRule').value = 'changed';
    h.run('onPatchEdit(); integrateSelectedPatchAndProceed()');
    assert.equal(h.state().resolutionChoice, null);
    const check = h.run('verifySelectedPatchEdit()');
    assert.equal(h.pending[0].data.original_sleec, 'original input\n');
    assert.equal(h.pending[0].data.sleec_text, 'changed specification');
    h.pending[0].resolve({valid: true, regression_report: {selected_issue_fixed: true, regression_passed: true}}); await check;
    assert.equal(patch.edit_verified, true);
    h.element('stakeholderProposedRule').value = 'changed again';
    h.run('onPatchEdit(); integrateSelectedPatchAndProceed()');
    assert.equal(patch.edit_verified, false);
    assert.equal(h.state().resolutionChoice, null);
});

test('a manual verification response for older text is ignored', async () => {
    const h = setup(); h.diagnosed();
    h.element('manualSleecEditor').value = 'edited specification\n';
    const check = h.run('verifyManualResolution()');
    h.element('manualSleecEditor').value = 'changed while waiting\n';
    h.run('onManualEdit()');
    h.pending[0].resolve({valid: true}); await check;
    assert.equal(h.state().manualVerification, null);
    h.run('integrateManualResolutionAndProceed()');
    assert.equal(h.state().resolutionChoice, null);
});

test('case switches clear prior diagnoses and ignore an older case response', async () => {
    const h = setup(); h.diagnosed();
    h.state().userProfession = 'Researcher';
    h.state().issueResults.old = {log: {successful: true}};
    const first = h.run('loadSelectedUseCase()');
    h.element('useCase').value = 'ALMI';
    const second = h.run('loadSelectedUseCase()');
    assert.equal(h.state().issues.length, 0);
    assert.equal(Object.keys(h.state().issueResults).length, 0);
    h.pending[1].resolve({sleec_text: 'fresh ALMI'}); await second;
    h.pending[0].resolve({sleec_text: 'old DAISY'}); await first;
    assert.equal(h.element('sleecInput').value, 'fresh ALMI');
    assert.equal(h.state().sleecText, 'fresh ALMI');
    assert.equal(h.state().userProfession, 'Researcher');
});

test('late diagnosis and generation results do not repopulate a reset workbench', async () => {
    for (const call of ['diagnoseWFIs()', 'generateVerifiedPatches()']) {
        const h = setup(); h.diagnosed();
        const job = h.run(call);
        h.run('resetPatchWorkbench()');
        h.pending[0].resolve({issues: [{id: 'stale'}], verified_patches: [candidate()]});
        await job;
        assert.equal(h.state().issues.length, 0);
        assert.equal(h.state().verifiedPatches.length, 0);
        assert.equal(h.state().selectedIssue, null);
    }
});

test('changed input requires diagnosis again, and full raw trace evidence is shown', () => {
    const h = setup(); h.diagnosed();
    h.state().selectedIssue.diagnosis = {source_text: 'source concern',
        raw_report: 'at time 12: Measure(risk=high)\nat time 12: Start()',
        rule_references: [{id: 'R7', text: 'R7 when Start then Act'}]};
    h.run('renderIssues()');
    assert.match(h.element('issuesOutput').innerHTML, /Measure\(risk=high\)/);
    assert.match(h.element('issuesOutput').innerHTML.replace(/<[^>]+>/g, ''), /R7 when Start then Act/);
    h.element('sleecInput').value = 'different input';
    h.run('onSpecificationInput()');
    assert.equal(h.state().selectedIssue, null);
    assert.equal(h.run('canAdvancePatchWizard(3)'), false);
});

test('leaving an issue unresolved does not label it as fixed', () => {
    const h = setup(); h.diagnosed();
    h.run('leaveIssueUnresolved()');
    assert.equal(h.state().selectedIssue.id, 'concerns_2');
    assert.equal(h.run('issueRunStatus(sleecPatchState.issues[0])'), 'not run');
});

test('a failed detector is displayed as an error and cannot unlock the diagnosis step', async () => {
    const h = setup(); h.diagnosed();
    const job = h.run('diagnoseWFIs()');
    h.pending[0].resolve({status: 'ERROR', error: 'Rule IDs must be unique; repeated: R3', issues: []});
    await job;
    assert.equal(h.state().rawDiagnosis, null);
    assert.equal(h.run('canAdvancePatchWizard(3)'), false);
    assert.match(h.element('issuesOutput').innerHTML, /Diagnosis did not complete/);
    assert.match(h.element('issuesOutput').innerHTML, /repeated: R3/);
});
