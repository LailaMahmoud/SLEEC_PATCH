"""Incoming ID allocation and local verification must retain the same contract."""
import copy
import unittest

import test_sleec_verification as fixtures
from services.evidence_repair import target_resolution
from services.patch_verification_bridge import PatchVerificationBridge
from services.rule_model import apply_rule_patch, rules_from_text
from services.semantic_patch_validator import SemanticPatchValidator
from services.structured_semantic_edit import materialize_semantic_edit


MODEL = '''def_start
event Start
event Act
event R2
measure urgent:boolean
measure R3:numeric
measure severity:scale(R4,high)
def_end
rule_start
R1 when Start then Act within 5 minutes
rule_end
concern_start
c1 when Start and {urgent} then not Act within 2 minutes
concern_end
'''


class CoauthorIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.scope = target_resolution(MODEL, 'concerns', {'source_id': 'c1'})['addition_scope']
        self.proposal = {
            'operation': 'new_rule_generation', 'target_rule_id': None,
            'source_requirement_id': 'c1',
            'change': {'rule_id': 'R1', 'trigger_event': 'Start', 'condition': '{urgent}',
                       'response_event': 'Act', 'negated': False, 'deadline': {'kind': 'source'}},
            'natural_language_explanation': 'Require the response within the source deadline.',
        }

    def render(self):
        return materialize_semantic_edit(MODEL, self.proposal, [], self.scope)

    def test_allocated_id_avoids_existing_rules_events_measures_and_scale_labels(self):
        candidate = self.render()
        self.assertEqual(candidate['assigned_rule_id'], 'R5')
        self.assertEqual(candidate['requested_rule_id'], 'R1')
        rules = rules_from_text(apply_rule_patch(MODEL, candidate))
        self.assertEqual([r['id'] for r in rules], ['R1', 'R5'])
        self.assertEqual(rules[0]['raw'], 'R1 when Start then Act within 5 minutes')

    def test_repeat_materialization_keeps_the_proposal_and_allocated_id_stable(self):
        original = copy.deepcopy(self.proposal)
        first, second = self.render(), self.render()
        self.assertEqual(self.proposal, original)
        self.assertEqual(first['change'], original['change'])
        self.assertEqual(first['proposed_rule'], second['proposed_rule'])
        verdict = SemanticPatchValidator().validate(MODEL, {}, first, [], [], [])
        self.assertTrue(verdict['valid'], verdict)

    def test_source_anchor_needs_no_existing_rule_target_and_preserves_timing(self):
        candidate = self.render()
        self.assertEqual(candidate['original_rule'], '')
        self.assertEqual(candidate['proposed_rule'], 'R5 when Start and {urgent} then Act within 2 minutes')

    def test_event_names_are_rejected_in_measure_condition(self):
        self.proposal['change']['condition'] = '(Start and {urgent})'
        with self.assertRaisesRegex(ValueError, 'measure/context'):
            self.render()

    def test_bridge_retains_generated_payload_with_separate_assigned_id(self):
        original = copy.deepcopy(self.proposal)
        result = PatchVerificationBridge().prepare(MODEL, self.proposal, [], self.scope)
        self.assertTrue(result['success'], result['materialization'])
        self.assertEqual(result['generated_candidate'], original)
        self.assertEqual(result['executable_patch']['generated_candidate'], original)
        self.assertEqual(result['executable_patch']['assigned_rule_id'], 'R5')


if __name__ == '__main__':
    unittest.main()
