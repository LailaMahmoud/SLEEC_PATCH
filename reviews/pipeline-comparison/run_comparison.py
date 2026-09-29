"""Reproduce the offline comparison using immutable Git snapshots.

Run from the project with: venv/bin/python reviews/pipeline-comparison/run_comparison.py
Requires the project's Python dependencies; makes no network or database calls.
"""
import json
from pathlib import Path
import subprocess
import sys
import tempfile


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
REVISIONS = {
    "main": "c75d47e19609a8cfd4b8d99ed5eb311e75750a69",
    "development": "aee947a8d412afea413b8c8180c89ebee1cf0501",
}


def main():
    metadata = {"revisions": REVISIONS, "python": sys.version, "live_llm_calls": 0}
    with tempfile.TemporaryDirectory(prefix="sleec-pipeline-comparison-") as folder:
        for branch, revision in REVISIONS.items():
            snapshot = Path(folder) / branch
            snapshot.mkdir()
            archive = subprocess.check_output(
                ["git", "archive", revision, "SLEECpatch/app", "sleec"], cwd=REPOSITORY
            )
            subprocess.run(["tar", "-xf", "-", "-C", str(snapshot)], input=archive, check=True)
            subprocess.run(
                [sys.executable, str(HERE / "probe_pipeline.py"), str(snapshot),
                 str(HERE / f"{branch}-results.json")],
                check=True, timeout=180, cwd=snapshot,
            )
    (HERE / "metadata.json").write_text(json.dumps(metadata, indent=2) + "\n")


if __name__ == "__main__":
    main()
