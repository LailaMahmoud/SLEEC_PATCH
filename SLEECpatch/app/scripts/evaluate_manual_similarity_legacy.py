import argparse
import sqlite3
import sys

from pathlib import Path
from statistics import mean


APP_DIR = (
    Path(__file__)
    .resolve()
    .parents[1]
)

REPO_ROOT = (
    APP_DIR.parents[1]
)


if str(APP_DIR) not in sys.path:
    sys.path.insert(
        0,
        str(APP_DIR),
    )


from services.manual_similarity_evaluator import (
    ManualSimilarityEvaluator,
)


# ================================================================
# Database
# ================================================================

def find_db(explicit=None):

    candidates = []

    if explicit:

        candidates.append(
            Path(explicit)
        )

    candidates += [

        REPO_ROOT
        / "instance"
        / "sleec_patch_results.db",

        APP_DIR
        / "instance"
        / "sleec_patch_results.db",

        APP_DIR
        / "sleec_patch_results.db",
    ]

    for path in candidates:

        if path.exists():
            return path

    raise FileNotFoundError(
        "Could not find sleec_patch_results.db. "
        "Use --db with the full database path."
    )


# ================================================================
# SLEEC files
# ================================================================

def find_sleec(
    use_case,
    corrected=False,
):

    root = (
        APP_DIR
        / "sleec_usecases"
    )

    if corrected:

        candidates = [

            root
            / f"{use_case}-corrected.sleec",

            root
            / f"{use_case}-Corrected.sleec",

            root
            / f"{use_case}_corrected.sleec",

            root
            / f"{use_case}_Corrected.sleec",
        ]

    else:

        candidates = [
            root
            / f"{use_case}.sleec"
        ]

    for path in candidates:

        if path.exists():
            return path

    # fallback search

        # Map evaluation use-case names to their actual SLEEC filenames.
    sleec_aliases = {
        "csicobot": "csi",
        "safescad": "safescade",
    }

    uc = sleec_aliases.get(
        use_case.lower(),
        use_case.lower()
    )

    for path in root.glob(
        "*.sleec"
    ):

        stem = path.stem.lower()

        if (
            corrected
            and
            uc in stem
            and
            "corrected" in stem
        ):

            return path

        if (
            not corrected
            and
            stem == uc
        ):

            return path

    kind = (
        "corrected"
        if corrected
        else "original"
    )

    raise FileNotFoundError(
        f"Could not find {kind} "
        f"SLEEC file for {use_case}"
    )


# ================================================================
# Database columns
# ================================================================

def get_columns(con):

    return {
        row[1]
        for row
        in con.execute(
            """
            PRAGMA table_info(
                sleec_patch_results
            )
            """
        )
    }


# ================================================================
# Latest verified run PER WFI
# ================================================================

def load_latest_verified_per_issue(
    con,
    use_case,
):

    cols = get_columns(con)

    required = {

        "use_case",
        "issue_id",
        "patch_id",
        "operation",
        "target_rule_id",
        "proposed_rule",
        "verified",
    }

    missing = (
        required - cols
    )

    if missing:

        raise RuntimeError(
            "Missing required database "
            "columns: "
            +
            ", ".join(
                sorted(missing)
            )
        )

    optional = [

        name
        for name in [

            "source",
            "run_id",
            "timestamp",
            "ranking_score",
            "rank",

        ]

        if name in cols
    ]

    select_columns = [

        "use_case",
        "issue_id",
        "patch_id",
        "operation",
        "target_rule_id",
        "proposed_rule",
        "verified",

    ] + optional

    sql = f"""
        SELECT
            {", ".join(select_columns)}

        FROM sleec_patch_results

        WHERE
            lower(use_case)
            =
            lower(?)

            AND verified = 1

        ORDER BY
            issue_id,
            timestamp DESC
    """

    rows = [

        dict(row)

        for row
        in con.execute(
            sql,
            (use_case,),
        ).fetchall()

    ]

    if not rows:
        return []

        # ------------------------------------------------------------
    # Keep the latest verified record for each unique patch.
    #
    # This mirrors export_overleaf_tables.py so the similarity
    # evaluation uses the same verified-patch dataset as Table 1.
    #
    # Identity:
    #   (use_case, issue_id, patch_id)
    # ------------------------------------------------------------

    latest = {}

    for row in rows:

        key = (
            str(row.get("use_case") or ""),
            str(row.get("issue_id") or ""),
            str(row.get("patch_id") or ""),
        )

        previous = latest.get(key)

        if previous is None:
            latest[key] = row
            continue

        current_timestamp = str(
            row.get("timestamp") or ""
        )

        previous_timestamp = str(
            previous.get("timestamp") or ""
        )

        if current_timestamp >= previous_timestamp:
            latest[key] = row

    selected = list(latest.values())

    selected.sort(
        key=lambda row: (
            str(row.get("issue_id") or ""),
            str(row.get("patch_id") or ""),
        )
    )

    return selected

   


# ================================================================
# Printing
# ================================================================

def print_components(
    components,
):

    order = [

        "target",
        "trigger",
        "response",
        "polarity",
        "defeater",
        "temporal",
    ]

    for name in order:

        if name in components:

            value = components[name]

            if value is None:
                display_value = "N/A"
            else:
                display_value = f"{value:.4f}"

            print(
                f"    "
                f"{name.capitalize():9}: "
                f"{display_value}"
            )


# ================================================================
# Main
# ================================================================

def main():

    parser = argparse.ArgumentParser(

        description=(
            "Read-only Manual Similarity "
            "(M-Sim) evaluation."
        )
    )

    parser.add_argument(
        "--use-case",
        required=True,
    )

    parser.add_argument(
        "--db",
        default=None,
    )

    args = parser.parse_args()

    use_case = args.use_case

    db = find_db(
        args.db
    )

    original_path = find_sleec(
        use_case,
        corrected=False,
    )

    corrected_path = find_sleec(
        use_case,
        corrected=True,
    )

    original_text = (
        original_path
        .read_text(
            encoding="utf-8"
        )
    )

    corrected_text = (
        corrected_path
        .read_text(
            encoding="utf-8"
        )
    )

    # ------------------------------------------------------------
    # Load DB
    # ------------------------------------------------------------

    con = sqlite3.connect(
        str(db)
    )

    con.row_factory = (
        sqlite3.Row
    )

    rows = (
        load_latest_verified_per_issue(
            con,
            use_case,
        )
    )

    con.close()

    # ------------------------------------------------------------
    # Header
    # ------------------------------------------------------------

    print(
        "\n"
        + "=" * 76
    )

    print(
        f"{use_case.upper()} "
        f"— Manual Similarity Evaluation"
    )

    print(
        "=" * 76
    )

    print(
        f"Original : "
        f"{original_path}"
    )

    print(
        f"Corrected: "
        f"{corrected_path}"
    )

    print(
        f"Database : "
        f"{db}"
    )

    print(
        "Latest verified patches "
        f"loaded: {len(rows)}"
    )

    if not rows:

        print(
            "\nNo verified patches found."
        )

        return

    evaluator = (
        ManualSimilarityEvaluator()
    )

    scores = []

    current_issue = None

    # ------------------------------------------------------------
    # Evaluate
    # ------------------------------------------------------------

    for row in rows:

        issue = row[
            "issue_id"
        ]

        if (
            issue
            !=
            current_issue
        ):

            print(
                f"\n[{issue}]"
            )

            if row.get(
                "run_id"
            ):

                print(
                    "  Run: "
                    f"{row['run_id']}"
                )

            current_issue = issue

        result = (
            evaluator.evaluate(

                operation=
                    row["operation"],

                target_rule_id=
                    row["target_rule_id"],

                proposed_rule=
                    row["proposed_rule"],

                original_text=
                    original_text,

                corrected_text=
                    corrected_text,
            )
        )

        score = float(
            result.get(
                "m_sim",
                0.0,
            )
        )

        scores.append(
            score
        )

        print(
            f"\n  "
            f"{row['patch_id']}"
        )

        print(
            "    Operator : "
            f"{row['operation']}"
        )

        print(
            "    Source   : "
            f"{row.get('source', '--')}"
        )

        print(
            "    Target   : "
            f"{row['target_rule_id']}"
        )

        print(
            "    M-Sim    : "
            f"{score:.4f}"
        )

        warning = (
            result.get(
                "warning"
            )
        )

        if warning:

            print(
                "    WARNING  : "
                f"{warning}"
            )

        components = (
            result.get(
                "components"
            )
            or {}
        )

        print_components(
            components
        )

        # --------------------------------------------------------
        # Matched expert rule
        # --------------------------------------------------------

        expert = (
            result.get(
                "matched_expert_rule"
            )
        )

        if expert is not None:

            expert_text = (
                expert.raw
                if hasattr(expert, "raw")
                else str(expert)
            )

            print(
                "    Expert   : "
                f"{expert_text}"
            )
        # --------------------------------------------------------
        # Decomposition
        # --------------------------------------------------------

        set_matches = (
            result.get(
                "set_matches"
            )
        )

        if set_matches:

            print(
                "    Decomposition matches:"
            )

            for (
                generated,
                matched,
                subscore,
            ) in set_matches:

                expert_text = (

                    matched.raw

                    if matched

                    else "<none>"
                )

                print(
                    "      Generated: "
                    f"{generated.raw}"
                )

                print(
                    "      Expert   : "
                    f"{expert_text}"
                )

                print(
                    "      M-Sim    : "
                    f"{subscore.get('m_sim', 0.0):.4f}"
                )

    # ------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------

    print(
        "\n"
        + "-" * 76
    )

    print(
        "Verified patches evaluated : "
        f"{len(scores)}"
    )

    print(
        "Mean M-Sim                : "
        f"{mean(scores):.4f}"
    )

    print(
        "Min M-Sim                 : "
        f"{min(scores):.4f}"
    )

    print(
        "Max M-Sim                 : "
        f"{max(scores):.4f}"
    )

    print(
        "-" * 76
    )

    print(
        "READ-ONLY MODE: "
        "database was not modified."
    )

    print(
        "Expert-match threshold is "
        "intentionally not applied yet."
    )


if __name__ == "__main__":
    main()
