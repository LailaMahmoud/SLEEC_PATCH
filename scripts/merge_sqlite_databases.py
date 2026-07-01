#!/usr/bin/env python3
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_DB = REPO_ROOT / "instance" / "sleec_patch_results.db"
SOURCE_DB = REPO_ROOT / "SLEECpatch" / "app" / "instance" / "sleec_patch_results.db"
BACKUP_DIR = Path("/private/tmp")


RESULT_COLUMNS = [
    "use_case",
    "issue_id",
    "issue_type",
    "selected_issue",
    "attempts",
    "failed_patch_count",
    "verified_patch_count",
    "generation_time_seconds",
    "validation_time_seconds",
    "total_time_seconds",
    "patch_id",
    "operation",
    "source",
    "target_rule_id",
    "original_rule",
    "proposed_rule",
    "natural_language_explanation",
    "patched_sleec",
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
    "philosopher_decision",
    "philosopher_comments",
    "review_timestamp",
    "timestamp",
]

REVIEW_COLUMNS = [
    "use_case",
    "issue_id",
    "issue_type",
    "patch_id",
    "operation",
    "original_rule",
    "proposed_rule",
    "explanation",
    "reviewer",
    "decision",
    "comment",
    "timestamp",
]

RUN_COLUMNS = [
    "run_id",
    "use_case",
    "issue_id",
    "issue_type",
    "selected_issue",
    "max_attempts",
    "attempts",
    "successful",
    "failed_patch_count",
    "verified_patch_count",
    "generation_time_seconds",
    "validation_time_seconds",
    "total_time_seconds",
    "repair_operators_json",
    "original_issue_count",
    "original_structured_json",
    "generated_file_path",
    "timestamp",
]

CANDIDATE_COLUMNS = [
    "run_id",
    "use_case",
    "issue_id",
    "issue_type",
    "attempt",
    "patch_id",
    "source",
    "operation",
    "target_rule_id",
    "original_rule",
    "proposed_rule",
    "natural_language_explanation",
    "candidate_signature",
    "patch_json",
    "timestamp",
]

VERIFICATION_COLUMNS = [
    "run_id",
    "use_case",
    "issue_id",
    "issue_type",
    "attempt",
    "patch_id",
    "source",
    "operation",
    "target_rule_id",
    "verified",
    "target_fixed",
    "regression_passed",
    "failure_reason",
    "verification_depth",
    "related_issue_json",
    "regression_report_json",
    "ranking_json",
    "ranking_score",
    "patched_sleec",
    "patch_json",
    "timestamp",
]


def table_exists(conn, table):
    schema = "main"
    table_name = table

    if "." in table:
        schema, table_name = table.split(".", 1)

    row = conn.execute(
        f"SELECT name FROM {schema}.sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def table_columns(conn, table):
    if not table_exists(conn, table):
        return []

    if "." in table:
        schema, table_name = table.split(".", 1)
        rows = conn.execute(f"PRAGMA {schema}.table_info({table_name})")
    else:
        rows = conn.execute(f"PRAGMA table_info({table})")

    return [row[1] for row in rows]


def ensure_column(conn, table, column, definition):
    if column not in table_columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def ensure_schema(conn):
    ensure_column(conn, "sleec_patch_results", "philosopher_decision", "TEXT")
    ensure_column(conn, "sleec_patch_results", "philosopher_comments", "TEXT")
    ensure_column(conn, "sleec_patch_results", "review_timestamp", "TEXT")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sleec_patch_pipeline_runs (
            run_id TEXT PRIMARY KEY,
            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            selected_issue TEXT,
            max_attempts INTEGER,
            attempts INTEGER,
            successful INTEGER,
            failed_patch_count INTEGER,
            verified_patch_count INTEGER,
            generation_time_seconds REAL,
            validation_time_seconds REAL,
            total_time_seconds REAL,
            repair_operators_json TEXT,
            original_issue_count INTEGER,
            original_structured_json TEXT,
            generated_file_path TEXT,
            timestamp TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sleec_patch_candidates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            attempt INTEGER,
            patch_id TEXT,
            source TEXT,
            operation TEXT,
            target_rule_id TEXT,
            original_rule TEXT,
            proposed_rule TEXT,
            natural_language_explanation TEXT,
            candidate_signature TEXT,
            patch_json TEXT,
            timestamp TEXT
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS sleec_patch_verifications (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT,
            use_case TEXT,
            issue_id TEXT,
            issue_type TEXT,
            attempt INTEGER,
            patch_id TEXT,
            source TEXT,
            operation TEXT,
            target_rule_id TEXT,
            verified INTEGER,
            target_fixed INTEGER,
            regression_passed INTEGER,
            failure_reason TEXT,
            verification_depth INTEGER,
            related_issue_json TEXT,
            regression_report_json TEXT,
            ranking_json TEXT,
            ranking_score REAL,
            patched_sleec TEXT,
            patch_json TEXT,
            timestamp TEXT
        )
    """)


def count(conn, table):
    if not table_exists(conn, table):
        return 0
    return conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def source_exprs(source_columns, columns):
    return [
        f"s.{column}" if column in source_columns else "NULL"
        for column in columns
    ]


def null_safe_match(alias_left, alias_right, columns):
    return " AND ".join(
        f"COALESCE({alias_left}.{column}, '') = COALESCE({alias_right}.{column}, '')"
        for column in columns
    )


def copy_missing_rows(conn, source_schema, table, columns, identity_columns):
    if not table_exists(conn, f"{source_schema}.{table}"):
        return 0

    before = count(conn, table)
    source_columns = table_columns(conn, f"{source_schema}.{table}")
    select_sql = ", ".join(source_exprs(source_columns, columns))
    column_sql = ", ".join(columns)
    match_sql = null_safe_match("target", "s", identity_columns)

    conn.execute(f"""
        INSERT INTO {table} ({column_sql})
        SELECT {select_sql}
        FROM {source_schema}.{table} AS s
        WHERE NOT EXISTS (
            SELECT 1
            FROM {table} AS target
            WHERE {match_sql}
        )
    """)

    return count(conn, table) - before


def print_counts(conn, label):
    print(label)
    for table in [
        "sleec_patch_results",
        "sleec_patch_pipeline_runs",
        "sleec_patch_candidates",
        "sleec_patch_verifications",
        "philosopher_patch_reviews",
    ]:
        print(f"  {table}: {count(conn, table)}")


def backup(path):
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    backup_path = BACKUP_DIR / f"{path.stem}.{timestamp}.before_merge{path.suffix}"
    shutil.copy2(path, backup_path)
    return backup_path


def main():
    if not TARGET_DB.exists():
        raise SystemExit(f"Target DB not found: {TARGET_DB}")
    if not SOURCE_DB.exists():
        raise SystemExit(f"Source DB not found: {SOURCE_DB}")

    backup_path = backup(TARGET_DB)

    conn = sqlite3.connect(TARGET_DB)
    conn.row_factory = sqlite3.Row

    try:
        ensure_schema(conn)
        conn.execute("ATTACH DATABASE ? AS source_db", (str(SOURCE_DB),))

        print_counts(conn, "Before merge")

        copied = {
            "sleec_patch_results": copy_missing_rows(
                conn,
                "source_db",
                "sleec_patch_results",
                RESULT_COLUMNS,
                [
                    "use_case",
                    "issue_id",
                    "issue_type",
                    "patch_id",
                    "operation",
                    "source",
                    "target_rule_id",
                    "proposed_rule",
                    "timestamp",
                ],
            ),
            "philosopher_patch_reviews": copy_missing_rows(
                conn,
                "source_db",
                "philosopher_patch_reviews",
                REVIEW_COLUMNS,
                ["patch_id", "operation", "reviewer", "decision", "timestamp"],
            ),
            "sleec_patch_pipeline_runs": copy_missing_rows(
                conn,
                "source_db",
                "sleec_patch_pipeline_runs",
                RUN_COLUMNS,
                ["run_id"],
            ),
            "sleec_patch_candidates": copy_missing_rows(
                conn,
                "source_db",
                "sleec_patch_candidates",
                CANDIDATE_COLUMNS,
                ["run_id", "patch_id", "source", "operation", "candidate_signature", "timestamp"],
            ),
            "sleec_patch_verifications": copy_missing_rows(
                conn,
                "source_db",
                "sleec_patch_verifications",
                VERIFICATION_COLUMNS,
                ["run_id", "patch_id", "source", "operation", "timestamp"],
            ),
        }

        conn.commit()
        print_counts(conn, "After merge")
        print("Copied")
        for table, rows in copied.items():
            print(f"  {table}: {rows}")
        print(f"Backup: {backup_path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
