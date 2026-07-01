#!/usr/bin/env python3
import os
import sqlite3
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "SLEECpatch" / "app"
sys.path.insert(0, str(APP_DIR))

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
    pk = PRIMARY_KEYS[table]

    return f"""
    INSERT INTO {table} ({column_sql})
    VALUES ({placeholders})
    ON CONFLICT ({pk}) DO NOTHING
    """


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


def migrate_table(source_conn, target_store, table, preserve_ids=True):
    if not sqlite_table_exists(source_conn, table):
        print(f"SKIP {table}: table not present in SQLite")
        return 0

    source_columns = sqlite_columns(source_conn, table)
    target_columns = target_store.table_columns(table)
    columns = [col for col in target_columns if col in source_columns]

    if not preserve_ids and PRIMARY_KEYS[table] == "id":
        columns = [col for col in columns if col != "id"]

    if not columns:
        print(f"SKIP {table}: no shared columns")
        return 0

    source_sql = f"SELECT {', '.join(columns)} FROM {table}"
    insert_sql = postgres_insert_sql(table, columns)

    rows = source_conn.execute(source_sql).fetchall()

    target_conn = target_store.connect()
    target_cur = target_conn.cursor()

    for row in rows:
        values = tuple(row[col] for col in columns)
        target_store.execute(target_cur, insert_sql, values)

    target_conn.commit()
    target_conn.close()

    reset_postgres_sequence(target_store, table)

    print(f"COPIED {table}: {len(rows)} row(s)")
    return len(rows)


def migrate_sqlite_file(sqlite_path, target_store, preserve_ids=True):
    source_conn = sqlite3.connect(sqlite_path)
    source_conn.row_factory = sqlite3.Row

    print(f"MIGRATING {sqlite_path} (preserve_ids={preserve_ids})")

    total = 0

    try:
        for table in TABLES:
            total += migrate_table(
                source_conn,
                target_store,
                table,
                preserve_ids=preserve_ids
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
    PhilosopherReviewStore()

    total = 0

    for index, sqlite_path in enumerate(sqlite_paths):
        total += migrate_sqlite_file(
            sqlite_path,
            target_store,
            preserve_ids=index == 0
        )

    print(f"DONE: copied {total} total row(s) into Postgres.")
    print("SQLite source database(s) were not modified.")


if __name__ == "__main__":
    main()
