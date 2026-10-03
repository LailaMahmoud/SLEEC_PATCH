"""Status must agree across raw app.py, the engine, persistence and the UI.

Uses temporary SQLite/solver files, a real detector and no external HTTP.
"""
import contextlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'SLEECpatch/app'), str(ROOT)]
from test_backend_integration import spec


class VerificationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        scratch = cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='sleec-status-test-'))
        cls.previous = Path.cwd()
        os.chdir(scratch)
        cls.stack.callback(os.chdir, cls.previous)
        cls.stack.enter_context(patch.dict(os.environ, {
            'OPENAI_API_KEY': 'offline-test-key', 'DATABASE_URL': '',
            'SLEEC_REQUIRE_DATABASE_URL': '0', 'SECRET_KEY': 'offline-test-secret',
        }))
        cls.stack.enter_context(patch('dotenv.load_dotenv', return_value=False))
        cls.stack.enter_context(patch('httpx.Client.send', side_effect=AssertionError('External HTTP disabled')))
        cls.store_module = importlib.import_module('services.sleec_patch_evaluation_store')
        cls.stack.enter_context(patch.object(cls.store_module, 'DATABASE_URL', ''))
        cls.stack.enter_context(patch.object(cls.store_module, 'REQUIRE_DATABASE_URL', False))
        cls.stack.enter_context(patch.object(cls.store_module, 'DB_PATH', str(Path(scratch) / 'boot.sqlite')))
        cls.backend = importlib.import_module('app')
        cls.backend.app.config.update(TESTING=True)
        cls.scratch = Path(scratch)

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def setUp(self):
        stack = self.enterContext(contextlib.ExitStack())
        stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        stack.enter_context(patch.object(self.store_module, 'DB_PATH', str(self.scratch / (self._testMethodName + '.sqlite'))))
        self.engine = self.backend.SLEECPatchWorkbenchEngine()
        stack.enter_context(patch.object(self.backend, 'sleec_patch_engine', self.engine))
        # Test the raw app routes even if another suite imported deployment_app.
        stack.enter_context(patch.object(self.backend.app, 'after_request_funcs', {}))
        self.client = self.backend.app.test_client()

    def issue(self, original=None):
        data = self.client.post('/api/sleec-patch/diagnose', json={'sleec_text': original or spec()}).json
        return next(i for i in data['issues'] if i['issue_type'] == 'concerns')

    def generate(self, candidate=None):
        issue = self.issue()
        plan = {'deterministic': [], 'llm': [], 'applicability': {}, 'diagnosis': {}}
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(self.engine.gpt_patch_engine, 'generate_all_patches', return_value=[]))
            if candidate:
                # The generator is stubbed; verification and database are real.
                stack.enter_context(patch.object(self.engine.operator_selector, 'select', return_value=plan))
                stack.enter_context(patch.object(self.engine.deterministic_engine, 'generate', return_value=[candidate]))
            response = self.client.post('/api/sleec-patch/generate-verified', json={
                'use_case': 'OfflineTest', 'sleec_text': spec(), 'issue': issue, 'max_attempts': 1})
        self.assertEqual(response.status_code, 200, response.json)
        return response.json

    def candidate(self, seconds=240, **overrides):
        return {'patch_id': 'failed_bound', 'source': 'deterministic', 'operation': 'deadline_refinement',
                'target_rule_id': 'R1', 'original_rule': 'R1 when Start then Act within 300 seconds',
                'proposed_rule': f'R1 when Start then Act within {seconds} seconds', **overrides}

    def test_raw_app_success_agrees_with_frontend_and_database(self):
        data = self.generate()
        self.assertTrue(data['verified_patches'])
        for p in data['verified_patches']:
            self.assertIs(p['verified'], True)
            self.assertIs(p.get('formally_verified'), True)
            self.assertEqual(p.get('candidate_status'), 'formally_verified')
        self.assertEqual(len(self.engine.store.all_results()), len(data['verified_patches']))
        self.assertEqual(data['log']['verified_patch_count'], len(data['verified_patches']))
        self.assertTrue(all(row['run_id'] == data['log']['run_id'] for row in self.engine.store.all_results()))
        with self.engine.store.connect() as conn:
            states = conn.execute('SELECT candidate_status FROM sleec_patch_candidates').fetchall()
        self.assertTrue(states)
        self.assertTrue(all(row['candidate_status'] == 'formally_verified' for row in states))

    def test_separate_runs_keep_separate_verified_artifacts(self):
        first = self.generate()
        filename = Path(first['generated_file']['path'])
        saved_text = filename.read_text()
        second = self.generate()
        self.assertNotEqual(first['generated_file']['path'], second['generated_file']['path'])
        self.assertEqual(filename.read_text(), saved_text)
        self.assertIn(first['log']['run_id'], filename.name)

    def test_invalid_llm_proposal_keeps_its_identity_and_does_not_hide_valid_proposal(self):
        original = spec().replace('event Start', 'event Backup\nevent Start').replace('R1 when Start', 'R1 when Backup')
        issue = self.issue(original)
        valid = {'operation': 'new_rule_generation', 'target_rule_id': None, 'source_requirement_id': 'c1',
            'change': {'rule_id': 'R2', 'trigger_event': 'Start', 'condition': '{urgent}',
                       'response_event': 'Act', 'negated': False, 'deadline': {'kind': 'source'}},
            'natural_language_explanation': 'Require the response within the selected concern deadline.'}
        invalid = {'operation': 'new_rule_generation', 'proposed_rule': 'unstructured arbitrary rewrite'}
        with patch.object(self.engine.gpt_patch_engine, 'generate_all_patches', return_value=[invalid, valid]):
            response = self.client.post('/api/sleec-patch/generate-verified', json={
                'use_case': 'OfflineTest', 'sleec_text': original, 'issue': issue, 'max_attempts': 1})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertEqual([p['patch_id'] for p in response.json['verified_patches']], ['g2'])
        self.assertEqual([p['patch_id'] for p in response.json['failed_patches']], ['g1'])
        self.assertEqual(len(self.engine.store.all_results()), 1)
        with self.engine.store.connect() as conn:
            rows = conn.execute('SELECT patch_id, candidate_status FROM sleec_patch_candidates ORDER BY patch_id').fetchall()
        self.assertEqual([(r['patch_id'], r['candidate_status']) for r in rows],
                         [('g1', 'rejected'), ('g2', 'formally_verified')])

    def test_failed_target_returns_no_verified_patch_and_saves_no_success(self):
        data = self.generate(self.candidate())
        self.assertEqual(data['verified_patches'], [])
        self.assertFalse(data['log']['successful'])
        self.assertEqual(data['log']['verified_patch_count'], 0)
        self.assertEqual(self.engine.store.all_results(), [])
        for p in data['failed_patches'] + data['deterministic_candidates']:
            self.assertIs(p.get('formally_verified'), False)
            self.assertEqual(p.get('candidate_status'), 'rejected')
            self.assertIn('selected issue', p.get('failure_reason', '').lower())
        with self.engine.store.connect() as conn:
            row = conn.execute('SELECT verified, target_fixed, patch_json FROM sleec_patch_verifications').fetchone()
        self.assertEqual(row['verified'], 0)
        self.assertEqual(row['target_fixed'], 0)
        self.assertFalse(json.loads(row['patch_json'])['formally_verified'])

    def test_stale_true_metadata_cannot_promote_failed_candidate(self):
        data = self.generate(self.candidate(verified=True, formally_verified=True, candidate_status='formally_verified'))
        self.assertEqual(data['verified_patches'], [])
        self.assertEqual(self.engine.store.all_results(), [])
        self.assertIs(data['failed_patches'][0].get('formally_verified'), False)

    def test_manual_unchanged_or_renamed_rule_does_not_fix_concern(self):
        issue = self.issue()
        for proposed in (spec(), spec().replace('R1 when', 'R1_15 when'), spec(240)):
            with self.subTest(proposed=proposed):
                data = self.client.post('/api/sleec-patch/verify-edited-sleec', json={
                    'original_sleec': spec(), 'sleec_text': proposed, 'issue': issue}).json
                self.assertIs(data['valid'], False)
                self.assertFalse(data['regression_report']['selected_issue_fixed'])
        fixed = self.client.post('/api/sleec-patch/verify-edited-sleec', json={
            'original_sleec': spec(), 'sleec_text': spec(60), 'issue': issue}).json
        self.assertIs(fixed['valid'], True)
        self.assertTrue(fixed['regression_report']['regression_passed'])
        self.assertEqual(self.engine.store.all_results(), [])

    def test_manual_cannot_delete_requirement_to_pass(self):
        data = self.client.post('/api/sleec-patch/verify-edited-sleec', json={
            'original_sleec': spec(), 'sleec_text': spec().split('concern_start')[0], 'issue': self.issue()}).json
        self.assertIs(data['valid'], False)
        self.assertIn('cannot change', data['failure_reason'])

    def test_manual_cannot_hide_a_conflict_by_renaming_a_rule(self):
        original = spec().replace('rule_end', 'R2 when Start then not Act within 300 seconds\nrule_end')
        diagnosis = self.client.post('/api/sleec-patch/diagnose', json={'sleec_text': original}).json
        issue = next(i for i in diagnosis['issues'] if i['issue_type'] in {'conflicts', 'situational_conflicts'})
        data = self.client.post('/api/sleec-patch/verify-edited-sleec', json={
            'original_sleec': original, 'sleec_text': original.replace('R1 when', 'R1_15 when'),
            'issue': issue}).json
        self.assertIs(data['valid'], False)
        self.assertFalse(data['regression_report']['regression_passed'])

    def test_manual_rejects_regression_and_missing_original_context(self):
        changed = spec(60).replace('rule_end', 'R2 when Start then not Act within 120 seconds\nrule_end')
        data = self.client.post('/api/sleec-patch/verify-edited-sleec', json={
            'original_sleec': spec(), 'sleec_text': changed, 'issue': self.issue()}).json
        self.assertIs(data['valid'], False)
        self.assertFalse(data['regression_report']['regression_passed'])
        missing = self.client.post('/api/sleec-patch/verify-edited-sleec', json={'sleec_text': spec(60)}).json
        self.assertIs(missing['valid'], False)

    def test_incomplete_detector_output_cannot_certify_a_repair(self):
        for result in ({'status': 'ERROR', 'detections': {}, 'structured': {}},
                       {'status': 'OK', 'detections': {}, 'structured': {}}):
            with self.subTest(result=result), patch.object(self.engine, 'run_detector_cached', return_value=result):
                self.assertIs(self.engine.validate_patched_sleec(spec(60))['valid'], False)

    def test_cached_identical_input_reuses_analysis_without_changing_verdict(self):
        with patch.object(self.engine.detector, 'run_text', wraps=self.engine.detector.run_text) as detector:
            first = self.engine.run_detector_cached(spec())
            second = self.engine.run_detector_cached(spec())
            self.assertEqual(first['structured'], second['structured'])
            self.assertEqual(detector.call_count, 1)
            self.assertIs(first.get('cache_hit'), False)
            self.assertIs(second.get('cache_hit'), True)
            self.engine.run_detector_cached(spec(60))
            self.assertEqual(detector.call_count, 2)

    def test_incomplete_analysis_is_retried_instead_of_cached(self):
        with patch.object(self.engine.detector, 'run_text', return_value={
                'status': 'OK', 'detections': {}, 'structured': {}}) as detector:
            for _ in range(2):
                self.assertIs(self.engine.validate_patched_sleec(spec(60))['valid'], False)
            self.assertEqual(detector.call_count, 2)
            self.assertFalse(self.engine.detector_cache)


if __name__ == '__main__':
    unittest.main()
