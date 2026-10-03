"""Evidence retention through real detectors and offline repair/prompt generation."""
import copy
import json
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import test_sleec_verification as fixtures
from services.diagnosis_evidence import diagnosis_for_issue, extract_evidence, parse_trace
from services.deterministic_repair_engine import DeterministicRepairEngine
from services.gpt_patch_engine import GPTPatchEngine
from sleec import sleec_api


STARS = "*" * 100 + "\n"
RULE_A = "policy_safe when Start then Act within 300 seconds"
RULE_B = "policy_backup when Start\n then Act within 300 seconds"
CONCERN_A = "missed_response exists Start while not Act within 120 seconds"
CONCERN_B = "late_response when Start then not Act within 180 seconds"
MODEL = f"""def_start
event Start
event Act
measure urgent:boolean
measure count:numeric
measure risk:scale(low,high)
def_end
rule_start
{RULE_A}
{RULE_B}
rule_end
concern_start
{CONCERN_A}
{CONCERN_B}
concern_end
"""
TRACE = """at time 0: Start()
at time 0: Measure(urgent=True, count=-17, risk=high)
at time 121: Act()
at time 121: Measure(urgent=False, count=0, risk=low)
"""


class EvidenceTests(unittest.TestCase):
    # Reuse only fixture methods, not the verification test cases.
    setUpClass = classmethod(fixtures.VerificationTests.setUpClass.__func__)
    tearDownClass = classmethod(fixtures.VerificationTests.tearDownClass.__func__)
    setUp = fixtures.VerificationTests.setUp
    tearDown = fixtures.VerificationTests.tearDown

    def concern_report(self, trace=TRACE):
        return f"{CONCERN_A}\nConcern is raised\n{trace}{STARS}"

    def test_trace_keeps_order_timestamps_and_typed_values(self):
        finding = extract_evidence("concern", self.concern_report(), MODEL)[0]
        diagnosis = finding["diagnosis"]
        self.assertEqual(diagnosis["source_id"], "missed_response")
        self.assertEqual(diagnosis["trace"][0]["name"], "Start")
        self.assertEqual([e["timestamp"] for e in diagnosis["trace"]], [0, 0, 121, 121])
        self.assertEqual(diagnosis["trace"][1]["values"], {"urgent": True, "count": -17, "risk": "high"})
        self.assertEqual(diagnosis["trace"][3]["values"], {"urgent": False, "count": 0, "risk": "low"})
        self.assertTrue(all(e["time_unit"] == "seconds" for e in diagnosis["trace"]))
        self.assertIn(TRACE.strip(), diagnosis["raw_report"])
        self.assertEqual(diagnosis["affected_rule_ids"], [])
        self.assertEqual(diagnosis["rule_id_provenance"], "unavailable")
        self.assertEqual(json.loads(json.dumps(finding)), finding)

    def test_multiple_findings_do_not_share_or_duplicate_stdout_traces(self):
        second_trace = "at time 181: Act()\n"
        report = self.concern_report() + f"{CONCERN_B}\nConcern is raised\n{second_trace}{STARS}"
        def detector(_):
            print(report)
            print("at time 999: Act()")
            return True, report, []
        result = self.engine.detector.safe_call("concern", detector, MODEL)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["count"], 2)
        self.assertEqual(len(result["findings"][0]["diagnosis"]["trace"]), 4)
        self.assertEqual(result["findings"][1]["diagnosis"]["trace"][0]["timestamp"], 181)
        self.assertIn("999", result["debug_output"])
        self.assertNotIn("999", json.dumps(result["findings"]))

    def test_custom_rule_ids_and_full_multiline_proof_are_preserved(self):
        for kind, header in [("conflict", "Conflicting SLEEC rule:"),
                             ("redundancy", "Redundant SLEEC rule:")]:
            report = f"{header}\n{RULE_B}\nBecause of the following SLEEC rule:\n{RULE_A}\n{STARS}"
            finding = extract_evidence(kind, report, MODEL)[0]
            self.assertEqual(finding["diagnosis"]["affected_rule_ids"], ["policy_backup", "policy_safe"])
            self.assertEqual(finding["original_rules"], [RULE_B, RULE_A])
            self.assertIn(RULE_A, finding["diagnosis"]["raw_report"])
            self.assertEqual(finding["diagnosis"]["rule_id_provenance"], "detector_report")

    def test_situational_reports_keep_separate_witnesses_and_rule_ids(self):
        reports = [f"Situational conflict under situation :\nat time {t}: Start()\nFor rule:\n{rule}\n"
                   for t, rule in [(5, RULE_A), (8, RULE_B)]]
        findings = extract_evidence("situational_conflict", "".join(reports), MODEL)
        self.assertEqual(len(findings), 2)
        for finding, t, rule_id in zip(findings, [5, 8], ["policy_safe", "policy_backup"]):
            self.assertEqual([e["timestamp"] for e in finding["diagnosis"]["trace"]], [t])
            self.assertEqual(finding["diagnosis"]["affected_rule_ids"], [rule_id])

    def test_unknown_trace_format_and_fractional_values_are_not_lost(self):
        trace = "at time 1/3: Act()\nat time ? unknown witness\nat time 4: Measure(count=1/7)\n"
        entries = parse_trace(trace)
        self.assertEqual(entries[0]["timestamp"], "1/3")
        self.assertEqual(entries[1], {"kind": "unparsed", "raw": "at time ? unknown witness"})
        self.assertEqual(entries[2]["values"]["count"], "1/7")
        self.assertEqual("\n".join(e["raw"] for e in entries) + "\n", trace)

    def test_same_finding_with_two_witnesses_keeps_the_selected_witness(self):
        reports = [f"Situational conflict under situation :\nat time {t}: Start()\nFor rule:\n{RULE_A}\n"
                   for t in [5, 8]]
        findings = extract_evidence("situational_conflict", "".join(reports), MODEL)
        analysis = fixtures.clean_analysis()
        analysis["detections"]["situational_conflict"]["detected"] = True
        structured = analysis["structured"]
        structured["situational_conflicts"] = [f["value"] for f in findings]
        structured["diagnoses_by_type"] = {"situational_conflicts": [f["diagnosis"] for f in findings]}
        with patch.object(self.engine, "run_detector_cached", return_value=analysis):
            issues = self.engine.diagnose(MODEL)["issues"]
        self.assertEqual([i["diagnosis"]["trace"][0]["timestamp"] for i in issues], [5, 8])
        selected = diagnosis_for_issue(structured, "situational_conflicts", issues[1]["value"], issues[1]["id"])
        self.assertEqual(selected["trace"][0]["timestamp"], 8)
        with self.assertRaisesRegex(ValueError, "issue ID"):
            diagnosis_for_issue(structured, "situational_conflicts", issues[0]["value"])

    def test_syntax_retry_cannot_replace_or_drop_original_evidence(self):
        diagnosis = extract_evidence("concern", self.concern_report(), MODEL)[0]["diagnosis"]
        candidate = {"target_rule_id": "R1", "operation": "edit", "proposed_rule": "broken", "diagnosis": diagnosis}
        self.engine.gpt_patch_engine.repair_patch_syntax.return_value = {
            "target_rule_id": "R1", "operation": "edit", "proposed_rule": "R1 when Start then Act within 60 seconds",
            "diagnosis": {"trace": ["forged"]}}
        gates = [{"valid": False, "syntax": {"valid": False}, "failure_reason": "malformed"},
                 {"valid": True, "syntax": {"valid": True}, "analysis": fixtures.clean_analysis()}]
        with patch.object(self.engine, "validate_patched_sleec", side_effect=gates):
            verified = self.engine.verify_llm_patch_once(fixtures.specification(), "concerns", CONCERN_A,
                                                        {"concerns": [CONCERN_A]}, candidate)
        self.assertTrue(verified["verified"])
        self.assertEqual(verified["diagnosis"], diagnosis)

    def test_unidentified_report_source_fails_instead_of_losing_the_finding(self):
        report = "unknown exists Start\nConcern is raised\nat time 0: Start()\n"
        result = self.engine.detector.safe_call("concern", lambda _: (True, report, []), MODEL)
        self.assertFalse(result["success"])
        self.assertIn("Cannot identify", result["message"])

    def test_different_witness_does_not_look_like_a_fixed_or_new_issue(self):
        values = []
        for trace in [TRACE, TRACE.replace("121", "150").replace("-17", "-20")]:
            finding = extract_evidence("concern", self.concern_report(trace), MODEL)[0]
            values.append(finding["value"])
        before = {"concerns": [values[0]]}
        after = {"concerns": [values[1]]}
        report = self.engine.build_regression_report("concerns", values[0], before, after)
        self.assertFalse(report["selected_issue_fixed"])
        self.assertEqual(report["new_issue_count"], 0)

    def test_changing_supporting_proof_does_not_change_the_diagnosed_subject(self):
        first = "Situational conflict under situation:\nFor rule:\npolicy_safe when Start then Act\nBecause of the following SLEEC rule:\npolicy_backup when Start then not Act"
        second = first.replace("policy_backup", "policy_other")
        before = {"situational_conflicts": [first], "diagnoses_by_type": {
            "situational_conflicts": [{"source_id": "policy_safe", "affected_rule_ids": ["policy_safe", "policy_backup"]}]}}
        after = {"situational_conflicts": [second], "diagnoses_by_type": {
            "situational_conflicts": [{"source_id": "policy_safe", "affected_rule_ids": ["policy_safe", "policy_other"]}]}}
        report = self.engine.build_regression_report("situational_conflicts", first, before, after)
        self.assertFalse(report["selected_issue_fixed"])
        self.assertEqual(report["new_issue_count"], 0)
        after["diagnoses_by_type"]["situational_conflicts"][0]["source_id"] = "policy_new"
        report = self.engine.build_regression_report("situational_conflicts", first, before, after)
        self.assertEqual(report["new_issue_count"], 1)
        self.assertFalse(report["regression_passed"])

    def test_real_exists_concern_keeps_trace(self):
        result = self.engine.detector.safe_call("concern", sleec_api.check_concern, MODEL)
        self.assertTrue(result["success"], result)
        self.assertEqual(result["count"], 2)
        finding = result["findings"][0]
        self.assertEqual(finding["diagnosis"]["source_id"], "missed_response")
        self.assertTrue(any(e["name"] == "Start" for e in finding["diagnosis"]["trace"]))
        self.assertTrue(any(e["kind"] == "measure" for e in finding["diagnosis"]["trace"]))

    def test_real_mixed_purposes_keep_only_blocked_purpose_evidence(self):
        model = MODEL.split("concern_start")[0].replace(RULE_B + "\n", "") + """purpose_start
blocked_goal exists Start while not Act within 300 seconds
possible_goal exists Start while Act within 300 seconds
purpose_end
"""
        result = self.engine.detector.safe_call("purpose", sleec_api.check_purpose, model)
        self.assertTrue(result["success"], result)
        self.assertIn("Not Blocking", result["debug_output"])
        self.assertEqual(result["count"], 1)
        diagnosis = result["findings"][0]["diagnosis"]
        self.assertEqual(diagnosis["source_id"], "blocked_goal")
        self.assertEqual(diagnosis["affected_rule_ids"], ["policy_safe"])
        self.assertEqual(diagnosis["trace"], [])

    def test_real_situational_conflict_retains_witness_and_proof(self):
        model = MODEL.split("concern_start")[0].replace(
            RULE_A, "policy_safe when Start and {urgent} then Act").replace(
            RULE_B, "policy_backup when Start and ({count} > 0) then not Act")
        result = self.engine.detector.safe_call("situational_conflict", sleec_api.check_situational, model)
        self.assertTrue(result["success"], result)
        self.assertTrue(result["findings"])
        for finding in result["findings"]:
            self.assertTrue(finding["diagnosis"]["trace"])
            self.assertEqual(set(finding["diagnosis"]["affected_rule_ids"]), {"policy_safe", "policy_backup"})

    def test_real_redundancy_and_conflict_keep_proof_rule_ids(self):
        base = MODEL.split("concern_start")[0]
        for kind, detector, text in [
            ("redundancy", sleec_api.check_redundancy, base),
            ("conflict", sleec_api.check_conflict,
             base.replace(RULE_B, "policy_backup when Start then not Act within 300 seconds")),
        ]:
            with self.subTest(kind=kind):
                result = self.engine.detector.safe_call(kind, detector, text)
                self.assertTrue(result["success"], result)
                self.assertTrue(result["findings"])
                self.assertEqual(set(result["findings"][0]["diagnosis"]["affected_rule_ids"]),
                                 {"policy_safe", "policy_backup"})

    def test_diagnosis_survives_ui_generation_prompt_normalization_and_storage(self):
        text = fixtures.specification()
        diagnosed = self.engine.diagnose(text)
        issue = diagnosed["issues"][0]
        evidence = copy.deepcopy(issue["diagnosis"])
        self.assertTrue(evidence["trace"])
        self.assertEqual(diagnosed["issue_count"], 1)

        deterministic = DeterministicRepairEngine()
        self.engine.deterministic_engine = Mock(wraps=deterministic)
        self.engine.operator_selector = Mock()
        from services.evidence_repair import target_resolution
        self.engine.operator_selector.select.return_value = {
            "deterministic": ["deadline_refinement"], "llm": ["new_rule_generation"],
            "diagnosis": evidence, "target_resolution": target_resolution(text, "concerns", evidence)}
        self.engine.store = Mock()
        from services.patch_ranker import PatchRanker
        self.engine.patch_ranker = PatchRanker()
        self.engine.gpt_patch_engine = GPTPatchEngine()
        client = Mock()
        # A controlled offline LLM candidate, rejected by the verification stub.
        client.chat.completions.create.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps([{
                "operation": "new_rule_generation", "target_rule_id": None, "source_requirement_id": "c1",
                "change": {"rule_id": "R2", "trigger_event": "Start", "condition": "({risk} = high)",
                           "response_event": "Act", "negated": False, "deadline": {"kind": "source"}},
                "natural_language_explanation": "Prevent the selected concern within its stated deadline."
            }])) )])
        self.engine.semantic_validator = Mock()
        self.engine.semantic_validator.validate.return_value = {"valid": True}
        # Legacy clients can omit evidence; posted evidence must not override it.
        issue["diagnosis"] = {"trace": ["forged"]}
        with patch("services.gpt_patch_engine._get_client", return_value=client), \
             patch.object(self.engine, "verify_deterministic_patch_iteratively", return_value=None), \
             patch.object(self.engine, "verify_llm_patch_once", return_value=None), \
             patch.object(self.engine, "build_final_sleecpatch_file", return_value={}):
            result = self.engine.generate_verified_patches("test", text, issue)
        self.assertEqual(result["selected_issue"]["diagnosis"], evidence)
        self.assertEqual(self.engine.deterministic_engine.generate.call_args.kwargs["diagnosis"], evidence)
        candidates = result["deterministic_candidates"] + result["llm_candidates"]
        self.assertGreaterEqual(len(candidates), 2)
        for candidate in candidates:
            self.assertEqual(candidate["diagnosis"], evidence)
            self.assertEqual(self.engine.normalize_patch(candidate, text)["diagnosis"], evidence)
        for call in self.engine.store.save_patch_candidate.call_args_list:
            self.assertEqual(call.args[0]["patch"]["diagnosis"], evidence)
        self.assertFalse(hasattr(self.engine, "_ranking_context"))
        prompt = client.chat.completions.create.call_args.kwargs["messages"][1]["content"]
        payload, _ = json.JSONDecoder().raw_decode(prompt.split("\nINPUT:\n", 1)[1])
        self.assertEqual(payload["diagnosis_evidence"], [evidence])
        stored = self.engine.store.save_pipeline_run.call_args.args[0]["original_structured"]
        self.assertEqual(stored["diagnoses_by_type"]["concerns"], [evidence])


if __name__ == "__main__":
    unittest.main()
