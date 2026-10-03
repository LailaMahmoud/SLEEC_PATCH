"""Regression tests for analysis isolation and verification failures.

Run: venv/bin/python -m unittest discover -s tests -v
No database or LLM client is created. Solver scratch files live in a temp dir.
"""
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
import copy
import io
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "SLEECpatch/app"), str(ROOT)]

from services.sleec_detection_engine import (
    DETECTOR_ISSUE_TYPES, SLEECDetectionEngine, analysis_failures,
)
from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine
from sleec import sleecParser, SleecNorm, sleec_api
from sleec.analysis_runtime import AnalysisError, reset_analysis_state


def specification(deadline=300, scale="low,high"):
    return f"""def_start
event Start
event Act
measure risk:scale({scale})
def_end
rule_start
R1 when Start then Act within {deadline} seconds
rule_end
concern_start
c1 when Start and ({{risk}} = high) then not Act within 120 seconds
concern_end
"""


def clean_analysis():
    return {
        "status": "OK",
        "detections": {name: {"success": True, "detected": False, "message": "", "findings": [], "count": 0}
                       for name in DETECTOR_ISSUE_TYPES},
        "structured": {kind: [] for kind in DETECTOR_ISSUE_TYPES.values()},
    }


def failed_analysis():
    result = clean_analysis()
    result["status"] = "ERROR"
    result["detections"]["conflict"].update(success=False, detected=None, message="solver failed")
    return result


def workbench():
    engine = SLEECPatchWorkbenchEngine.__new__(SLEECPatchWorkbenchEngine)
    engine.detector = SLEECDetectionEngine()
    engine.detector_cache = OrderedDict()
    engine.detector_cache_lock = threading.RLock()
    engine.detector_cache_max_entries = 64
    engine.gpt_patch_engine = Mock()
    from services.semantic_patch_validator import SemanticPatchValidator
    engine.semantic_validator = SemanticPatchValidator()
    return engine


class VerificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_cwd = os.getcwd()
        cls.scratch = tempfile.TemporaryDirectory(prefix="sleec-verification-tests-")
        os.chdir(cls.scratch.name)

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.previous_cwd)
        cls.scratch.cleanup()

    def setUp(self):
        reset_analysis_state()
        self.capture = redirect_stdout(io.StringIO())
        self.capture.__enter__()
        self.engine = workbench()

    def tearDown(self):
        reset_analysis_state()
        self.capture.__exit__(None, None, None)

    def test_syntax_check_does_not_register_solver_types(self):
        for _ in range(3):
            self.assertTrue(self.engine.check_sleec_syntax(specification())["valid"])
            self.assertEqual(sleecParser.registered_type, set())
            self.assertEqual(sleecParser.scalar_type, {})
        result = self.engine.detector.run_text(specification())
        self.assertFalse(analysis_failures(result))
        self.assertTrue(result["structured"]["concerns"])

    def test_repeated_scale_analyses_keep_the_actual_concern(self):
        for _ in range(3):
            gate = self.engine.validate_patched_sleec(specification())
            self.assertTrue(gate["valid"], gate)
            self.assertTrue(gate["analysis"]["structured"]["concerns"])
            self.engine.detector_cache.clear()

    def test_different_models_do_not_share_scale_state(self):
        for text, concern_expected in [(specification(), True),
                                       (specification(60, "high,low"), False),
                                       (specification(), True)]:
            result = self.engine.detector.run_text(text)
            self.assertFalse(analysis_failures(result), result)
            self.assertEqual(bool(result["structured"]["concerns"]), concern_expected)

    def test_direct_repeated_parsing_rebuilds_local_types_and_constants(self):
        for number, scale in [(300, "low,high"), (60, "high,low"), (0, "low,high")]:
            text = specification(scale=scale).replace("def_end", f"constant Limit = {number}\ndef_end")
            *_, mapping, actions = sleecParser.parse_sleec(text, read_file=False)
            mapping["Measure"](print_only=True)
            self.assertEqual(sleecParser.constants["Limit"], number)
            self.assertEqual(sleecParser.scalar_type["high"], scale.split(",").index("high"))

    def test_parallel_detector_calls_do_not_mix_models(self):
        texts = [specification(), specification(60, "high,low")] * 2
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(self.engine.detector.run_text, texts))
        for result, expected in zip(results, [True, False, True, False]):
            self.assertFalse(analysis_failures(result), result)
            self.assertEqual(bool(result["structured"]["concerns"]), expected)

    def test_solver_exception_is_reported_and_state_recovers(self):
        with patch.object(sleecParser, "check_property_refining", side_effect=RuntimeError("solver crashed")):
            result = self.engine.detector.safe_call("concern", sleec_api.check_concern, specification())
        self.assertFalse(result["success"])
        self.assertIsNone(result["detected"])
        self.assertIn("solver crashed", result["message"])
        self.assertEqual(sleecParser.registered_type, set())
        self.assertEqual(sleecParser.constants, {})
        recovered = self.engine.detector.run_text(specification())
        self.assertFalse(analysis_failures(recovered))
        self.assertTrue(recovered["structured"]["concerns"])

    def test_situational_exception_resets_obligations(self):
        with patch.object(SleecNorm, "check_property_refining", side_effect=RuntimeError("solver crashed")):
            with self.assertRaises(AnalysisError):
                sleec_api.check_situational(specification())
        self.assertEqual(SleecNorm.blocked_actions, {})
        self.assertEqual(SleecNorm.Obligation.Obg_by_head, {})
        self.assertEqual(sleecParser.registered_type, set())
        self.assertFalse(analysis_failures(self.engine.detector.run_text(specification())))

    def test_bounds_and_inconclusive_results_are_failures(self):
        for outcome in [-1, 2, None]:
            with self.subTest(outcome=outcome):
                with patch.object(sleecParser, "check_property_refining", return_value=outcome), \
                     patch.object(SleecNorm, "check_property_refining", return_value=outcome):
                    result = self.engine.detector.run_text(specification())
                self.assertEqual(result["status"], "ERROR")
                self.assertIn("concern", analysis_failures(result))
                self.assertIn("situational_conflict", analysis_failures(result))

    def test_no_issue_is_a_successful_analysis(self):
        gate = self.engine.validate_patched_sleec(specification(60))
        self.assertTrue(gate["valid"], gate)
        for result in gate["analysis"]["detections"].values():
            self.assertTrue(result["success"])
            self.assertFalse(result["detected"])

    def test_conclusive_retry_after_solver_bound_is_allowed(self):
        with patch.object(sleecParser, "check_property_refining", side_effect=[2, 0]):
            result = self.engine.detector.safe_call("concern", sleec_api.check_concern, specification())
        self.assertTrue(result["success"])
        self.assertFalse(result["detected"])

    def test_missing_proof_is_reported_as_a_failure(self):
        with patch.object(sleecParser, "check_property_refining", return_value=0), \
             patch.object(sleecParser, "check_and_minimize", return_value=None):
            result = self.engine.detector.safe_call("redundancy", sleec_api.check_redundancy, specification())
        self.assertFalse(result["success"])
        self.assertIn("proof", result["message"])

    def test_invalid_results_do_not_become_empty_successes(self):
        for outcome in [None, "unknown", (None, "", []), (False, "", None), (True, "", [])]:
            with self.subTest(outcome=outcome):
                result = self.engine.detector.safe_call("concern", lambda text: outcome, specification())
                self.assertFalse(result["success"])

    def test_missing_or_failed_detector_blocks_verification(self):
        missing = clean_analysis()
        del missing["detections"]["purpose"]
        incomplete = clean_analysis()
        del incomplete["structured"]["concerns"]
        for result in [failed_analysis(), missing, incomplete, {}, None]:
            with self.subTest(result=result):
                with patch.object(self.engine, "run_detector_cached", return_value=result):
                    gate = self.engine.validate_patched_sleec(specification())
                self.assertFalse(gate["valid"])

    def test_failed_analyses_are_not_cached(self):
        with patch.object(sleec_api, "check_input_conflict", side_effect=RuntimeError("temporary error")):
            result = self.engine.run_detector_cached(specification())
        self.assertTrue(analysis_failures(result))
        self.assertEqual(len(self.engine.detector_cache), 0)
        recovered = self.engine.run_detector_cached(specification())
        self.assertFalse(analysis_failures(recovered))
        self.assertEqual(len(self.engine.detector_cache), 1)

    def test_failed_diagnosis_does_not_use_heuristic_fallback(self):
        with patch.object(self.engine, "run_detector_cached", return_value=failed_analysis()), \
             patch.object(self.engine, "fallback_wfi_detection") as fallback:
            result = self.engine.diagnose(specification())
        self.assertEqual(result["status"], "ERROR")
        fallback.assert_not_called()

    def test_failed_original_analysis_stops_generation(self):
        with patch.object(self.engine, "run_detector_cached", return_value=failed_analysis()):
            with self.assertRaisesRegex(RuntimeError, "original analysis failed"):
                self.engine.generate_verified_patches("test", specification(), {"issue_type": "concerns"})
        self.engine.gpt_patch_engine.generate_all_patches.assert_not_called()

    def test_failed_original_analysis_blocks_cumulative_verification(self):
        with patch.object(self.engine, "run_detector_cached", side_effect=[clean_analysis(), failed_analysis()]):
            result = self.engine.validate_cumulative_sleec(specification(), specification(60))
        self.assertFalse(result["valid"])
        self.assertFalse(result["passed"])

    def test_failed_original_analysis_blocks_candidate_verification(self):
        candidate = {"operation": "edit", "target_rule_id": "R1", "proposed_rule": "R1 when Start then Act within 60 seconds"}
        with patch.object(self.engine, "run_detector_cached", side_effect=[clean_analysis(), failed_analysis()]):
            result = self.engine.verify_candidate_patch(specification(), {"issue_type": "concerns"}, candidate)
        self.assertFalse(result["verified"])

    def test_detector_failure_does_not_trigger_llm_syntax_retry(self):
        candidate = {"operation": "edit", "target_rule_id": "R1", "proposed_rule": "R1 when Start then Act within 60 seconds"}
        with patch.object(self.engine, "run_detector_cached", return_value=failed_analysis()):
            result = self.engine.verify_llm_patch_once(specification(), "concerns", "c1", {"concerns": ["c1"]}, candidate)
        self.assertIsNone(result)
        self.engine.gpt_patch_engine.repair_patch_syntax.assert_not_called()

    def test_detector_failure_blocks_deterministic_verification_and_export(self):
        candidate = {"operation": "edit", "target_rule_id": "R1", "proposed_rule": "R1 when Start then Act within 60 seconds"}
        with patch.object(self.engine, "run_detector_cached", return_value=failed_analysis()):
            verified = self.engine.verify_deterministic_patch_iteratively(
                specification(), "concerns", "c1", {"concerns": ["c1"]}, copy.deepcopy(candidate))
            output = self.engine.build_final_sleecpatch_file("test", specification(), [candidate])
        self.assertIsNone(verified)
        self.assertEqual(output["path"], "")
        self.assertFalse(output["cumulative_verification"]["passed"])
        self.assertFalse(Path("results/test/test_SLEECPATCH.sleec").exists())


if __name__ == "__main__":
    unittest.main()
