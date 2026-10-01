import argparse
import sqlite3
import sys
from pathlib import Path
from statistics import mean


# ============================================================
# Paths
# ============================================================

APP_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = APP_DIR.parents[1]

if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from services.manual_similarity_evaluator import (
    ManualSimilarityEvaluator,
)


# ============================================================
# File helpers
# ============================================================

def find_database(explicit_db=None):
    candidates = []

    if explicit_db:
        candidates.append(Path(explicit_db))

    candidates.extend([
        REPO_ROOT / "instance" / "sleec_patch_results.db",
        APP_DIR / "instance" / "sleec_patch_results.db",
        APP_DIR / "sleec_patch_results.db",
    ])

    for path in candidates:
        if path.exists():
            return path.resolve()

    raise FileNotFoundError(
        "Could not find sleec_patch_results.db.\n"
        "Checked:\n"
        + "\n".join(str(p) for p in candidates)
    )


def find_sleec_file(use_case, corrected=False):
    folder = APP_DIR / "sleec_usecases"

    if not folder.exists():
        raise FileNotFoundError(
            f"SLEEC use-case directory not found: {folder}"
        )

    if corrected:
        preferred = [
            folder / f"{use_case}-corrected.sleec",
            folder / f"{use_case}_corrected.sleec",
            folder / f"{use_case}-Corrected.sleec",
            folder / f"{use_case}_Corrected.sleec",
        ]
    else:
        preferred = [
            folder / f"{use_case}.sleec",
        ]

    for path in preferred:
        if path.exists():
            return path.resolve()

    # Case-insensitive fallback.
    files = list(folder.glob("*.sleec"))

    uc = use_case.lower()

    for path in files:
        stem = path.stem.lower()

        if corrected:
            if (
                uc in stem
                and "corrected" in stem
            ):
                return path.resolve()
        else:
            if (
                stem == uc
                and "corrected" not in stem
                and "sleecpatch" not in stem
            ):
                return path.resolve()

    kind = "corrected" if corrected else "original"

    raise FileNotFoundError(
        f"Could not find {kind} SLEEC file for {use_case}"
    )


# ============================================================
# Database helpers
# ============================================================

def table_columns(con):
    rows = con.execute(
        "PRAGMA table_info(sleec_patch_results)"
    ).fetchall()

    return [row[1] for row in rows]


def validate_schema(con):
    columns = set(table_columns(con))

    required = {
        "use_case",
        "issue_id",
        "patch_id",
        "operation",
        "target_rule_id",
        "proposed_rule",
        "verified",
        "run_id",
        "timestamp",
    }

    missing = required - columns

    if missing:
        raise RuntimeError(
            "Missing required columns in sleec_patch_results: "
            + ", ".join(sorted(missing))
        )

    return columns


def latest_run_per_issue(con, use_case):
    """
    Determine the latest verified non-null run independently
    for each WFI.

    This prevents historical reruns from being mixed together.
    """

    rows = con.execute(
        """
        SELECT
            issue_id,
            run_id,
            MAX(timestamp) AS latest_timestamp
        FROM sleec_patch_results
        WHERE lower(use_case) = lower(?)
          AND verified = 1
          AND run_id IS NOT NULL
        GROUP BY issue_id, run_id
        ORDER BY issue_id, latest_timestamp DESC
        """,
        (use_case,),
    ).fetchall()

    latest = {}

    for row in rows:
        issue_id = row["issue_id"]

        if issue_id not in latest:
            latest[issue_id] = {
                "run_id": row["run_id"],
                "timestamp": row["latest_timestamp"],
            }

    return latest


def load_latest_verified_patches(con, use_case):
    """
    Load only verified patches belonging to the latest run
    of each WFI.
    """

    runs = latest_run_per_issue(
        con,
        use_case,
    )

    patches = []

    for issue_id, info in runs.items():
        run_id = info["run_id"]

        rows = con.execute(
            """
            SELECT *
            FROM sleec_patch_results
            WHERE lower(use_case) = lower(?)
              AND issue_id = ?
              AND run_id = ?
              AND verified = 1
            ORDER BY timestamp ASC
            """,
            (
                use_case,
                issue_id,
                run_id,
            ),
        ).fetchall()

        patches.extend(rows)

    patches.sort(
        key=lambda r: (
            str(r["issue_id"]),
            str(r["timestamp"]),
        )
    )

    return patches, runs


# ============================================================
# Output helpers
# ============================================================

def fmt(value):
    if value is None:
        return "N/A"

    if isinstance(value, float):
        return f"{value:.4f}"

    return str(value)


def print_components(components):
    if not components:
        return

    for key, value in components.items():

        if isinstance(value, list):
            formatted = ", ".join(
                f"{x:.4f}"
                if isinstance(x, float)
                else str(x)
                for x in value
            )

            print(
                f"    {key:<18}: [{formatted}]"
            )
        else:
            print(
                f"    {key:<18}: {fmt(value)}"
            )


# ============================================================
# Evaluation
# ============================================================

def evaluate_use_case(use_case, db_path=None):

    database = find_database(db_path)

    original_path = find_sleec_file(
        use_case,
        corrected=False,
    )

    corrected_path = find_sleec_file(
        use_case,
        corrected=True,
    )

    original_text = original_path.read_text(
        encoding="utf-8"
    )

    corrected_text = corrected_path.read_text(
        encoding="utf-8"
    )

    con = sqlite3.connect(database)
    con.row_factory = sqlite3.Row

    try:
        validate_schema(con)

        patches, runs = load_latest_verified_patches(
            con,
            use_case,
        )

        print()
        print("=" * 76)
        print(
            f"{use_case.upper()} — Manual Similarity Evaluation"
        )
        print("=" * 76)

        print(f"Original : {original_path}")
        print(f"Corrected: {corrected_path}")
        print(f"Database : {database}")

        print()
        print("Latest run selected per WFI:")

        for issue_id in sorted(runs):
            info = runs[issue_id]

            count = sum(
                1
                for p in patches
                if p["issue_id"] == issue_id
            )

            print(
                f"  {issue_id:<28} "
                f"{info['run_id']} "
                f"({count} verified)"
            )

        print()
        print(
            f"Verified patches selected: {len(patches)}"
        )

        if not patches:
            print(
                "\nNo verified patches found for the latest WFI runs."
            )
            return

        evaluator = ManualSimilarityEvaluator()

        scores = []
        current_issue = None

        for patch in patches:

            issue_id = patch["issue_id"]

            if issue_id != current_issue:
                current_issue = issue_id
                print()
                print(f"[{issue_id}]")

            patch_id = patch["patch_id"]
            operation = patch["operation"]
            target = patch["target_rule_id"]
            proposed = patch["proposed_rule"]

            source = (
                patch["source"]
                if "source" in patch.keys()
                else "--"
            )

            result = evaluator.evaluate(
                operation=operation,
                target_rule_id=target,
                proposed_rule=proposed,
                original_text=original_text,
                corrected_text=corrected_text,
            )

            score = result.get("m_sim")

            if score is not None:
                scores.append(float(score))

            print()
            print(f"  {patch_id}")
            print(f"    Operator : {operation}")
            print(f"    Operation type: {operation}")
            print(f"    Source   : {source}")
            print(f"    Target   : {target}")
            print(
                f"    M-Sim    : "
                f"{score:.4f}"
                if score is not None
                else "    M-Sim    : --"
            )

            matched = result.get(
                "matched_expert_rule"
            )

            if matched:
                print(
                    f"    Expert   : {matched}"
                )

            generated_subtype = result.get(
                "generated_temporal_subtype"
            )

            expert_subtype = result.get(
                "expert_temporal_subtype"
            )

            if generated_subtype:
                print(
                    f"    Generated temporal subtype: "
                    f"{generated_subtype}"
                )

            if expert_subtype:
                print(
                    f"    Expert temporal subtype   : "
                    f"{expert_subtype}"
                )

            warning = result.get("warning")

            if warning:
                print(
                    f"    WARNING  : {warning}"
                )

            components = result.get(
                "components",
                {},
            )

            if components:
                print("    Components:")
                print_components(components)

                applicable = components.get("applicable_count")
                if applicable is not None:
                    print(f"    Applicable components: {applicable}")

        print()
        print("-" * 76)
        print(
            f"Verified patches evaluated : {len(patches)}"
        )

        if scores:
            print(
                f"Mean M-Sim                : "
                f"{mean(scores):.4f}"
            )
            print(
                f"Min M-Sim                 : "
                f"{min(scores):.4f}"
            )
            print(
                f"Max M-Sim                 : "
                f"{max(scores):.4f}"
            )
        else:
            print(
                "Mean M-Sim                : --"
            )
            print(
                "Min M-Sim                 : --"
            )
            print(
                "Max M-Sim                 : --"
            )

        print("-" * 76)

        print(
            "READ-ONLY MODE: database was not modified."
        )

        print(
            "Expert-match threshold is intentionally "
            "not applied yet."
        )

    finally:
        con.close()


# ============================================================
# CLI
# ============================================================

def main():

    parser = argparse.ArgumentParser(
        description=(
            "Compute read-only Manual Similarity (M-Sim) "
            "for the latest verified SLEEC-PATCH run of "
            "each diagnosed WFI."
        )
    )

    parser.add_argument(
        "--use-case",
        required=True,
        help="Use case name, e.g. ALMI",
    )

    parser.add_argument(
        "--db",
        default=None,
        help=(
            "Optional explicit path to "
            "sleec_patch_results.db"
        ),
    )

    args = parser.parse_args()

    evaluate_use_case(
        use_case=args.use_case,
        db_path=args.db,
    )


if __name__ == "__main__":
    main()
