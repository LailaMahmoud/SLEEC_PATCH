"""Regressions for incomplete conflict repairs and case-study inputs."""
import copy
import unittest

import test_sleec_verification as fixtures
from services.evidence_repair import generate_repairs
from services.paper_repairs import plan
from services.rule_model import apply_rule_patch, parse_sleec_ast, rules_from_text


MODEL = """def_start
event Prepare
event Deploy
measure indigenous:boolean
measure treaty:boolean
measure private:boolean
measure damaged:boolean
def_end
rule_start
R4 when Prepare and {indigenous} then not Deploy
   unless {treaty} then Deploy
R7 when Prepare and {private} then not Deploy
R13 when Prepare and {damaged} then not Deploy
rule_end
"""


class ConflictRepairCases(unittest.TestCase):
    setUpClass = classmethod(fixtures.VerificationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.VerificationTests.tearDownClass.__func__)
    setUp = fixtures.VerificationTests.setUp
    tearDown = fixtures.VerificationTests.tearDown

    def test_combined_candidates_resolve_opponent_missing_from_single_proof(self):
        diagnosis = self.engine.diagnose(MODEL)
        issue = next(i for i in diagnosis['issues'] if i['diagnosis']['source_id'] == 'R4')
        # A minimal unsat core need mention only one of two competitors.
        evidence = {**issue['diagnosis'], 'affected_rule_ids': ['R4', 'R13']}
        original_evidence = copy.deepcopy(evidence)
        candidates = generate_repairs(MODEL, 'situational_conflicts', evidence,
                                      ['trigger_refinement', 'defeater_introduction'])
        combined = [p for p in candidates if p['target_rule_id'] == 'R4']
        self.assertEqual(len(combined), 2)
        for candidate in combined:
            self.assertIn('{private}', candidate['proposed_rule'])
            self.assertIn('{damaged}', candidate['proposed_rule'])
            self.assertEqual(candidate['diagnosis'], original_evidence)
            result = self.engine.verify_candidate_patch(MODEL, issue, candidate)
            self.assertTrue(result['verified'], candidate.get('failure_reason'))
            self.assertEqual(result['new_analysis']['structured']['situational_conflicts'], [])
        nested = next(p for p in combined if p['operation'] == 'defeater_introduction')
        rule = parse_sleec_ast(apply_rule_patch(MODEL, nested)).ruleBlock.rules[0]
        self.assertEqual(len(rule.response.defeater), 1)
        self.assertEqual(len(rule.response.defeater[0].response.defeater), 1)

    def test_competing_exception_priority_is_included(self):
        text = MODEL.replace('measure damaged:boolean', 'measure damaged:boolean\nmeasure exemption:boolean')
        text = text.replace('R7 when Prepare and {private} then not Deploy',
                            'R7 when Prepare and {private} then not Deploy unless {exemption}')
        candidates = generate_repairs(text, 'situational_conflicts',
            {'source_id': 'R4', 'affected_rule_ids': ['R4', 'R13']}, ['defeater_introduction'])
        candidate = next(p for p in candidates if p['target_rule_id'] == 'R4')
        self.assertIn('({private} and (not {exemption}))', candidate['proposed_rule'])

    def test_almi_does_not_copy_exception_state_between_different_trigger_times(self):
        text = (fixtures.ROOT / 'SLEECpatch/app/sleec_usecases/ALMI.sleec').read_text()
        result = plan(text, 'situational_conflicts', '', diagnosis={
            'source_id': 'R3', 'affected_rule_ids': ['R3', 'R21']})
        self.assertEqual(result['candidates'], [])

    def test_copying_a_later_exception_state_does_not_resolve_temporal_conflict(self):
        text = '''def_start
event Smoke
event Fall
event RequestHelp
event Vent
measure assent:boolean
measure alarmDisabled:boolean
def_end
rule_start
R3 when Fall then RequestHelp unless (not {assent}) then not RequestHelp
R21 when Smoke then RequestHelp within 5 minutes unless {alarmDisabled} then Vent
rule_end
'''
        diagnosis = self.engine.diagnose(text)
        self.assertEqual(diagnosis['status'], 'OK', diagnosis.get('error'))
        issue = next(i for i in diagnosis['issues']
                     if i['diagnosis']['source_id'] == 'R3')
        candidate = {'operation': 'defeater_introduction', 'target_rule_id': 'R3',
                     'proposed_rule': 'R3 when Fall then RequestHelp unless ((not {assent}) and {alarmDisabled}) then not RequestHelp'}
        result = self.engine.verify_candidate_patch(text, issue, candidate)
        self.assertFalse(result['verified'])
        self.assertFalse(result['target_fixed'])

    def test_timed_opponent_is_not_treated_as_an_immediate_context(self):
        text = MODEL.replace('R13 when Prepare and {damaged} then not Deploy',
                             'R13 when Prepare and {damaged} then not Deploy within 1 minutes')
        candidates = generate_repairs(text, 'situational_conflicts',
            {'source_id': 'R4', 'affected_rule_ids': ['R4', 'R13']}, ['defeater_introduction'])
        self.assertFalse(any('{private}' in p['proposed_rule'] for p in candidates))

    def test_decomposition_does_not_split_an_unchanged_response(self):
        text = MODEL + '''concern_start
c1 when Prepare and {private} then Deploy
concern_end
'''
        candidates = generate_repairs(text, 'concerns', {'source_id': 'c1'},
                                      ['trigger_strengthening', 'rule_decomposition'])
        self.assertTrue(any(p['operation'] == 'trigger_strengthening' for p in candidates))
        self.assertFalse(any(p['operation'] == 'rule_decomposition' for p in candidates))

    def test_dressassist_source_and_excel_have_unique_matching_ids(self):
        root = fixtures.ROOT
        for directory in ['SLEECpatch/app/sleec_usecases', 'sleec/dressingAssist']:
            for name in ['DRESSASSIST.sleec', 'DRESSASSIST-corrected.sleec']:
                rules = rules_from_text((root / directory / name).read_text())
                self.assertIn('Rule20_3', {r['id'] for r in rules})
        excel = self.engine.detector.excel_to_full_sleec(
            root / 'SLEECpatch/app/sleec_usecases/DRESSASSIST.xlsx')
        source = (root / 'SLEECpatch/app/sleec_usecases/DRESSASSIST.sleec').read_text()
        self.assertEqual({r['id'] for r in rules_from_text(excel)},
                         {r['id'] for r in rules_from_text(source)})


if __name__ == '__main__':
    unittest.main()
