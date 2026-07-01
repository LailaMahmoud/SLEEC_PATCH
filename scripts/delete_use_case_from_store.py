#!/usr/bin/env python3
import argparse
import os
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


def count_rows(store, use_case):
    conn = store.connect()
    cur = conn.cursor()
    counts = {}

    for table in TABLES:
        row = store.execute(
            cur,
            f"SELECT COUNT(*) AS count FROM {table} WHERE use_case = ?",
            (use_case,),
        ).fetchone()
        counts[table] = row["count"]

    conn.close()
    return counts


def delete_rows(store, use_case):
    conn = store.connect()
    cur = conn.cursor()

    for table in TABLES:
        store.execute(
            cur,
            f"DELETE FROM {table} WHERE use_case = ?",
            (use_case,),
        )

    conn.commit()
    conn.close()


def main():
    parser = argparse.ArgumentParser(
        description="Delete a use case from all SLEEC-PATCH persistence tables."
    )
    parser.add_argument("use_case")
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Actually delete rows. Without this flag the script only prints counts.",
    )
    args = parser.parse_args()

    store = SLEECPatchEvaluationStore()
    PhilosopherReviewStore().connect().close()

    before = count_rows(store, args.use_case)
    print(f"Backend: {'postgres' if store.using_postgres() else 'sqlite'}")
    print(f"Use case: {args.use_case}")
    print("Before:")
    for table, count in before.items():
        print(f"  {table}: {count}")

    if not args.yes:
        print("Dry run only. Re-run with --yes to delete.")
        return

    delete_rows(store, args.use_case)
    after = count_rows(store, args.use_case)

    print("After:")
    for table, count in after.items():
        print(f"  {table}: {count}")


if __name__ == "__main__":
    main()
