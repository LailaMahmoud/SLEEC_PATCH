import os
import sqlite3
from datetime import datetime


DB_PATH = os.path.join("instance", "sleec_patch_results.db")


class SLEECPatchEvaluationStore:

    def __init__(self):
        os.makedirs("instance", exist_ok=True)
        self.create_tables()
        self.ensure_columns()

    def connect(self):
        return sqlite3.connect(DB_PATH)

    def create_tables(self):
        conn = self.connect()
        cur = conn.cursor()

        cur.execute("""
        CREATE TABLE IF NOT EXISTS sleec_patch_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,

            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            selected_issue TEXT,

            attempts INTEGER,
            failed_patch_count INTEGER,
            verified_patch_count INTEGER,

            generation_time_seconds REAL,
            validation_time_seconds REAL,
            total_time_seconds REAL,

            patch_id TEXT,
            operation TEXT,
            source TEXT,
            target_rule_id TEXT,
            original_rule TEXT,
            proposed_rule TEXT,
            natural_language_explanation TEXT,
            patched_sleec TEXT,

            rules_modified INTEGER,
            rules_added INTEGER,
            rules_deleted INTEGER,
            defeaters_added INTEGER,
            conditions_refined INTEGER,
            actions_refined INTEGER,
            capabilities_refined INTEGER,

            verified INTEGER,
            expert_similarity REAL,
            expert_match INTEGER,
            requires_social_scientist_review INTEGER,

            timestamp TEXT
        )
        """)

        conn.commit()
        conn.close()

    def ensure_columns(self):
        conn = self.connect()
        cur = conn.cursor()

        existing_columns = [
            row[1]
            for row in cur.execute("PRAGMA table_info(sleec_patch_results)").fetchall()
        ]

        required_columns = {
            "source": "TEXT",
            "target_rule_id": "TEXT",
            "original_rule": "TEXT",
            "proposed_rule": "TEXT",
            "natural_language_explanation": "TEXT",
            "patched_sleec": "TEXT"
        }

        for col, col_type in required_columns.items():
            if col not in existing_columns:
                cur.execute(
                    f"ALTER TABLE sleec_patch_results ADD COLUMN {col} {col_type}"
                )

        conn.commit()
        conn.close()

    def save_result(self, row):
        conn = self.connect()
        cur = conn.cursor()

        cur.execute("""
        INSERT INTO sleec_patch_results (
            use_case,
            issue_id,
            issue_type,
            selected_issue,

            attempts,
            failed_patch_count,
            verified_patch_count,

            generation_time_seconds,
            validation_time_seconds,
            total_time_seconds,

            patch_id,
            operation,
            source,
            target_rule_id,
            original_rule,
            proposed_rule,
            natural_language_explanation,
            patched_sleec,

            rules_modified,
            rules_added,
            rules_deleted,
            defeaters_added,
            conditions_refined,
            actions_refined,
            capabilities_refined,

            verified,
            expert_similarity,
            expert_match,
            requires_social_scientist_review,

            timestamp
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            row.get("use_case", ""),
            row.get("issue_id", ""),
            row.get("issue_type", ""),
            str(row.get("selected_issue", "")),

            row.get("attempts", 0),
            row.get("failed_patch_count", 0),
            row.get("verified_patch_count", 0),

            row.get("generation_time_seconds", 0),
            row.get("validation_time_seconds", 0),
            row.get("total_time_seconds", 0),

            row.get("patch_id", ""),
            row.get("operation", ""),
            row.get("source", ""),

            row.get("target_rule_id", ""),
            row.get("original_rule", ""),
            row.get("proposed_rule", ""),
            row.get("natural_language_explanation", ""),
            row.get("patched_sleec", ""),

            row.get("rules_modified", 0),
            row.get("rules_added", 0),
            row.get("rules_deleted", 0),
            row.get("defeaters_added", 0),
            row.get("conditions_refined", 0),
            row.get("actions_refined", 0),
            row.get("capabilities_refined", 0),

            1 if row.get("verified") else 0,
            row.get("expert_similarity", 0),
            1 if row.get("expert_match") else 0,
            1 if row.get("requires_social_scientist_review") else 0,

            datetime.now().isoformat()
        ))

        conn.commit()
        conn.close()

    def summary(self):
        conn = self.connect()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        rows = cur.execute("""
        SELECT
            use_case,
            COUNT(*) AS total_records,
            SUM(verified) AS verified_patches,
            AVG(attempts) AS avg_attempts,
            AVG(total_time_seconds) AS avg_total_time,
            AVG(generation_time_seconds) AS avg_generation_time,
            AVG(validation_time_seconds) AS avg_validation_time,
            SUM(rules_modified) AS rules_modified,
            SUM(rules_added) AS rules_added,
            SUM(rules_deleted) AS rules_deleted,
            SUM(defeaters_added) AS defeaters_added,
            SUM(conditions_refined) AS conditions_refined,
            SUM(actions_refined) AS actions_refined,
            SUM(capabilities_refined) AS capabilities_refined,
            AVG(expert_similarity) AS avg_expert_similarity,
            SUM(requires_social_scientist_review) AS social_review_needed
        FROM sleec_patch_results
        GROUP BY use_case
        """).fetchall()

        conn.close()
        return [dict(r) for r in rows]

    def result_columns(self, include_patched_sleec=True):
        columns = [
            "use_case",
            "issue_id",
            "issue_type",
            "attempts",
            "total_time_seconds",
            "patch_id",
            "operation",
            "source",
            "target_rule_id",
            "original_rule",
            "proposed_rule",
            "natural_language_explanation",
            "rules_modified",
            "rules_added",
            "rules_deleted",
            "defeaters_added",
            "conditions_refined",
            "actions_refined",
            "capabilities_refined",
            "verified",
            "expert_similarity",
            "expert_match",
            "requires_social_scientist_review",
            "timestamp"
        ]

        if include_patched_sleec:
            columns.insert(12, "patched_sleec")

        return columns

    def fetch_results(self, where_clause="", params=(), include_patched_sleec=True):
        conn = self.connect()
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        columns = ",\n            ".join(
            self.result_columns(include_patched_sleec)
        )

        query = f"""
        SELECT
            {columns}
        FROM sleec_patch_results
        """

        if where_clause:
            query += f"\n        WHERE {where_clause}"

        query += "\n        ORDER BY timestamp DESC"

        rows = cur.execute(query, params).fetchall()

        conn.close()
        return [dict(r) for r in rows]

    def all_results(self, include_patched_sleec=True):
        return self.fetch_results(
            include_patched_sleec=include_patched_sleec
        )

    def results_for_use_case(self, use_case, include_patched_sleec=True):
        return self.fetch_results(
            where_clause="use_case = ?",
            params=(use_case,),
            include_patched_sleec=include_patched_sleec
        )
