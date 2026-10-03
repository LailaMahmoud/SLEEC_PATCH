"""Offline case-study smoke test: real detectors, temporary SQLite, no LLM calls.

Run from the repository root with the project Python environment:
    python scripts/check_repair_cases.py --output /tmp/repair-cases.json
Each case runs in its own process. A timeout is inconclusive, never success.
"""
import argparse
import contextlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def check_case(name, issue_ids=(), checkpoint=None):
    sys.path[:0] = [str(ROOT / "SLEECpatch/app"), str(ROOT)]
    text = (ROOT / "SLEECpatch/app/sleec_usecases" / name).read_text(encoding="utf-8-sig")
    previous = Path.cwd()
    with contextlib.ExitStack() as stack:
        scratch = stack.enter_context(tempfile.TemporaryDirectory(prefix="sleec-case-check-"))
        os.chdir(scratch)
        stack.callback(os.chdir, previous)
        stack.enter_context(patch.dict(os.environ, {"DATABASE_URL": "", "SLEEC_REQUIRE_DATABASE_URL": "0"}))
        stack.enter_context(patch("dotenv.load_dotenv", return_value=False))
        stack.enter_context(patch("httpx.Client.send", side_effect=AssertionError("External HTTP disabled")))
        from services import sleec_patch_evaluation_store as persistence
        stack.enter_context(patch.object(persistence, "DATABASE_URL", ""))
        stack.enter_context(patch.object(persistence, "REQUIRE_DATABASE_URL", False))
        stack.enter_context(patch.object(persistence, "DB_PATH", str(Path(scratch) / "probe.sqlite")))
        from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine
        engine = SLEECPatchWorkbenchEngine()
        stack.enter_context(patch.object(engine.gpt_patch_engine, "generate_all_patches", return_value=[]))
        diagnosis = engine.diagnose(text)
        issues = [issue for issue in diagnosis["issues"] if not issue_ids or issue["id"] in issue_ids]
        if diagnosis["status"] == "OK" and set(issue_ids) - {issue["id"] for issue in issues}:
            raise ValueError("A requested issue is absent from this case's diagnosis.")
        report = {"case": name, "status": "RUNNING" if diagnosis["status"] == "OK" else diagnosis["status"],
                  "diagnosis_status": diagnosis["status"], "error": diagnosis.get("error", ""),
                  "selected_issue_count": len(issues),
                  "issue_count": diagnosis["issue_count"], "repairs": [], "llm_calls": 0}

        def save_progress():
            report["saved_successes"] = len(engine.store.all_results())
            expected = sum(row["verified"] for row in report["repairs"])
            assert report["saved_successes"] == expected, "Saved results disagree with verification"
            if checkpoint:
                checkpoint.write_text(json.dumps(report, indent=2) + "\n")

        save_progress()
        for issue in issues:
            result = engine.generate_verified_patches(Path(name).stem, text, issue, max_attempts=1)
            report["repairs"].append({"issue": issue["id"],
                "source_id": issue.get("diagnosis", {}).get("source_id"),
                "verified": len(result["verified_patches"]),
                "operations": [p["operation"] for p in result["verified_patches"]],
                "failed": [{"operation": p.get("operation"), "reason": p.get("failure_reason")}
                           for p in result["failed_patches"]],
                "semantic_operators": result["repair_operators"].get("llm", []),
                "log": result["log"]})
            save_progress()
        report["status"] = diagnosis["status"]
        save_progress()
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--case", action="append", dest="cases")
    parser.add_argument("--issue-id", action="append", default=[],
                        help="Run only the specified diagnosis ID (repeatable).")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args()
    cases = args.cases or ["ALMI.sleec", "aspen.sleec", "DRESSASSIST.sleec", "Daisy.sleec"]
    args.output = args.output.resolve()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if args.worker:
        check_case(cases[0], args.issue_id, args.output)
        return
    reports = []
    with tempfile.TemporaryDirectory(prefix="sleec-case-workers-") as scratch:
        for index, name in enumerate(cases):
            started = time.monotonic()
            result_file = Path(scratch) / f"{index}.json"
            log_file = args.output.with_suffix(f".{index}.log")
            try:
                with log_file.open("w") as log:
                    command = [sys.executable, __file__, "--worker", "--case", name,
                               "--output", str(result_file)]
                    for issue_id in args.issue_id:
                        command.extend(["--issue-id", issue_id])
                    completed = subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT,
                        timeout=args.timeout, check=False)
                report = json.loads(result_file.read_text()) if completed.returncode == 0 else {
                    "case": name, "status": "ERROR", "error": f"Worker failed; see {log_file}"}
            except subprocess.TimeoutExpired:
                report = json.loads(result_file.read_text()) if result_file.exists() else {"case": name}
                report.update(status="INCONCLUSIVE", error="Case exceeded the probe timeout; only completed issues are listed.")
            report["seconds"] = round(time.monotonic() - started, 3)
            reports.append(report)
            args.output.write_text(json.dumps(reports, indent=2) + "\n")
            print(name, report["status"], report["seconds"], flush=True)


if __name__ == "__main__":
    main()
