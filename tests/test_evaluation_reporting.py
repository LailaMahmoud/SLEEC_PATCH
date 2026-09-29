"""Report correctness with a temporary database; no live services or model calls."""
import ast
import hashlib
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from flask import Flask, jsonify, request

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "SLEECpatch/app"), str(ROOT)]
from services import sleec_patch_evaluation_store as persistence
from services.philosopher_review_store import PhilosopherReviewStore
from services.evaluation_reporting import ISSUE_TYPES, build_report_payload, recorded_diagnoses


class EvaluationReportingTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory(prefix="sleec-report-test-")
        self.addCleanup(scratch.cleanup)
        self.database = str(Path(scratch.name) / "report.sqlite")
        for name, value in [("DB_PATH", self.database), ("DATABASE_URL", ""), ("REQUIRE_DATABASE_URL", False)]:
            p = patch.object(persistence, name, value)
            p.start()
            self.addCleanup(p.stop)
        self.store = persistence.SLEECPatchEvaluationStore()
        self.reviews = PhilosopherReviewStore()

    def save_run(self, run_id, case="DAISY", count=9, duration=10, fingerprint="original-daisy", successful=True):
        structured = {kind: [] for kind in ISSUE_TYPES}
        structured["concerns"] = [f"c{i}" for i in range(count)]
        self.store.save_pipeline_run({"run_id": run_id, "use_case": case, "issue_id": "concerns_1",
            "original_structured": structured, "original_issue_count": count,
            "input_sha256": hashlib.sha256(fingerprint.encode()).hexdigest(),
            "total_time_seconds": duration, "attempts": 1, "successful": successful})

    def save_patch(self, case="DAISY", decision="", duration=10):
        return self.store.save_result({"use_case": case, "issue_id": "concerns_1", "patch_id": "p1",
            "operation": "event_specialization", "source": "llm", "verified": True,
            "philosopher_decision": decision, "total_time_seconds": duration,
            "generation_time_seconds": duration / 2, "validation_time_seconds": duration / 2,
            "patched_sleec": "private preview"})

    def report(self, case=""):
        return build_report_payload(self.store, self.reviews, case, include_patched_sleec=False)

    def test_diagnosis_count_survives_other_cases_and_repeated_repairs(self):
        self.save_run("daisy-first")
        for _ in range(3):
            self.save_patch()
        self.save_run("almi", "ALMI", count=2, fingerprint="almi")
        self.save_patch("ALMI")
        self.save_run("daisy-repeat")
        self.save_patch()
        report = self.report("DAISY")
        self.assertEqual(report["report_metrics"]["total_patch_rows"], 4)
        self.assertEqual(report["report_metrics"]["repair_run_count"], 2)
        self.assertEqual([r["issue_count"] for r in report["recorded_diagnoses"]], [9, 9])
        self.assertEqual(len({r["input_sha256"] for r in report["recorded_diagnoses"]}), 1)
        self.assertEqual(len(self.report()["evaluation_details"]), 5)

    def test_use_case_filter_applies_to_reviews_logs_and_summaries(self):
        for case, decision in [("DAISY", ""), ("ALMI", "Accepted")]:
            self.save_run(case, case)
            self.save_patch(case, decision)
            self.reviews.save_review({"use_case": case, "decision": "Accepted"})
            candidate = {"patch_id": "p1", "source": "llm"}
            self.store.save_patch_candidate({"run_id": case, "use_case": case, "patch": candidate})
            self.store.save_patch_verification({"run_id": case, "use_case": case, "patch": candidate})
        report = self.report("DAISY")
        self.assertEqual(report["philosopher_review_metrics"]["overall"]["accepted"], 0)
        self.assertEqual(report["philosopher_review_metrics"]["overall"]["pending"], 1)
        self.assertEqual(report["philosopher_review_summary"]["total_reviews"], 1)
        for key in ("evaluation_details", "evaluation_summary", "recorded_diagnoses", "experiment_runs",
                    "experiment_candidates", "experiment_verifications", "philosopher_reviews"):
            self.assertTrue(report[key], key)
            self.assertTrue(all(row["use_case"] == "DAISY" for row in report[key]), key)
        self.assertEqual(report["persistence"]["scope"], "all_use_cases")
        self.assertNotIn("patched_sleec", report["evaluation_details"][0])

    def test_average_time_counts_each_run_once_including_no_patch_run(self):
        self.save_run("fast", duration=10)
        for _ in range(3):
            self.save_patch(duration=10)
        self.save_run("slow", duration=90, successful=False)
        report = self.report()
        self.assertEqual(report["report_metrics"]["avg_run_time_seconds"], 50)
        self.assertEqual(report["evaluation_summary"][0]["avg_run_time"], 50)
        self.assertEqual(report["evaluation_summary"][0]["avg_generation_time"], 5)
        self.assertEqual(report["report_metrics"]["total_patch_rows"], 3)

    def test_unsuccessful_case_remains_visible_without_saved_patches(self):
        self.save_run("failed", successful=False)
        report = self.report()
        self.assertEqual(report["evaluation_summary"][0]["total_records"], 0)
        self.assertEqual(report["recorded_diagnoses"][0]["issue_count"], 9)

    def test_older_or_inconsistent_diagnoses_are_not_reported_as_zero(self):
        self.store.save_pipeline_run({"run_id": "legacy", "use_case": "DAISY", "original_issue_count": 9})
        self.save_patch()
        row = self.report()["recorded_diagnoses"][0]
        self.assertIsNone(row["issue_count"])
        self.assertEqual(row["status"], "unavailable")
        self.assertFalse(row["input_sha256"])
        structured = {kind: [] for kind in ISSUE_TYPES}
        inconsistent = recorded_diagnoses([{"original_issue_count": 9, "original_structured_json": json.dumps(structured)}])[0]
        self.assertEqual(inconsistent["status"], "inconsistent_record")
        self.assertIsNone(inconsistent["issue_count"])
        self.save_run("zero", count=0, fingerprint="other-input")
        self.assertEqual(self.report()["recorded_diagnoses"][0]["issue_count"], 0)

    def test_legacy_database_migration_preserves_records_and_unknown_fingerprint(self):
        self.save_run("old")
        conn = sqlite3.connect(self.database)
        conn.execute("ALTER TABLE sleec_patch_pipeline_runs DROP COLUMN input_sha256")
        conn.commit()
        conn.close()
        store = persistence.SLEECPatchEvaluationStore()
        rows = store.pipeline_runs()
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["input_sha256"])
        self.assertEqual(recorded_diagnoses(rows)[0]["issue_count"], 9)

    def test_report_route_filters_response_and_disables_http_caching(self):
        # Execute the actual route and its request helpers without booting the
        # application's production database, dotenv configuration or ML stack.
        names = {"request_payload", "truthy", "api_sleec_patch_report_data"}
        parsed = ast.parse((ROOT / "SLEECpatch/app/app.py").read_text())
        code = ast.Module(body=[n for n in parsed.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
        app = Flask("report-test")
        scope = {"app": app, "request": request, "jsonify": jsonify, "build_report_payload": build_report_payload,
                 "sleec_patch_engine": SimpleNamespace(store=self.store), "philosopher_review_store": self.reviews}
        exec(compile(code, "app-report-route", "exec"), scope)
        self.save_run("DAISY")
        self.save_patch()
        self.save_patch("ALMI")
        response = app.test_client().get("/api/sleec-patch/report-data?use_case=DAISY&include_patched_sleec=0")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(response.json["report_metrics"]["total_patch_rows"], 1)
        self.assertNotIn("patched_sleec", response.json["evaluation_details"][0])


if __name__ == "__main__":
    unittest.main()
