"""Overleaf exports use saved results without model calls or live databases."""
import io
import contextlib
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "SLEECpatch/app"), str(ROOT)]
from scripts import export_overleaf_tables as exporter
from services import sleec_patch_evaluation_store as persistence


ORIGINAL = """def_start
event Start
event Act
def_end
rule_start
R1 when Start then Act within 5 minutes
rule_end
"""
CORRECTED = ORIGINAL.replace("5 minutes", "2 minutes")


class OverleafExportTests(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        self.scratch = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.database = self.scratch / "results.sqlite"
        for name, value in [("DB_PATH", str(self.database)), ("DATABASE_URL", ""),
                            ("REQUIRE_DATABASE_URL", False)]:
            self.stack.enter_context(patch.object(persistence, name, value))
        self.stack.enter_context(patch.object(exporter, "SLEEC_DIR", self.scratch))
        self.stack.enter_context(patch.object(exporter, "RESULTS_DIR", self.scratch / "results"))
        self.stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
        (self.scratch / "Sample.sleec").write_text(ORIGINAL)
        (self.scratch / "Sample-corrected.sleec").write_text(CORRECTED)
        self.store = persistence.SLEECPatchEvaluationStore()

    def save_patch(self, **changes):
        row = {"use_case": "Sample", "issue_id": "c1", "issue_type": "concerns",
               "patch_id": "p1", "run_id": "first", "operation": "response_refinement",
               "source": "deterministic", "target_rule_id": "R1", "verified": True,
               "proposed_rule": "R1 when Start then Act within 2 minutes",
               "patched_sleec": CORRECTED, "expert_similarity": 0.123}
        row.update(changes)
        self.store.save_result(row)
        return row

    def test_one_file_contains_filtered_results_and_computed_similarity(self):
        self.save_patch()
        self.save_patch(use_case="Other", patch_id="other-patch")
        self.save_patch(patch_id="rejected-patch", verified=False)
        before = self.store.all_results()
        with patch.object(exporter, "load_verified_patch_rows", side_effect=AssertionError("No separate SQLite file")):
            files = exporter.build_overleaf_exports(store=self.store, use_case="Sample")
        combined = files["sleec_patch_report_sample.tex"]
        for label in ("patch-results", "manual-similarity-details", "spec-comparison"):
            self.assertIn(r"\label{tab:" + label + "}", combined)
        self.assertEqual(combined.count(r"\begin{table*}"), 3)
        self.assertNotIn("other-patch", combined)
        self.assertNotIn("rejected-patch", combined)
        self.assertIn("1.00", files["table_manual_similarity_details_sample.tex"])
        self.assertEqual(self.store.all_results(), before)

    def test_local_sqlite_cli_source_remains_supported(self):
        self.save_patch()
        local = exporter.build_overleaf_exports(self.database, "Sample")
        live = exporter.build_overleaf_exports(store=self.store, use_case="Sample")
        self.assertEqual(local, live)

    def test_rank_is_matched_to_saved_run_not_reused_patch_id(self):
        self.save_patch(run_id="selected-run")
        for run, rank in [("selected-run", 2), ("other-run", 9)]:
            self.store.save_patch_verification({"run_id": run, "use_case": "Sample", "issue_id": "c1",
                "patch": {"patch_id": "p1", "rank": rank, "ranking_score": 0.8}})
        rows = exporter.load_store_verified_patch_rows(self.store, "Sample")
        self.assertEqual(rows[0]["rank"], 2)
        self.assertEqual(exporter.load_verified_patch_rows(self.database)[0]["rank"], 2)

    def test_missing_expert_spec_does_not_crash_or_report_false_zero(self):
        (self.scratch / "Sample-corrected.sleec").unlink()
        self.save_patch()
        rows = exporter.compute_manual_similarity(self.store.all_results())
        self.assertIsNone(rows[0]["expert_similarity"])
        files = exporter.build_overleaf_exports(store=self.store, use_case="Sample")
        detail = files["table_manual_similarity_details_sample.tex"]
        self.assertIn(" & -- & -- & -- & -- & -- & --", detail)

    def test_missing_final_spec_is_not_replaced_with_an_individual_candidate(self):
        self.save_patch()
        files = exporter.build_overleaf_exports(store=self.store, use_case="Sample")
        comparison = files["table_spec_comparison_sample.tex"]
        self.assertIn(" & -- & -- & -- & -- ", comparison)
        folder = self.scratch / "results" / "Sample"
        folder.mkdir(parents=True)
        (folder / "Sample_SLEECPATCH.sleec").write_text(CORRECTED)
        comparison = exporter.build_overleaf_exports(store=self.store, use_case="Sample")["table_spec_comparison_sample.tex"]
        self.assertIn(" & 1 (2, 0, 1) & R1 & -- & --", comparison)

    def test_postgres_configuration_uses_store_connection_and_bound_filter(self):
        row = self.save_patch()
        cursor = Mock()
        cursor.execute.return_value = cursor
        cursor.fetchall.side_effect = [[{**row, "timestamp": "2026-10-03"}], []]
        connection = Mock()
        connection.cursor.return_value = cursor
        # Exercise the PostgreSQL branch through a fake driver, never a server.
        with patch.object(persistence, "DATABASE_URL", "postgresql://unused/export-test"), \
             patch("psycopg.connect", return_value=connection) as connect, \
             patch.object(exporter, "load_verified_patch_rows", side_effect=AssertionError("SQLite fallback")):
            files = exporter.build_overleaf_exports(store=self.store, use_case="Sample")
        self.assertIn("sleec_patch_report_sample.tex", files)
        self.assertEqual(connect.call_count, 2)
        query, params = cursor.execute.call_args_list[0].args
        self.assertIn("verified = 1 AND use_case = %s", query)
        self.assertEqual(params, ("Sample",))


if __name__ == "__main__":
    unittest.main()
