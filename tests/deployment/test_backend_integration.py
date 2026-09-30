"""Offline integration checks for the empowered backend and preserved live UI.

Run: venv/bin/python -m unittest discover -s tests/deployment -v
Uses a temporary database/scratch directory and blocks external HTTP requests.
"""
import contextlib
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / 'SLEECpatch/app'), str(ROOT)]
from services.deployment_frontend_compat import generation_payload, report_payload


def spec(seconds=300):
    return f'''def_start
event Start
event Act
measure urgent:boolean
def_end
rule_start
R1 when Start then Act within {seconds} seconds
rule_end
concern_start
c1 when Start and {{urgent}} then not Act within 120 seconds
concern_end
'''


class ImportProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((ROOT / 'reviews/deployment-backend-import.json').read_text())

    def test_requested_backend_and_dependencies_are_exact_source_copies(self):
        self.assertEqual(len(self.manifest['requested_backend_files']), 11)
        for group in ('requested_backend_files', 'required_dependencies'):
            for name, expected in self.manifest[group].items():
                raw = (ROOT / name).read_bytes()
                self.assertEqual(hashlib.sha256(raw).hexdigest(), expected, name)
                compile(raw, name, 'exec')

    def test_every_preserved_frontend_file_is_unchanged(self):
        expected = self.manifest['frontend_sha256']
        actual = {str(p.relative_to(ROOT)) for folder in ('static', 'templates')
                  for p in (ROOT / 'SLEECpatch/app' / folder).rglob('*') if p.is_file()}
        self.assertEqual(actual, set(expected))
        for name, sha in expected.items():
            self.assertEqual(hashlib.sha256((ROOT / name).read_bytes()).hexdigest(), sha, name)
        self.assertTrue(all(asset['matches_local'] for asset in self.manifest['live_assets']))

    def test_archived_variants_are_absent_from_deployment_tree(self):
        for name in self.manifest['excluded_backup_files']:
            self.assertFalse((ROOT / name).exists(), name)

    def test_status_aliases_do_not_change_or_promote_backend_verdicts(self):
        payload = {'verified_patches': [
            {'patch_id': 'p1', 'verified': True, 'source': 'deterministic'},
            {'patch_id': 'p2', 'verified': False, 'source': 'llm'},
            {'patch_id': 'p3', 'verified': True, 'formally_verified': False}],
            'failed_patches': [{'patch_id': 'p4', 'verified': False, 'failure_reason': 'target remains'}]}
        original = json.dumps(payload, sort_keys=True)
        result = generation_payload(payload)
        self.assertEqual([p['formally_verified'] for p in result['verified_patches']], [True, False, False])
        self.assertEqual(result['failed_patches'][0]['candidate_status'], 'rejected')
        self.assertEqual(json.dumps(payload, sort_keys=True), original)


class DeploymentRoutesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.stack = contextlib.ExitStack()
        cls.scratch = cls.stack.enter_context(tempfile.TemporaryDirectory(prefix='sleec-deployment-test-'))
        cls.previous = Path.cwd()
        os.chdir(cls.scratch)
        cls.stack.callback(os.chdir, cls.previous)
        cls.stack.enter_context(patch.dict(os.environ, {
            'OPENAI_API_KEY': 'offline-test-key', 'DATABASE_URL': '',
            'SLEEC_REQUIRE_DATABASE_URL': '0', 'SECRET_KEY': 'offline-test-secret',
        }))
        # Prevent app.py from loading real credentials, including a remote DB.
        cls.stack.enter_context(patch('dotenv.load_dotenv', return_value=False))
        cls.stack.enter_context(patch('httpx.Client.send', side_effect=AssertionError('External HTTP is disabled in deployment tests')))
        cls.persistence = importlib.import_module('services.sleec_patch_evaluation_store')
        cls.stack.enter_context(patch.object(cls.persistence, 'DATABASE_URL', ''))
        cls.stack.enter_context(patch.object(cls.persistence, 'REQUIRE_DATABASE_URL', False))
        cls.stack.enter_context(patch.object(cls.persistence, 'DB_PATH', str(Path(cls.scratch) / 'boot.sqlite')))
        try:
            cls.entry = importlib.import_module('deployment_app')
            cls.backend = cls.entry.backend
            cls.app = cls.entry.app
            cls.app.config.update(TESTING=True)
        except Exception:
            cls.stack.close()
            raise

    @classmethod
    def tearDownClass(cls):
        cls.stack.close()

    def setUp(self):
        self.capture = contextlib.redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.addCleanup(self.capture.__exit__, None, None, None)
        database = str(Path(self.scratch) / (self._testMethodName + '.sqlite'))
        p = patch.object(self.persistence, 'DB_PATH', database)
        p.start(); self.addCleanup(p.stop)
        self.engine = self.backend.SLEECPatchWorkbenchEngine()
        self.reviews = self.backend.PhilosopherReviewStore()
        for attr, value in [('sleec_patch_engine', self.engine), ('philosopher_review_store', self.reviews)]:
            p = patch.object(self.backend, attr, value)
            p.start(); self.addCleanup(p.stop)
        self.client = self.app.test_client()

    def diagnose(self, text):
        response = self.client.post('/api/sleec-patch/diagnose', json={'sleec_text': text})
        self.assertEqual(response.status_code, 200, response.get_data(as_text=True)[:500])
        self.assertEqual(response.json['status'], 'OK')
        return response.json

    def test_live_templates_and_assets_render_with_imported_app(self):
        self.assertEqual(self.client.get('/').status_code, 302)
        for url in ('/sleec-patch-workbench', '/sleec-patch-report', '/philosopher-review'):
            response = self.client.get(url)
            self.assertEqual(response.status_code, 200, url)
            self.assertIn(b'sleec_shell.css', response.data)
        manifest = json.loads((ROOT / 'reviews/deployment-backend-import.json').read_text())
        for asset in manifest['live_assets']:
            with self.client.get(asset['url']) as response:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(hashlib.sha256(response.data).hexdigest(), asset['sha256'])

    def test_load_use_case_preserves_original_source(self):
        response = self.client.post('/api/sleec-patch/load-usecase', json={'use_case': 'DAISY'})
        self.assertEqual(response.status_code, 200)
        with open(self.backend.SLEEC_FILES['DAISY'], encoding='utf-8-sig', newline='') as source:
            self.assertEqual(response.json['sleec_text'], source.read())

    def test_repeated_diagnosis_survives_a_different_input(self):
        first = self.diagnose(spec())
        middle = self.diagnose(spec(60))
        again = self.diagnose(spec())
        self.assertTrue(any(i['issue_type'] == 'concerns' for i in first['issues']))
        self.assertFalse(any(i['issue_type'] == 'concerns' for i in middle['issues']))
        self.assertEqual(first['issues'], again['issues'])

    def test_manual_editor_uses_imported_target_and_regression_checks(self):
        original = spec()
        issue = next(i for i in self.diagnose(original)['issues'] if i['issue_type'] == 'concerns')
        for changed, expected in [(original, False), (spec(60), True), ('invalid specification', False)]:
            response = self.client.post('/api/sleec-patch/verify-edited-sleec', json={
                'original_sleec': original, 'sleec_text': changed, 'issue': issue})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json['valid'], expected, response.json)
            if expected:
                self.assertTrue(response.json['regression_report']['selected_issue_fixed'])
                self.assertEqual(response.json['semantic_review_status'], 'pending')

    def test_manual_editor_rejects_issue_from_another_diagnosis(self):
        response = self.client.post('/api/sleec-patch/verify-edited-sleec', json={
            'original_sleec': spec(), 'sleec_text': spec(60),
            'issue': {'issue_type': 'concerns', 'value': 'another concern'}})
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json['valid'])

    def test_deterministic_pipeline_output_can_be_selected_by_live_frontend(self):
        original = spec().split('concern_start')[0].replace('rule_end', 'R2 when Start then Act within 300 seconds\nrule_end')
        issue = next(i for i in self.diagnose(original)['issues'] if i['issue_type'] == 'redundancies')
        with patch.object(self.engine.gpt_patch_engine, 'generate_all_patches', return_value=[]), \
             patch.object(self.engine.gpt_patch_engine, 'assess_patch_quality', return_value={}):
            response = self.client.post('/api/sleec-patch/generate-verified', json={
                'use_case': 'OfflineTest', 'sleec_text': original, 'issue': issue, 'max_attempts': 1})
        self.assertEqual(response.status_code, 200, response.json)
        self.assertTrue(response.json['verified_patches'], response.json.get('log'))
        for candidate in response.json['verified_patches']:
            self.assertIs(candidate['verified'], True)
            self.assertIs(candidate['formally_verified'], True)
            self.assertTrue(candidate['patched_sleec'])
            self.assertEqual(candidate['candidate_status'], 'formally_verified')
        self.assertTrue(self.engine.store.all_results())

    def save_report_run(self, case, run, count=9, duration=10):
        structured = {kind: [] for kind in ['concerns', 'conflicts', 'purpose_blocking', 'redundancies', 'situational_conflicts']}
        structured['concerns'] = [f'c{i}' for i in range(count)]
        self.engine.store.save_pipeline_run({'run_id': run, 'use_case': case,
            'original_issue_count': count, 'original_structured': structured,
            'attempts': 1, 'total_time_seconds': duration, 'successful': True})

    def test_llm_fixture_uses_source_verification_and_remains_pending_review(self):
        original = spec()
        issue = next(i for i in self.diagnose(original)['issues'] if i['issue_type'] == 'concerns')
        proposal = {'operation': 'concern_new_rule_generation', 'source': 'llm',
            'target_rule_id': 'R2', 'original_rule': '',
            'proposed_rule': 'R2 when Start and {urgent} then Act within 120 seconds',
            'natural_language_explanation': 'Offline fixture for the response contract, not a live LLM quality result.'}
        with patch.object(self.engine.gpt_patch_engine, 'generate_all_patches', return_value=[proposal]) as generate, \
             patch.object(self.engine.gpt_patch_engine, 'assess_patch_quality', return_value={}):
            response = self.client.post('/api/sleec-patch/generate-verified', json={
                'use_case': 'OfflineTest', 'sleec_text': original, 'issue': issue, 'max_attempts': 1})
        self.assertEqual(response.status_code, 200, response.json)
        generate.assert_called_once()
        semantic = [p for p in response.json['verified_patches'] if p['source'] == 'llm']
        self.assertTrue(semantic, response.json.get('failed_patches'))
        self.assertTrue(semantic[0]['formally_verified'])
        self.assertEqual(semantic[0]['semantic_review_status'], 'pending')

    def test_current_report_contract_keeps_diagnosis_and_run_counts(self):
        self.save_report_run('DAISY', 'first', duration=10)
        self.save_report_run('DAISY', 'second', duration=30)
        self.save_report_run('ALMI', 'other', count=2)
        for _ in range(3):
            self.engine.store.save_result({'use_case': 'DAISY', 'verified': True, 'source': 'llm', 'patched_sleec': 'preview'})
        self.engine.store.save_result({'use_case': 'ALMI', 'verified': True, 'source': 'llm', 'philosopher_decision': 'Accepted'})
        response = self.client.get('/api/sleec-patch/report-data?use_case=DAISY&include_patched_sleec=0')
        self.assertEqual(response.status_code, 200)
        data = response.json
        self.assertEqual(data['report_metrics']['total_patch_rows'], 3)
        self.assertEqual(data['report_metrics']['repair_run_count'], 2)
        self.assertEqual(data['report_metrics']['avg_run_time_seconds'], 20)
        self.assertEqual([row['issue_count'] for row in data['recorded_diagnoses']], [9, 9])
        self.assertEqual(data['philosopher_review_metrics']['overall']['accepted'], 0)
        self.assertEqual(response.headers['Cache-Control'], 'no-store')
        self.assertTrue(all('patched_sleec' not in row for row in data['evaluation_details']))

    def test_unsuccessful_run_is_visible_without_saved_patches(self):
        self.save_report_run('DAISY', 'no-patch')
        result = self.client.get('/api/sleec-patch/report-data?use_case=DAISY').json
        self.assertEqual(result['report_metrics']['total_patch_rows'], 0)
        self.assertEqual(result['evaluation_summary'][0]['repair_run_count'], 1)

    def test_expert_review_round_trip_uses_imported_store(self):
        self.engine.store.save_result({'use_case': 'DAISY', 'patch_id': 'p1', 'source': 'llm', 'verified': True,
            'requires_social_scientist_review': True, 'proposed_rule': 'R1 when Start then Act'})
        queue = self.client.post('/api/sleec-patch/philosopher-review-queue', json={'use_case': 'DAISY'}).json
        self.assertEqual(len(queue['patches']), 1)
        candidate = queue['patches'][0]
        result = self.client.post('/api/sleec-patch/philosopher-review-decision', json={
            **candidate, 'decision': 'Accepted', 'reviewer': 'Offline reviewer', 'comments': 'Local integration test'})
        self.assertEqual(result.status_code, 200)
        self.assertEqual(self.engine.store.all_results()[0]['philosopher_decision'], 'Accepted')

    def test_json_export_has_same_contract_as_report_page(self):
        self.save_report_run('DAISY', 'export')
        response = self.client.get('/api/sleec-patch/download-report-json?use_case=DAISY')
        self.assertEqual(response.status_code, 200)
        self.assertIn('attachment', response.headers['Content-Disposition'])
        self.assertEqual(response.json['report_metrics']['repair_run_count'], 1)
        self.assertEqual(response.json['recorded_diagnoses'][0]['issue_count'], 9)


if __name__ == '__main__':
    unittest.main()
