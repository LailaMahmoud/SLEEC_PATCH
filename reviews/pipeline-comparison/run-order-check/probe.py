"""Uncached, offline cross-case detector probe. Never imports the Flask app."""
import contextlib
import hashlib
import json
import os
from pathlib import Path
import signal
import sys
import tempfile
import time

root, inputs, output = map(lambda value: Path(value).resolve(), sys.argv[1:4])
sys.path[:0] = [str(root / "SLEECpatch/app"), str(root)]
from services.sleec_detection_engine import SLEECDetectionEngine


class StageTimeout(BaseException):
    pass


def timed_out(*_args):
    raise StageTimeout()


signal.signal(signal.SIGALRM, timed_out)
detector = SLEECDetectionEngine()
report = {"implementation": str(root), "cache": "bypassed", "llm_calls": 0,
          "scope": "Sequential diagnoses only, without a repair-generation stage or report database.", "runs": []}
with tempfile.TemporaryDirectory(prefix="sleec-state-scratch-") as scratch:
    os.chdir(scratch)
    for index, name in enumerate(["Daisy.sleec", "ALMI.sleec", "aspen.sleec", "Daisy.sleec"]):
        text = (inputs / name).read_text()
        row = {"case": name, "input_sha256": hashlib.sha256(text.encode()).hexdigest()}
        started = time.monotonic()
        print(f"START {index + 1}: {name}", flush=True)
        try:
            signal.alarm(60)
            with output.with_suffix(f".{index}.log").open("w") as log, contextlib.redirect_stdout(log):
                result = detector.run_text(text)
            row["status"] = result.get("status")
            kinds = ["concerns", "conflicts", "purpose_blocking", "redundancies", "situational_conflicts"]
            row["counts"] = {kind: len(result.get("structured", {}).get(kind, [])) for kind in kinds}
            row["total"] = sum(row["counts"].values())
            row["source_lines"] = {kind: sorted(str(item).strip().splitlines()[0]
                for item in result.get("structured", {}).get(kind, [])) for kind in kinds}
            row["detector_outcomes"] = {kind: {
                "success": value.get("success"), "detected": value.get("detected"),
                "count": value.get("count"), "message_prefix": str(value.get("message", ""))[:300]
            } for kind, value in result.get("detections", {}).items()}
        except StageTimeout:
            row["status"] = "timeout_inconclusive"
        except Exception as exc:
            row.update(status="error", error=str(exc))
        finally:
            signal.alarm(0)
        row["elapsed_seconds"] = round(time.monotonic() - started, 3)
        report["runs"].append(row)
        output.write_text(json.dumps(report, indent=2) + "\n")
        print(json.dumps({key: value for key, value in row.items()
                          if key not in {"source_lines", "detector_outcomes"}}), flush=True)
        if row["status"] in {"timeout_inconclusive", "error"}:
            break
    if len(report["runs"]) == 4:
        report["daisy_counts_equal"] = report["runs"][0]["counts"] == report["runs"][-1]["counts"]
        report["daisy_source_lines_equal"] = report["runs"][0]["source_lines"] == report["runs"][-1]["source_lines"]
        output.write_text(json.dumps(report, indent=2) + "\n")
