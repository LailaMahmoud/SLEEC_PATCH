"""Bounded offline comparison against real repository use cases.

Run with the project venv. Each case has a fresh process and solver scratch
directory. No database or LLM calls are made. Timeout means inconclusive.
"""
import argparse
from collections import OrderedDict
from contextlib import redirect_stdout
import inspect
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading


def check_case(snapshot, case, output):
    sys.path[:0] = [str(snapshot / "SLEECpatch/app"), str(snapshot)]
    from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine
    from services.sleec_detection_engine import SLEECDetectionEngine
    from services.deterministic_repair_engine import DeterministicRepairEngine
    from services.repair_operator_selector import RepairOperatorSelector
    engine = SLEECPatchWorkbenchEngine.__new__(SLEECPatchWorkbenchEngine)
    engine.detector = SLEECDetectionEngine()
    engine.deterministic_engine = DeterministicRepairEngine()
    engine.operator_selector = RepairOperatorSelector()
    engine.detector_cache = OrderedDict()
    engine.detector_cache_lock = threading.RLock()
    engine.detector_cache_max_entries = 64
    text = case.read_text()
    row = {"case": case.name, "outcome": "completed", "repairs": []}
    with tempfile.TemporaryDirectory(prefix="sleec-case-") as scratch:
        os.chdir(scratch)
        with open("solver.log", "w") as log, redirect_stdout(log):
            syntax = engine.check_sleec_syntax(text)
            row["syntax"] = syntax
            if syntax["valid"]:
                before = engine.run_detector_cached(text)
                failures = engine.detector_failures(before)
                row["detector_failures"] = failures
                row["detector_outcomes"] = {name: {"success": result.get("success"), "detected": result.get("detected"),
                    "message_prefix": str(result.get("message", ""))[:300]} for name, result in before.get("detections", {}).items()}
                structured = before.get("structured", {})
                row["issue_counts"] = {key: len(structured.get(key, [])) for key in engine.issue_types()}
                rules = engine.sleec_text_to_rules_json(text)
                row["rules_parsed"] = len(rules)
                row["verbatim_roundtrip"] = all(engine.deterministic_engine.rule_to_text(rule) == rule.get("raw") for rule in rules)
                if not failures:
                    for kind in engine.issue_types():
                        for index, finding in enumerate(structured.get(kind, [])[:1]):
                            plan = engine.operator_selector.select(kind, rules, finding,
                                engine.extract_defined_events(text), engine.extract_defined_measures(text), engine.extract_rule_actions(rules))
                            kwargs = dict(issue_type=kind, selected_issue=finding, rules=rules, operators=plan["deterministic"])
                            signature = inspect.signature(engine.deterministic_engine.generate).parameters
                            if "sleec_text" in signature:
                                kwargs.update(sleec_text=text, diagnosis=structured.get("diagnoses_by_type", {}).get(kind, [{}])[index])
                            candidates = engine.deterministic_engine.generate(**kwargs)
                            for candidate in candidates[:2]:
                                proposed = engine.apply_patch_to_text(text, candidate)
                                valid = engine.check_sleec_syntax(proposed)["valid"]
                                result = engine.verify_deterministic_patch_iteratively(text, kind, finding, structured, candidate, max_depth=0) if valid else None
                                row["repairs"].append({"kind": kind, "operation": candidate["operation"],
                                    "target": candidate.get("target_rule_id"), "syntax_valid": valid,
                                    "verified": bool(result and result.get("verified")),
                                    "failure_reason": candidate.get("failure_reason", "")})
    output.write_text(json.dumps(row, indent=2))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--case", type=Path)
    parser.add_argument("--timeout", type=int, default=45)
    args = parser.parse_args()
    if args.case:
        check_case(args.snapshot.resolve(), args.case.resolve(), args.output.resolve())
        return
    rows = []
    cases = ["BSN.sleec", "BSN-corrected.sleec", "DRESSASSIST.sleec", "DRESSASSIST-corrected.sleec", "ALMI.sleec", "ALMI-corrected.sleec"]
    with tempfile.TemporaryDirectory(prefix="sleec-benchmark-") as scratch:
        for name in cases:
            case = args.snapshot.resolve() / "SLEECpatch/app/sleec_usecases" / name
            output = Path(scratch) / (name + ".json")
            try:
                process = subprocess.run([sys.executable, str(Path(__file__).resolve()), "--snapshot", str(args.snapshot.resolve()),
                    "--case", str(case), "--output", str(output)], capture_output=True, text=True, timeout=args.timeout)
                row = json.loads(output.read_text()) if process.returncode == 0 else {"case": name, "outcome": "error", "error": process.stderr[-3000:]}
            except subprocess.TimeoutExpired:
                row = {"case": name, "outcome": "inconclusive_timeout", "timeout_seconds": args.timeout}
            rows.append(row)
            args.output.write_text(json.dumps(rows, indent=2))
            print(name, row.get("outcome"), flush=True)


if __name__ == "__main__":
    main()
