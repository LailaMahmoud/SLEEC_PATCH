"""Offline comparative probes; pass an extracted repository snapshot as argv[1].

Uses the real SLEEC parser and detectors. No database is opened and no LLM API
is called. Malformed LLM responses and solver failure are controlled probes.
Writes JSON evidence to argv[2]; does not modify the implementation under test.
"""
import contextlib
import copy
import inspect
import io
import json
import os
from pathlib import Path
import sys
import threading
from collections import OrderedDict
from unittest.mock import patch as mock_patch

ROOT = Path(sys.argv[1]).resolve()
OUTPUT = Path(sys.argv[2]).resolve()
sys.path[:0] = [str(ROOT / "SLEECpatch/app"), str(ROOT)]
os.chdir(ROOT)

from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine
from services.sleec_detection_engine import SLEECDetectionEngine
from services.deterministic_repair_engine import DeterministicRepairEngine
from services.repair_operator_selector import RepairOperatorSelector
from services.semantic_patch_validator import SemanticPatchValidator
from services.patch_ranker import PatchRanker
from services.prompts import OPERATOR_EXAMPLES
from sleec import sleec_api
from sleec.sleecParser import mm


class OfflineLLM:
    def __init__(self):
        self.syntax_calls = 0

    def repair_patch_syntax(self, patch, **kwargs):
        self.syntax_calls += 1
        return copy.deepcopy(patch)


def engine():
    w = SLEECPatchWorkbenchEngine.__new__(SLEECPatchWorkbenchEngine)
    w.detector = SLEECDetectionEngine()
    w.deterministic_engine = DeterministicRepairEngine()
    w.operator_selector = RepairOperatorSelector()
    w.semantic_validator = SemanticPatchValidator()
    w.gpt_patch_engine = OfflineLLM()
    w.detector_cache = OrderedDict()
    w.detector_cache_lock = threading.RLock()
    w.detector_cache_max_entries = 64
    w.patch_ranker = PatchRanker()
    return w


def spec(rules, concern="", extra=""):
    return "\n".join([
        "def_start", "event Start", "event Other", "event Act", "event Backup",
        "measure urgent:boolean", "measure ready:boolean",
        "def_end", "rule_start", rules,
        "rule_end", *( ["concern_start", concern, "concern_end"] if concern else []),
        extra, "",
    ])


def generate(w, text, kind, finding):
    rules = w.sleec_text_to_rules_json(text)
    plan = w.operator_selector.select(
        issue_type=kind, rules=rules, selected_issue=finding,
        existing_events=w.extract_defined_events(text),
        existing_measures=w.extract_defined_measures(text),
        existing_responses=w.extract_rule_actions(rules),
    )
    kwargs = dict(issue_type=kind, selected_issue=finding, rules=rules,
                  operators=plan["deterministic"])
    if "existing_events" in inspect.signature(w.deterministic_engine.generate).parameters:
        kwargs["existing_events"] = w.extract_defined_events(text)
    if "sleec_text" in inspect.signature(w.deterministic_engine.generate).parameters:
        analysis = w.run_detector_cached(text)["structured"]
        index = analysis[kind].index(finding)
        kwargs.update(sleec_text=text, diagnosis=analysis["diagnoses_by_type"][kind][index])
    return plan, w.deterministic_engine.generate(**kwargs)


def deterministic_case(text, kind):
    w = engine()
    syntax = w.check_sleec_syntax(text)
    assert syntax["valid"], syntax
    before = w.run_detector_cached(text)
    findings = before["structured"].get(kind, [])
    result = {"input_syntax_valid": True, "detector_failures": w.detector_failures(before),
              "findings": findings, "repairs": []}
    for finding in findings[:1]:
        plan, patches = generate(w, text, kind, finding)
        result["operator_plan"] = plan
        for candidate in patches:
            patched = w.apply_patch_to_text(text, candidate)
            parsed = w.check_sleec_syntax(patched)
            row = {"operation": candidate["operation"],
                   "target": candidate.get("target_rule_id"),
                   "proposed_rule": candidate.get("proposed_rule"),
                   "syntax_valid": parsed["valid"], "syntax_error": parsed.get("error", ""),
                   "formally_verified": False}
            if parsed["valid"]:
                after = w.run_detector_cached(patched)
                report = w.build_regression_report(kind, finding, before["structured"], after["structured"])
                row.update(target_fixed=report["selected_issue_fixed"],
                           new_issue_count=report["new_issue_count"],
                           remaining_target_findings=after["structured"].get(kind, []),
                           detector_failures=w.detector_failures(after))
                verified = w.verify_deterministic_patch_iteratively(
                    text, kind, finding, before["structured"], copy.deepcopy(candidate), max_depth=0)
                row["formally_verified"] = bool(verified and verified.get("verified"))
            result["repairs"].append(row)
    return result


def llm_gate(text, proposed):
    w = engine()
    before = w.run_detector_cached(text)
    finding = before["structured"]["concerns"][0]
    patch = {"patch_id": "probe", "source": "llm", "operation": "event_specialization",
             "target_rule_id": "R1", "original_rule": "R1 when Start then Act within 5 minutes",
             "proposed_rule": proposed, "missing_element": "Start",
             "natural_language_explanation": "Controlled offline response."}
    returned = w.verify_llm_patch_once(text, "concerns", finding, before["structured"], patch)
    row = {"returned_candidate": returned is not None, "syntax_repair_attempts": w.gpt_patch_engine.syntax_calls}
    if returned:
        row.update({k: returned.get(k) for k in ["verified", "formally_verified", "syntax_valid", "target_fixed", "failure_reason"]})
        assessed = []
        ranker = PatchRanker(semantic_assessor=lambda p: assessed.append(p["patch_id"]) or {})
        row["ranked_candidates"] = len(ranker.rank([returned]))
        row["sent_to_quality_assessor"] = bool(assessed)
        final = w.build_final_sleecpatch_file("offline_probe", text, [returned], before["structured"], "concerns", finding)
        row["exported"] = bool(final["path"])
    return row


def run():
    timed = spec("R1 when Start then Act within 5 minutes",
                 "c1 when Start and {urgent} then not Act within 2 minutes")
    compound = spec("R1 when Start then Act within 5 minutes",
                    "c1 when Start and ((not {urgent}) or {ready}) then not Act within 2 minutes")
    defeated = spec("R1 when Start then Act unless {urgent} then not Act",
                    "c1 when Start and ({urgent} and {ready}) then not Act")
    conflict = spec("R1 when Start and {urgent} then Act\nR2 when Start and {ready} then not Act")
    situational = spec("R1 when Start then Act unless (not {urgent}) then not Act\n"
                      "R2 when Other then Act within 5 minutes unless ({ready} and (not {urgent})) then Backup")
    duplicate = spec("R1 when Start then Act\nR2 when Start then Act")
    report = {"snapshot": str(ROOT), "deterministic": {}}
    for name, text, kind in [
        ("timed_boolean_concern", timed, "concerns"),
        ("timed_compound_concern", compound, "concerns"),
        ("defeater_concern", defeated, "concerns"),
        ("measure_situational_conflict", conflict, "situational_conflicts"),
        ("opposing_defeater_situation", situational, "situational_conflicts"),
        ("redundant_rule", duplicate, "redundancies"),
    ]:
        report["deterministic"][name] = deterministic_case(text, kind)

    report["llm_invalid_syntax"] = llm_gate(timed, "R1 when Start then Act AND BROKEN")
    report["llm_unresolved_target"] = llm_gate(timed, "R1 when Start then Act within 5 minutes")

    w = engine()
    before = w.run_detector_cached(timed)
    message = before["detections"]["concern"]["message"]
    values = before["structured"]["concerns"]
    report["trace_retention"] = {
        "raw_message_has_timed_trace": "at time " in message,
        "selected_findings_have_timed_trace": any("at time " in v for v in values),
        "raw_message": message,
        "selected_findings": values,
        "structured_evidence": before["structured"].get("diagnoses_by_type", {}).get("concerns", []),
    }
    with mock_patch.object(sleec_api, "check_input_conflict", side_effect=RuntimeError("controlled solver failure")):
        failure = w.detector.safe_call("conflict", sleec_api.check_conflict, timed)
    report["detector_failure"] = {"result": failure,
        "gate_recognizes_failure": bool(w.detector_failures({"detections": {"conflict": failure}}))}

    rules = w.sleec_text_to_rules_json(conflict)
    report["unidentified_trace_target"] = [r["id"] for r in
        w.deterministic_engine.find_conflicting_rules("No identifiable rule or event in this witness", rules)]

    # New extraction validates references against the parsed source. Keep the
    # original probes for older snapshots, whose extractor accepts only text.
    if "sleec_text" in inspect.signature(w.detector.extract_findings).parameters:
        concern = "c1 exists Start and {urgent}"
        report["exists_concern_extraction"] = w.detector.extract_findings(
            "concern", concern + "\nConcern is raised\nat time 0: Start()", [],
            spec("R1 when Start then Act", concern))
        purpose = "p1 when Start and {urgent} then Act"
        rule = "R1 when Start then not Act"
        report["purpose_detail_extraction"] = w.detector.extract_findings(
            "purpose", f"Blocked SLEEC purpose:\n{purpose}\nBecause of the following SLEEC rule:\n{rule}", [],
            spec(rule, extra=f"purpose_start\n{purpose}\npurpose_end"))
    else:
        report["exists_concern_extraction"] = w.detector.extract_findings(
            "concern", "c1 exists Start and {urgent}\nConcern is raised\nat time 0: Start()", [])
        report["purpose_detail_extraction"] = w.detector.extract_findings(
            "purpose", "p1 when Start and {urgent} then Act\nBlocking\nat time 0: Start()", [])

    preservation = spec("R1 when Start and ({urgent} and {ready}) then Act within 5 minutes\n"
                        "unless {urgent} then Backup unless {ready} then not Act")
    assert w.check_sleec_syntax(preservation)["valid"]
    rules = w.sleec_text_to_rules_json(preservation)
    serialized = w.deterministic_engine.rule_to_text(rules[0])
    report["rule_preservation"] = {"original": rules[0]["raw"], "serialized": serialized,
        "identical": rules[0]["raw"] == serialized,
        "serialized_syntax_valid": w.check_sleec_syntax(spec(serialized))["valid"]}

    custom = spec("R1bb when Start then Act\npolicy_safe when Other then Backup")
    assert w.check_sleec_syntax(custom)["valid"]
    report["custom_rule_identifiers"] = [r["id"] for r in w.sleec_text_to_rules_json(custom)]

    definitions = {
        "event_specialization": "event FireSafetyMeasures\nevent InformCaregiver\nevent ConfirmedFireHazard",
        "measure_specialization": "event UserWantsToCook\nevent InterfereSafely\nmeasure cookingRiskLevel:scale(low,medium,high)",
        "capability_refinement": "event HumanOnFloor\nevent RequestUrgentCareAssessment\nmeasure humanAssents:boolean",
    }
    report["prompt_correct_patch_syntax"] = {}
    for operation, declarations in definitions.items():
        if "Correct patch:\n" not in OPERATOR_EXAMPLES[operation]:
            # Structured examples are materialized and parsed by the new tests.
            report["prompt_correct_patch_syntax"][operation] = {"structured_edit": json.loads(OPERATOR_EXAMPLES[operation])}
            continue
        example = json.loads(OPERATOR_EXAMPLES[operation].split("Correct patch:\n", 1)[1])[0]
        text = "def_start\n" + declarations + "\ndef_end\nrule_start\n" + example["proposed_rule"] + "\nrule_end\n"
        result = {"proposed_rule": example["proposed_rule"]}
        try:
            mm.model_from_str(text)
            result["syntax_valid"] = True
        except Exception as exc:
            result.update(syntax_valid=False, error=str(exc))
        report["prompt_correct_patch_syntax"][operation] = result

    # Run last: this exposes shared global parser state and contaminates later
    # solver calls in the same process. The implementation is not patched.
    scalar = timed.replace("def_end", "measure risk:scale(low,high)\ndef_end")
    w = engine()
    gate = w.validate_patched_sleec(scalar)
    report["scalar_syntax_then_verification"] = {
        "gate_valid": gate["valid"],
        "syntax": gate["syntax"],
        "detectors": {k: {"success": v["success"], "message": v["message"],
                           "count": v["count"]}
                      for k, v in gate.get("analysis", {}).get("detections", {}).items()},
        "concerns_after_gate": gate.get("analysis", {}).get("structured", {}).get("concerns", []),
    }
    return report


if __name__ == "__main__":
    log = io.StringIO()
    try:
        with contextlib.redirect_stdout(log):
            evidence = run()
        OUTPUT.write_text(json.dumps(evidence, indent=2))
        print(json.dumps({"output": str(OUTPUT), "cases": list(evidence["deterministic"])}))
    finally:
        OUTPUT.with_suffix(".log").write_text(log.getvalue())
