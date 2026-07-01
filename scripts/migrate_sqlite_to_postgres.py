#!/usr/bin/env python3
import os
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "SLEECpatch" / "app"
sys.path.insert(0, str(APP_DIR))

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv(APP_DIR / ".env")

from services.philosopher_review_store import PhilosopherReviewStore
from services.sleec_patch_evaluation_store import SLEECPatchEvaluationStore


TABLES = [
    "sleec_patch_results",
    "sleec_patch_pipeline_runs",
    "sleec_patch_candidates",
    "sleec_patch_verifications",
    "philosopher_patch_reviews",
]


PRIMARY_KEYS = {
    "sleec_patch_results": "id",
    "sleec_patch_pipeline_runs": "run_id",
    "sleec_patch_candidates": "id",
    "sleec_patch_verifications": "id",
    "philosopher_patch_reviews": "id",
}


IDENTITY_COLUMNS = {
    "sleec_patch_results": [
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
    "sleec_patch_pipeline_runs": ["run_id"],
    "sleec_patch_candidates": [
        "run_id",
        "patch_id",
        "source",
        "operation",
        "candidate_signature",
        "timestamp",
    ],
    "sleec_patch_verifications": [
        "run_id",
        "patch_id",
        "source",
        "operation",
        "timestamp",
    ],
    "philosopher_patch_reviews": [
        "patch_id",
        "operation",
        "reviewer",
        "decision",
        "timestamp",
    ],
}


def sqlite_columns(conn, table):
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return [row["name"] for row in rows]


def sqlite_table_exists(conn, table):
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,)
    ).fetchone()
    return row is not None


def postgres_insert_sql(table, columns):
    column_sql = ", ".join(columns)
    placeholders = ", ".join(["?"] * len(columns))

    return f"""
    INSERT INTO {table} ({column_sql})
    VALUES ({placeholders})
    """


def postgres_exists_sql(table, columns):
    where = " AND ".join(
        f"COALESCE(CAST({col} AS TEXT), '') = COALESCE(CAST(? AS TEXT), '')"
        for col in columns
    )
    return f"SELECT 1 FROM {table} WHERE {where} LIMIT 1"


def reset_postgres_sequence(store, table):
    if table == "sleec_patch_pipeline_runs":
        return

    conn = store.connect()
    cur = conn.cursor()
    cur.execute(
        f"""
        SELECT setval(
            pg_get_serial_sequence('{table}', 'id'),
            COALESCE((SELECT MAX(id) FROM {table}), 1),
            true
        )
        """
    )
    conn.commit()
    conn.close()


def migrate_table(source_conn, target_store, table):
    if not sqlite_table_exists(source_conn, table):
        print(f"SKIP {table}: table not present in SQLite")
        return 0

    source_columns = sqlite_columns(source_conn, table)
    target_columns = target_store.table_columns(table)
    columns = [col for col in target_columns if col in source_columns]

    if PRIMARY_KEYS[table] == "id":
        columns = [col for col in columns if col != "id"]

    if not columns:
        print(f"SKIP {table}: no shared columns")
        return 0

    source_sql = f"SELECT {', '.join(columns)} FROM {table}"
    insert_sql = postgres_insert_sql(table, columns)
    identity_columns = [
        col for col in IDENTITY_COLUMNS[table]
        if col in columns
    ]
    exists_sql = postgres_exists_sql(table, identity_columns)

    rows = source_conn.execute(source_sql).fetchall()

    target_conn = target_store.connect()
    target_cur = target_conn.cursor()

    copied = 0

    for row in rows:
        identity_values = tuple(row[col] for col in identity_columns)
        exists = target_store.execute(
            target_cur,
            exists_sql,
            identity_values
        ).fetchone()

        if exists:
            continue

        values = tuple(row[col] if col in source_columns else None for col in columns)
        target_store.execute(target_cur, insert_sql, values)
        copied += 1

    target_conn.commit()
    target_conn.close()

    reset_postgres_sequence(target_store, table)

    print(f"COPIED {table}: {copied} new row(s), {len(rows) - copied} skipped")
    return copied


def migrate_sqlite_file(sqlite_path, target_store):
    source_conn = sqlite3.connect(sqlite_path)
    source_conn.row_factory = sqlite3.Row

    print(f"MIGRATING {sqlite_path} (preserve_ids={preserve_ids})")

    total = 0

    try:
        for table in TABLES:
            total += migrate_table(
                source_conn,
                target_store,
                table
            )
    finally:
        source_conn.close()

    return total


def main():
    if not os.environ.get("DATABASE_URL", "").startswith(("postgres://", "postgresql://")):
        raise SystemExit(
            "Set DATABASE_URL to your Postgres connection string before running."
        )

    sqlite_paths = [
        Path(path)
        for path in (
            sys.argv[1:] or [
                os.environ.get(
                    "SLEEC_SQLITE_PATH",
                    REPO_ROOT / "instance" / "sleec_patch_results.db"
                )
            ]
        )
    ]

    missing = [path for path in sqlite_paths if not path.exists()]

    if missing:
        raise SystemExit(
            "SQLite database not found: "
            + ", ".join(str(path) for path in missing)
        )

    target_store = SLEECPatchEvaluationStore()
    philosopher_store = PhilosopherReviewStore()
    philosopher_store.connect().close()

    total = 0

    for sqlite_path in sqlite_paths:
        total += migrate_sqlite_file(sqlite_path, target_store)

    print(f"DONE: copied {total} total row(s) into Postgres.")
    print("SQLite source database(s) were not modified.")


if __name__ == "__main__":
    main()
