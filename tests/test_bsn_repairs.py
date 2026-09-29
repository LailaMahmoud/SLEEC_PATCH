"""Paper operator split, controlled LLM fixtures and real formal checks.

Handwritten model responses test integration, not live LLM repair success.
"""
import hashlib
import json
from types import SimpleNamespace
from unittest.mock import Mock, patch
import unittest

import test_sleec_verification as fixtures
from test_pipeline_improvements import spec
from services.candidate_status import LLM_ONLY_OPERATORS, formally_verified, update_candidate_status
from services.deterministic_repair_engine import DeterministicRepairEngine
from services.evidence_repair import generate_repairs, target_resolution
from services.gpt_patch_engine import GPTPatchEngine
from services.patch_ranker import PatchRanker
from services.repair_operator_selector import RepairOperatorSelector
from services.rule_model import rules_from_text
from services.semantic_patch_validator import SemanticPatchValidator
from services.structured_semantic_edit import materialize_semantic_edit
from sleec import SleecNorm as norm
from sleec.Analyzer.logic_operator import encode
from pysmt.shortcuts import Int, Bool, is_valid


class BSNRepairTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.VerificationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.VerificationTests.tearDownClass.__func__)
    tearDown = fixtures.VerificationTests.tearDown

    def setUp(self):
        fixtures.VerificationTests.setUp(self)
        self.engine.deterministic_engine = DeterministicRepairEngine()
        self.engine.operator_selector = RepairOperatorSelector()
        self.engine.semantic_validator = SemanticPatchValidator()

    def bsn(self, corrected=False):
        name = "BSN-corrected.sleec" if corrected else "BSN.sleec"
        return (fixtures.ROOT / "SLEECpatch/app/sleec_usecases" / name).read_text()

    def llm_fixture(self, text, source_id="late", **change):
        # Explicit test data: application code must not choose these fields.
        proposal = self.anchored_proposal()
        proposal["source_requirement_id"] = source_id
        proposal["change"].update(change)
        scope = target_resolution(text, "concerns", {"source_id": source_id})["addition_scope"]
        return materialize_semantic_edit(text, proposal, [], scope)

    def test_paper_operator_split_excludes_deterministic_new_rule_generation(self):
        selector = self.engine.operator_selector
        for operators in selector.BASE_DETERMINISTIC_OPERATORS.values():
            self.assertFalse(set(operators) & (LLM_ONLY_OPERATORS | {"concern_completion"}))
        self.assertIn("new_rule_generation", selector.select("concerns", rules=[])["llm"])
        for operator in ["concern_completion", *LLM_ONLY_OPERATORS]:
            with self.subTest(operator=operator), self.assertRaises(ValueError):
                generate_repairs(spec(), "concerns", {"source_id": "late"}, [operator])
        for corrected, sources in [(False, ["C2", "C8", "C9"]), (True, ["C9"])]:
            for source_id in sources:
                self.assertEqual(generate_repairs(self.bsn(corrected), "concerns", {"source_id": source_id},
                    selector.BASE_DETERMINISTIC_OPERATORS["concerns"]), [])

    def test_handwritten_llm_fixtures_preserve_real_bsn_sources(self):
        changes = {
            "C2": {"trigger_event": "TrackVitals", "condition": "({canDeactivate} and ({patientDiscomfort} > low))",
                   "response_event": "CaregiverCanDeactivate"},
            "C8": {"trigger_event": "DataCollected", "condition": "", "response_event": "AnonymizeData"},
            "C9": {"trigger_event": "UserWantsToRemoveSensors", "condition": "", "response_event": "RemoveSensors"},
        }
        for corrected, concern_ids in [(False, ["C2", "C8", "C9"]), (True, ["C9"])]:
            text = self.bsn(corrected)
            digest = hashlib.sha256(text.encode()).hexdigest()
            original = {r["id"]: r["raw"] for r in rules_from_text(text)}
            for source_id in concern_ids:
                with self.subTest(corrected=corrected, concern=source_id):
                    change = dict(changes[source_id])
                    if corrected:
                        change["condition"] = "{canPatientDeactivate}"
                    candidate = self.llm_fixture(text, source_id, **change)
                    self.assertEqual(candidate["source"], "llm")
                    self.assertEqual(candidate["source_requirement_id"], source_id)
                    self.assertFalse(candidate["target_rule_id"])
                    updated = self.engine.apply_patch_to_text(text, candidate)
                    after = {r["id"]: r["raw"] for r in rules_from_text(updated)}
                    self.assertEqual(len(after), len(original) + 1)
                    self.assertEqual(original, {k: after[k] for k in original})
                    self.assertTrue(self.engine.check_sleec_syntax(updated)["valid"])
            self.assertEqual(hashlib.sha256(self.bsn(corrected).encode()).hexdigest(), digest)

    def test_c2_different_trigger_is_context_not_an_arbitrary_edit_target(self):
        resolution = target_resolution(self.bsn(), "concerns", {"source_id": "C2"})
        self.assertEqual(resolution["rule_ids"], [])
        related = next(r for r in resolution["related_responses"] if r["rule_id"] == "Rule1")
        self.assertEqual(related["trigger_event"], "PatientAsleep")
        self.assertIn("main.unless[0]", related["response_paths"])
        scope = resolution["addition_scope"]
        self.assertEqual(scope["trigger_event"], "TrackVitals")
        self.assertTrue(scope["response_negated"])
        self.assertNotIn("proposed_rule", scope)
        self.assertNotIn("response", scope)
        self.assertNotIn("negated", scope)

    def test_c8_exception_is_recognised_without_replacing_deletion(self):
        text = self.bsn()
        resolution = target_resolution(text, "concerns", {"source_id": "C8"})
        self.assertEqual(resolution["rule_ids"], ["Rule12"])
        self.assertEqual(resolution["related_responses"][0]["response_paths"], ["main.unless[0]"])
        self.assertEqual(resolution["addition_scope"]["timing"], "eventually")

    def test_c9_witnesses_do_not_trigger_deterministic_rule_addition(self):
        text = self.bsn(True)
        scopes = []
        for consent in (True, False):
            diagnosis = {"source_id": "C9", "trace": [
                {"kind": "event", "name": "UserWantsToRemoveSensors", "timestamp": 0},
                {"kind": "measure", "timestamp": 0, "values": {"caregiverConsent": consent, "canPatientDeactivate": True}}]}
            self.assertEqual(generate_repairs(text, "concerns", diagnosis,
                self.engine.operator_selector.BASE_DETERMINISTIC_OPERATORS["concerns"]), [])
            scopes.append(target_resolution(text, "concerns", diagnosis)["addition_scope"])
        self.assertEqual(scopes[0], scopes[1])
        self.assertTrue(scopes[0]["response_negated"])

    def test_nested_response_branches_are_found_but_not_flattened(self):
        text = spec("policy_safe when Backup then Act otherwise {Backup unless {urgent} then Act}",
                    "late when Start then not Act")
        resolution = target_resolution(text, "concerns", {"source_id": "late"})
        self.assertEqual(resolution["rule_ids"], [])
        self.assertIn("main.alternative.unless[0]", resolution["related_responses"][0]["response_paths"])

    def test_complex_unknown_and_duplicate_concern_sources_have_no_addition_anchor(self):
        for concern in ["late when Start then not Act while not Backup",
                        "late when Start then not Act unless {urgent} then Backup",
                        "late when Start then not Act\nlate when Backup then not Act"]:
            text = spec(concern=concern)
            self.assertIsNone(target_resolution(text, "concerns", {"source_id": "late"})["addition_scope"])
        self.assertIsNone(target_resolution(spec(), "concerns", {"source_id": "missing"})["addition_scope"])

    def test_llm_supplies_rule_fields_and_duplicate_ids_are_rejected(self):
        text = spec("policy_safe when Backup then Act",
                    "late when Start and ({urgent} or (not {ready})) then not Act within [1 minutes, 5 minutes]")
        candidate = self.llm_fixture(text, trigger_event="Backup", condition="{ready}",
                                     response_event="Start", negated=True, deadline=None)
        self.assertEqual(candidate["proposed_rule"],
                         "complete_late when Backup and {ready} then not Start")
        self.assertFalse(formally_verified(candidate))
        self.assertEqual(candidate["semantic_review_status"], "pending")
        with self.assertRaises(ValueError):
            self.llm_fixture(text, rule_id="policy_safe")

    def test_missing_obligation_verifies_while_preserving_immediate_prohibition(self):
        text = spec("policy_safe when Start and (not {ready}) then not Act",
                    "late when Start and {urgent} then not Act eventually")
        before = self.engine.run_detector_cached(text)
        self.assertFalse(self.engine.detector_failures(before))
        candidate = self.llm_fixture(text)
        result = self.engine.verify_llm_patch_once(
            text, "concerns", before["structured"]["concerns"][0], before["structured"], candidate)
        self.assertIsNotNone(result, candidate.get("regression_report"))
        self.assertTrue(formally_verified(result))
        self.assertIn("policy_safe when Start and (not {ready}) then not Act", result["patched_sleec"])

    def test_incompatible_addition_is_rejected_without_rewriting_existing_rule(self):
        text = spec("policy_safe when Start then not Act eventually",
                    "late when Start then not Act eventually")
        before = self.engine.run_detector_cached(text)
        self.assertFalse(self.engine.detector_failures(before))
        candidate = self.llm_fixture(text, condition="")
        result = self.engine.verify_llm_patch_once(
            text, "concerns", before["structured"]["concerns"][0], before["structured"], candidate)
        self.assertIsNone(result)
        self.assertFalse(formally_verified(candidate))
        self.assertTrue(candidate["regression_report"]["new_issues_introduced"])
        self.assertTrue(candidate["failure_reason"])
        update_candidate_status(candidate)
        self.assertEqual(candidate["candidate_status"], "rejected")

    def anchored_proposal(self):
        return {"operation": "new_rule_generation", "target_rule_id": None,
                "source_requirement_id": "late", "change": {
                    "rule_id": "complete_late", "trigger_event": "Start", "condition": "{urgent}",
                    "response_event": "Act", "negated": False, "deadline": {"kind": "source"}},
                "natural_language_explanation": "Require the response in the source concern's context and time window."}

    def test_structured_addition_keeps_eventually_intervals_and_symbolic_deadlines(self):
        for timing in ["eventually", "within [1 minutes, 5 minutes]", "within delay seconds"]:
            text = spec("policy_safe when Backup then Act", f"late when Start and {{urgent}} then not Act {timing}")
            text = text.replace("def_end", "constant delay = 4\ndef_end")
            scope = target_resolution(text, "concerns", {"source_id": "late"})["addition_scope"]
            candidate = materialize_semantic_edit(text, self.anchored_proposal(), [], scope)
            self.assertTrue(candidate["proposed_rule"].endswith(timing))
            self.assertTrue(self.engine.check_sleec_syntax(self.engine.apply_patch_to_text(text, candidate))["valid"])

    def test_structured_addition_rejects_wrong_source_invalid_fields_and_injections(self):
        text = spec("policy_safe when Backup then Act")
        scope = target_resolution(text, "concerns", {"source_id": "late"})["addition_scope"]
        bad = []
        for key, value in [("trigger_event", "Unknown"), ("response_event", "Unknown"),
                           ("negated", "false"), ("deadline", {"value": -1, "unit": "minutes"}),
                           ("deadline", {"value": 2, "unit": "weeks"}),
                           ("deadline", {"kind": "source", "value": 2}),
                           ("condition", "true then Act\ninjected when Start")]:
            proposal = self.anchored_proposal()
            proposal["change"][key] = value
            bad.append(proposal)
        proposal = self.anchored_proposal()
        proposal["source_requirement_id"] = "other"
        bad.append(proposal)
        for proposal in bad:
            with self.subTest(proposal=proposal), self.assertRaises(ValueError):
                materialize_semantic_edit(text, proposal, [], scope)
        with self.assertRaises(ValueError):
            materialize_semantic_edit(text, self.anchored_proposal(), [], None)

    def test_full_llm_path_accepts_concern_anchor_without_existing_rule_target(self):
        text = spec("policy_safe when Backup then Act")
        issue = self.engine.diagnose(text)["issues"][0]
        self.engine.store = Mock()
        self.engine.patch_ranker = PatchRanker()
        self.engine.gpt_patch_engine = GPTPatchEngine()
        client = Mock()
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps([self.anchored_proposal()])))])
        with patch("services.gpt_patch_engine._get_client", return_value=client):
            result = self.engine.generate_verified_patches("unmatched", text, issue)
        self.assertTrue(result["generated_file"]["path"])
        accepted = result["verified_patches"]
        self.assertTrue(accepted, result["failed_patches"])
        self.assertEqual(result["deterministic_candidates"], [])
        self.assertTrue(all(p["source"] == "llm" and formally_verified(p) for p in accepted))
        self.assertTrue(all(p["source_requirement_id"] == "late" for p in accepted))
        self.assertTrue(all(not p["target_rule_id"] for p in accepted))
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        self.assertIn('"addition_scopes"', prompt)
        example = prompt.split("Illustrative proposal for the selected operator (use the actual domain):")[1].split("INPUT:")[0]
        self.assertEqual(json.loads(example)["change"]["trigger_event"], "ParcelArrived")
        self.assertNotIn("complete_late", example)

    def test_empty_or_failed_llm_does_not_fall_back_to_deterministic_additions(self):
        text = spec("policy_safe when Backup then Act")
        issue = self.engine.diagnose(text)["issues"][0]
        self.engine.store = Mock()
        self.engine.patch_ranker = PatchRanker()
        for error in [None, RuntimeError("LLM unavailable")]:
            with self.subTest(error=error):
                self.engine.gpt_patch_engine = Mock()
                self.engine.gpt_patch_engine.generate_all_patches.return_value = []
                self.engine.gpt_patch_engine.generate_all_patches.side_effect = error
                result = self.engine.generate_verified_patches("no-model-result", text, issue)
                self.engine.gpt_patch_engine.generate_all_patches.assert_called_once()
                self.assertEqual(result["deterministic_candidates"], [])
                self.assertEqual(result["verified_patches"], [])
                self.assertFalse(result["generated_file"]["path"])

    def test_nonpaper_saved_candidates_cannot_apply_rank_or_export(self):
        for operation, origin in [("concern_completion", "deterministic"),
                                  ("concern_completion", "llm"),
                                  ("new_rule_generation", "deterministic")]:
            with self.subTest(operation=operation, origin=origin):
                candidate = {"operation": operation, "source": origin, "verified": True,
                             "target_fixed": True, "syntax_validation": {"valid": True},
                             "regression_report": {"regression_passed": True}}
                self.assertFalse(formally_verified(candidate))
                assessor = Mock()
                self.assertEqual(PatchRanker(semantic_assessor=assessor).rank([candidate]), [])
                assessor.assert_not_called()
                self.assertFalse(self.engine.build_final_sleecpatch_file("retired", spec(), [candidate])["path"])
                with self.assertRaises(ValueError):
                    self.engine.apply_patch_to_text(spec(), candidate)
                self.assertEqual(update_candidate_status(candidate)["candidate_status"], "rejected")

    def test_normalized_windows_preserve_both_bounds_and_explicit_infinity(self):
        trigger = SimpleNamespace(time=Int(10))
        finite = norm.TimeWindow(norm.Constant(2), norm.Constant(4))
        for time, expected in [(9, False), (11, False), (12, True), (14, True), (15, False)]:
            self.assertEqual(is_valid(encode(finite.encode(SimpleNamespace(time=Int(time)), trigger))), expected)
        eventual = norm.TimeWindow(norm.ZERO(), norm.INF(), unbounded=True)
        self.assertTrue(is_valid(encode(eventual.encode(SimpleNamespace(time=Int(200000)), trigger))))
        self.assertFalse(norm.TimeWindow(norm.ZERO(), norm.Constant(99999)).is_inf())
        self.assertFalse(norm.TimeWindow(norm.ZERO(), norm.NATMeasure("count")).is_inst())

    def test_notification_and_eventual_response_do_not_create_a_false_consent_conflict(self):
        text = spec("protect when Start and (not {ready}) then not Act\n"
                    "notify when Start then Backup\n"
                    "complete when Start and {urgent} then Act eventually", concern="")
        analysis = self.engine.run_detector_cached(text)
        self.assertFalse(self.engine.detector_failures(analysis))
        self.assertTrue(all(not analysis["structured"][kind] for kind in self.engine.issue_types()))

    def test_missing_response_is_pending_before_deadline_and_violated_after_it(self):
        # Evaluate quantified formulas over explicit traces, independently of
        # the solver's choice of witness or action instantiation order.
        with patch.object(norm, "forall", side_effect=lambda domain, fn: norm.AND([fn(x) for x in domain])):
            trigger = SimpleNamespace(time=Int(0))
            finite = norm.Obligation(norm.Event("Act", False), norm.TimeWindow(norm.ZERO(), norm.Constant(5)))
            for time, expected in [(0, False), (4, False), (5, False), (6, True)]:
                self.assertEqual(is_valid(encode(finite.violated(trigger, SimpleNamespace(time=Int(time)), {"Act": []}))), expected)
            eventual = norm.Obligation(norm.Event("Act", False), norm.TimeWindow(norm.ZERO(), norm.INF(), unbounded=True))
            self.assertFalse(is_valid(encode(eventual.violated(trigger, SimpleNamespace(time=Int(200000)), {"Act": []}))))

    def test_normalized_rule_cannot_borrow_a_future_measure_or_response(self):
        with patch.object(norm, "forall", side_effect=lambda domain, fn: norm.AND([fn(x) for x in domain])), \
             patch.object(norm, "exist", side_effect=lambda domain, fn: norm.OR([fn(x) for x in domain])):
            now = SimpleNamespace(time=Int(3), ready=Bool(False))
            then = SimpleNamespace(time=Int(0), ready=Bool(True))
            obligation = norm.Obligation(norm.Event("Act", False), norm.TimeWindow(norm.ZERO(), norm.ZERO()))
            chain = norm.ObligationChain([norm.Conditional_Obligation(norm.BoolMeasure("ready"), obligation)])
            rule = norm.NormalizedRule(norm.Event("Start", False), chain)
            rule.register_obligations()
            domain = {"Start": [SimpleNamespace(time=Int(0))], "Measure": [then, now],
                      "Act": [SimpleNamespace(time=Int(4))]}
            self.assertFalse(is_valid(encode(rule.encode_limited(now, domain))))
            # Exempting the current trigger must not exempt an earlier trigger.
            self.assertFalse(is_valid(encode(rule.encode_limited(now, domain, exception=now))))
            domain["Act"] = [SimpleNamespace(time=Int(0))]
            self.assertTrue(is_valid(encode(rule.encode_limited(now, domain))))


if __name__ == "__main__":
    unittest.main()
