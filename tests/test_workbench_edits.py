"""The restored edit screen must use the current formal repair gates."""
import ast
from pathlib import Path
import unittest
from unittest.mock import patch
from flask import Flask, jsonify, request
import test_sleec_verification as fixtures


class WorkbenchEditTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.VerificationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.VerificationTests.tearDownClass.__func__)
    setUp = fixtures.VerificationTests.setUp
    tearDown = fixtures.VerificationTests.tearDown

    def issue(self, text):
        return self.engine.diagnose(text)['issues'][0]

    def test_real_edit_fixes_target_without_changing_concern(self):
        original = fixtures.specification()
        result = self.engine.verify_edited_sleec(original, fixtures.specification(60), self.issue(original))
        self.assertTrue(result['valid'], result)
        self.assertTrue(result['regression_report']['selected_issue_fixed'])
        self.assertEqual(result['semantic_review_status'], 'pending')
        self.engine.gpt_patch_engine.assert_not_called()

    def test_syntax_valid_text_with_remaining_target_is_not_verified(self):
        original = fixtures.specification()
        result = self.engine.verify_edited_sleec(original, fixtures.specification(250), self.issue(original))
        self.assertFalse(result['valid'])
        self.assertFalse(result['regression_report']['selected_issue_fixed'])

    def test_deleting_concern_to_hide_issue_is_rejected(self):
        original = fixtures.specification()
        result = self.engine.verify_edited_sleec(original, fixtures.specification(60).split('concern_start')[0], self.issue(original))
        self.assertFalse(result['valid'])

    def test_selected_target_and_valid_syntax_are_required(self):
        original = fixtures.specification()
        for edited, issue in [('invalid text', self.issue(original)),
                              (fixtures.specification(60), {'issue_type': 'concerns', 'value': 'stale issue'})]:
            self.assertFalse(self.engine.verify_edited_sleec(original, edited, issue)['valid'])

    def test_new_conflict_is_rejected_even_when_target_disappears(self):
        original = fixtures.specification()
        edited = fixtures.specification(60).replace('rule_end', 'R2 when Start then not Act within 120 seconds\nrule_end')
        self.assertFalse(self.engine.verify_edited_sleec(original, edited, self.issue(original))['valid'])

    def test_detector_failure_is_not_a_successful_edit(self):
        original = fixtures.specification()
        issue = self.issue(original)
        baseline = self.engine.run_detector_cached(original)
        with patch.object(self.engine, 'run_detector_cached', side_effect=[baseline, fixtures.failed_analysis()]):
            result = self.engine.verify_edited_sleec(original, fixtures.specification(60), issue)
        self.assertFalse(result['valid'])

    def test_route_rejects_missing_context_and_returns_real_gate_result(self):
        source = ast.parse((fixtures.ROOT / 'SLEECpatch/app/app.py').read_text())
        route = next(n for n in source.body if isinstance(n, ast.FunctionDef) and n.name == 'api_sleec_patch_verify_edited_sleec')
        app = Flask('edit-test')
        exec(compile(ast.Module(body=[route], type_ignores=[]), 'edit-route', 'exec'),
             {'app': app, 'request': request, 'jsonify': jsonify, 'sleec_patch_engine': self.engine})
        client = app.test_client()
        url = '/api/sleec-patch/verify-edited-sleec'
        self.assertEqual(client.post(url, json={'sleec_text': fixtures.specification()}).status_code, 400)
        original = fixtures.specification()
        result = client.post(url, json={'original_sleec': original, 'sleec_text': original, 'issue': self.issue(original)})
        self.assertEqual(result.status_code, 200)
        self.assertFalse(result.json['valid'])


if __name__ == '__main__':
    unittest.main()
