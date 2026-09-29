"""Real parser/detector regressions; LLM and database calls remain offline."""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_sleec_verification as fixtures
from services.candidate_status import formally_verified, update_candidate_status
from services.deterministic_repair_engine import DeterministicRepairEngine
from services.evidence_repair import generate_repairs, target_resolution
from services.gpt_patch_engine import GPTPatchEngine
from services.patch_ranker import PatchRanker
from services.repair_operator_selector import RepairOperatorSelector
from services.rule_model import rules_from_text, source, parse_sleec_ast, expression_value
from services.semantic_patch_validator import SemanticPatchValidator
from services.structured_semantic_edit import materialize_semantic_edit
from services.prompts import OPERATOR_EXAMPLES
from services import sleec_patch_evaluation_store as evaluation_store


def spec(rules=None, concern="late exists Start and {urgent} while not Act within 2 minutes"):
    rules = rules or "policy_safe when Start then Act within 5 minutes"
    return f"""def_start
event Start
event Act
event Backup
measure urgent:boolean
measure ready:boolean
measure count:numeric
measure risk:scale(low,high)
def_end
rule_start
{rules}
rule_end
""" + (f"concern_start\n{concern}\nconcern_end\n" if concern else "")


def proposal(operation="event_specialization", **change):
    return {"operation": operation, "target_rule_id": "policy_safe", "change": {
        "from": "Start", "to": "ReadyToStart", "meaning": "Start is ready for processing.",
        "evidence": "Distinguish the readiness context in the reported source requirement.", **change},
        "natural_language_explanation": "A proposed specialization, subject to review."}


class ImprovementTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.VerificationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.VerificationTests.tearDownClass.__func__)
    tearDown = fixtures.VerificationTests.tearDown

    def setUp(self):
        fixtures.VerificationTests.setUp(self)
        self.engine.deterministic_engine = DeterministicRepairEngine()
        self.engine.operator_selector = RepairOperatorSelector()
        self.engine.semantic_validator = SemanticPatchValidator()

    def diagnosis(self, text, kind="concerns"):
        analysis = self.engine.run_detector_cached(text)
        self.assertFalse(self.engine.detector_failures(analysis), analysis.get("error"))
        evidence = analysis["structured"]["diagnoses_by_type"][kind][0]
        value = analysis["structured"][kind][0]
        return analysis, evidence, value

    def test_roundtrip_keeps_custom_ids_comments_intervals_and_stacked_exceptions(self):
        rule = "policy_safe when Start and ({urgent} or {ready}) then Act within [1 minutes, 5 minutes]\n unless {urgent} then Backup unless (not {ready}) then not Act"
        text = spec(rule + "\n// unrelated\npolicy_safely when Backup then Act", concern="")
        rules = rules_from_text(text)
        self.assertEqual([r["id"] for r in rules], ["policy_safe", "policy_safely"])
        self.assertEqual(self.engine.deterministic_engine.rule_to_text(rules[0]), rule)
        changed = self.engine.apply_patch_to_text(text, {"operation": "edit", "target_rule_id": "policy_safe", "proposed_rule": rule.replace("5 minutes", "3 minutes")})
        self.assertEqual(changed, text.replace("5 minutes", "3 minutes"))
        self.assertTrue(self.engine.check_sleec_syntax(changed)["valid"])

    def test_measure_values_choose_a_supported_target_without_arbitrary_ties(self):
        text = spec("policy_safe when Start and {ready} then Act within 5 minutes\npolicy_other when Start and (not {ready}) then Act within 5 minutes")
        evidence = {"source_id": "late", "trace": [
            {"kind": "event", "name": "Start", "timestamp": 10},
            {"kind": "measure", "timestamp": 10, "values": {"ready": True, "urgent": True}}]}
        result = target_resolution(text, "concerns", evidence)
        self.assertEqual(result["rule_ids"], ["policy_safe"])
        self.assertEqual(result["observed_contexts"][0]["timestamp"], 10)
        evidence["trace"] = []
        self.assertEqual(target_resolution(text, "concerns", evidence)["rule_ids"], [])
        self.assertEqual(self.engine.deterministic_engine.find_conflicting_rules("No rule reference", rules_from_text(text)), [])

    def test_numeric_and_scale_snapshots_use_declared_order(self):
        text = spec("policy_safe when Start and (({risk} > low) and ({count} >= 3)) then Act", concern="")
        node = parse_sleec_ast(text).ruleBlock.rules[0].condition
        self.assertIs(expression_value(node, {"risk": "high", "count": 4}), True)
        self.assertIs(expression_value(node, {"risk": "low", "count": 4}), False)
        self.assertIsNone(expression_value(node, {"risk": "high"}))

    def test_timing_repair_verifies_and_preserves_other_contexts(self):
        for condition in ["{urgent}", "((not {urgent}) or {ready})"]:
            with self.subTest(condition=condition):
                text = spec(concern=f"late exists Start and {condition} while not Act within 2 minutes")
                analysis, evidence, value = self.diagnosis(text)
                patches = generate_repairs(text, "concerns", evidence, ["trigger_strengthening", "rule_decomposition"])
                self.assertTrue(patches)
                candidate = patches[0]
                self.assertIn("within 2 minutes", candidate["proposed_rule"])
                self.assertIn("within 5 minutes", candidate["proposed_rule"])
                updated = self.engine.apply_patch_to_text(text, candidate)
                self.assertTrue(self.engine.check_sleec_syntax(updated)["valid"])
                result = self.engine.verify_deterministic_patch_iteratively(text, "concerns", value, analysis["structured"], candidate, max_depth=0)
                self.assertIsNotNone(result, candidate.get("failure_reason"))
                self.assertTrue(formally_verified(result))

    def test_repair_preserves_other_defeaters_and_avoids_rule_id_collisions(self):
        text = spec("policy_safe when Start then Act unless {urgent} then not Act unless (not {ready}) then Backup\npolicy_safe_1 when Backup then Act",
                    "late exists Start and ({urgent} and {ready}) while not Act")
        _, evidence, _ = self.diagnosis(text)
        patches = generate_repairs(text, "concerns", evidence, ["rule_decomposition", "defeater_introduction"])
        exception_patch = next(p for p in patches if p["operation"] == "defeater_introduction")
        self.assertIn("unless (not {ready}) then Backup", exception_patch["proposed_rule"])
        decomposition = next(p for p in patches if p["operation"] == "rule_decomposition")
        self.assertIn("policy_safe_2 when", decomposition["proposed_rule"])
        for candidate in patches:
            self.assertTrue(self.engine.check_sleec_syntax(self.engine.apply_patch_to_text(text, candidate))["valid"])

    def test_same_concern_with_changed_witness_is_still_unresolved(self):
        text = spec()
        before, evidence, value = self.diagnosis(text)
        after = self.engine.run_detector_cached(text.replace("5 minutes", "3 minutes"))
        report = self.engine.build_regression_report("concerns", value, before["structured"], after["structured"])
        self.assertFalse(report["selected_issue_fixed"])
        self.assertEqual(report["new_issue_count"], 0)
        self.assertEqual(evidence["source_id"], "late")

    def test_removing_the_concern_is_not_a_repair(self):
        text = spec()
        without_concern = text.split("concern_start")[0]
        result = self.engine.validate_cumulative_sleec(text, without_concern)
        self.assertFalse(result["valid"])
        self.assertIn("cannot change", result["failure_reason"])

    def test_structured_event_and_capability_edits_preserve_deadlines_exceptions(self):
        text = spec("policy_safe when Start then Act within 5 minutes unless {urgent} then Backup", concern="")
        for op, change in [("event_specialization", {"from": "Start", "to": "ReadyToStart"}),
                           ("capability_refinement", {"from": "Act", "to": "ActPrecisely"})]:
            candidate = materialize_semantic_edit(text, proposal(op, **change), ["policy_safe"])
            self.assertIn("within 5 minutes unless {urgent} then Backup", candidate["proposed_rule"])
            self.assertTrue(self.engine.check_sleec_syntax(self.engine.apply_patch_to_text(text, candidate))["valid"])

    def test_measure_edits_preserve_numeric_and_scale_types(self):
        cases = [("({count} > 3)", "count", "preciseCount", {}, "numeric"),
                 ("({risk} = high)", "risk", "specificRisk", {"scale_labels": ["specificLow", "specificHigh"]}, "scale(specificLow,specificHigh)")]
        for guard, old, new, extra, expected in cases:
            text = spec(f"policy_safe when Start and {guard} then Act within 5 minutes", concern="")
            candidate = materialize_semantic_edit(text, proposal("measure_specialization", **{"from": old, "to": new, **extra}), ["policy_safe"])
            self.assertEqual(candidate["declaration_text"], f"measure {new}:{expected}")
            self.assertTrue(self.engine.check_sleec_syntax(self.engine.apply_patch_to_text(text, candidate))["valid"])

    def test_unstructured_unrelated_and_injected_proposals_are_rejected(self):
        text = spec()
        candidates = [proposal(), proposal(), proposal()]
        candidates[0]["proposed_rule"] = "arbitrary rewrite"
        candidates[1]["target_rule_id"] = "other"
        candidates[2]["change"]["to"] = "NewEvent\nrule_end"
        for candidate in candidates:
            with self.assertRaises(ValueError):
                materialize_semantic_edit(text, candidate, ["policy_safe"])

    def test_new_rule_cannot_inject_additional_rules_or_requirements(self):
        candidate = {"operation": "new_rule_generation", "target_rule_id": "policy_safe",
                     "change": {"rule_id": "extra", "trigger_event": "Start", "condition": "{urgent}",
                                "response_event": "Act", "negated": False, "deadline": {"value": 2, "unit": "minutes"}},
                     "natural_language_explanation": "Meet the concern's declared deadline."}
        valid = materialize_semantic_edit(spec(), candidate, ["policy_safe"])
        self.assertIn("extra when Start", valid["proposed_rule"])
        candidate["change"]["condition"] = "true then Act\nextra_injected when Start"
        with self.assertRaises(ValueError):
            materialize_semantic_edit(spec(), candidate, ["policy_safe"])

    def test_every_prompt_example_materializes_to_valid_sleec(self):
        text = spec(concern="").replace("event Start", "event ParcelArrived").replace("event Act", "event Notify")
        text = text.replace("measure urgent:boolean", "measure priority:boolean")
        text = text.replace("policy_safe when Start then Act within 5 minutes", "r1 when ParcelArrived and {ready} then Notify within 5 minutes")
        for operation, example in OPERATOR_EXAMPLES.items():
            with self.subTest(operation=operation):
                candidate = materialize_semantic_edit(text, json.loads(example), ["r1"])
                self.assertTrue(self.engine.check_sleec_syntax(self.engine.apply_patch_to_text(text, candidate))["valid"])

    def test_unverified_candidates_never_reach_ranking_or_export(self):
        assessor = Mock()
        candidates = [{"verified": True}, {"verified": False, "syntax_validation": {"valid": True}}]
        self.assertEqual(PatchRanker(semantic_assessor=assessor).rank(candidates), [])
        assessor.assert_not_called()
        result = self.engine.build_final_sleecpatch_file("unverified", spec(), candidates)
        self.assertFalse(result["path"])
        status = update_candidate_status({"source": "llm", "verified": True, "target_fixed": True,
            "syntax_validation": {"valid": True}, "regression_report": {"regression_passed": True}})
        self.assertEqual(status["candidate_status"], "formally_verified")
        self.assertEqual(status["semantic_review_status"], "pending")

    def test_duplicate_ids_fail_diagnosis_before_detector_execution(self):
        text = spec("policy_safe when Start then Act\npolicy_safe when Backup then Act", concern="")
        with patch("services.sleec_detection_engine.check_concern") as detector:
            result = self.engine.diagnose(text)
        self.assertEqual(result["status"], "ERROR")
        self.assertEqual(result["issues"], [])
        detector.assert_not_called()

    def test_candidate_outcome_is_updated_in_sqlite_without_duplicate_rows(self):
        database = str(Path.cwd() / "status-test.sqlite")
        with patch.object(evaluation_store, "DB_PATH", database), \
             patch.object(evaluation_store, "DATABASE_URL", ""), \
             patch.object(evaluation_store, "REQUIRE_DATABASE_URL", False):
            store = evaluation_store.SLEECPatchEvaluationStore()
            candidate = {"patch_id": "p1", "source": "llm", "diagnosis": {"trace": [{"timestamp": 12}]}}
            store.save_patch_candidate({"run_id": "test", "patch": candidate})
            candidate.update(candidate_status="inconclusive", failure_reason="Solver did not complete.", semantic_review_status="pending")
            store.update_patch_candidate({"run_id": "test", "patch": candidate})
            conn = store.connect()
            try:
                rows = conn.execute("SELECT candidate_status, patch_json FROM sleec_patch_candidates WHERE run_id = ?", ("test",)).fetchall()
            finally:
                conn.close()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][0], "inconclusive")
        self.assertEqual(json.loads(rows[0][1])["diagnosis"], candidate["diagnosis"])

    def test_ranking_uses_each_candidates_context(self):
        self.engine._ranking_context = {"diagnosis_context": "different concurrent request"}
        context = {"diagnosis_context": {"source_id": "late"}, "selected_issue": "late", "issue_type": "concerns"}
        self.engine._assess_patch_quality_for_ranking({"ranking_context": context})
        sent = self.engine.gpt_patch_engine.assess_patch_quality.call_args.kwargs["patch"]
        self.assertEqual(sent["diagnosis_context"], context["diagnosis_context"])

    def test_full_pipeline_materializes_verifies_ranks_and_saves_offline_llm_edit(self):
        text = spec()
        issue = self.engine.diagnose(text)["issues"][0]
        self.engine.store = Mock()
        self.engine.patch_ranker = PatchRanker()
        self.engine.gpt_patch_engine = GPTPatchEngine()
        payload = {"operation": "new_rule_generation", "target_rule_id": "policy_safe",
                   "change": {"rule_id": "priority_rule", "trigger_event": "Start", "condition": "{urgent}",
                              "response_event": "Act", "negated": False, "deadline": {"value": 2, "unit": "minutes"}},
                   "natural_language_explanation": "Require the response before the priority deadline."}
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps([payload])))])
        with patch("services.gpt_patch_engine._get_client", return_value=client):
            result = self.engine.generate_verified_patches("offline", text, issue)
        self.assertTrue(result["verified_patches"], result["failed_patches"])
        self.assertTrue(any(p["source"] == "llm" for p in result["verified_patches"]), result["failed_patches"])
        self.assertTrue(all(formally_verified(p) for p in result["verified_patches"]))
        self.assertTrue(result["generated_file"]["path"])
        self.engine.store.save_patch_verification.assert_called()
        recorded_run = self.engine.store.save_pipeline_run.call_args.args[0]
        self.assertEqual(recorded_run["input_sha256"], hashlib.sha256(text.encode()).hexdigest())
        for candidate in result["verified_patches"]:
            self.assertEqual(candidate["semantic_review_status"], "pending")


if __name__ == "__main__":
    unittest.main()
