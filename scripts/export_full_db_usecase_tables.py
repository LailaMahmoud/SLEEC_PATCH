#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

import pandas as pd


DEFAULT_INPUT = Path("postgres_full_database_log.json")
DEFAULT_OUTPUT_DIR = Path("full_db_usecase_tables")

OUTPUT_COLUMNS = [
    "case study",
    "issue_id",
    "issue_type",
    "verified_patch_count",
    "generation_time_seconds",
    "validation_time_seconds",
    "patch_id",
    "operation",
    "rules_modified",
    "rules_added",
    "rules_deleted",
    "defeaters_added",
    "conditions_refined",
    "capabilities_refined",
    "rank",
    "source",
    "expert_similarity",
    "requires_social_scientist_review",
]


def safe_filename(value):
    value = str(value or "blank").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value.strip("._") or "blank"


def read_export(path):
    path = Path(path).expanduser().resolve()

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        return {
            "evaluation_details": pd.DataFrame(data.get("evaluation_details", [])),
            "experiment_runs": pd.DataFrame(data.get("experiment_runs", [])),
            "experiment_verifications": pd.DataFrame(
                data.get("experiment_verifications", [])
            ),
        }

    return {
        "evaluation_details": pd.read_csv(path),
        "experiment_runs": pd.DataFrame(),
        "experiment_verifications": pd.DataFrame(),
    }


def prepare_run_fields(details, runs):
    if runs.empty:
        for column in [
            "verified_patch_count",
            "generation_time_seconds",
            "validation_time_seconds",
        ]:
            details[column] = ""
        return details

    run_columns = [
        "use_case",
        "issue_id",
        "verified_patch_count",
        "generation_time_seconds",
        "validation_time_seconds",
    ]
    available = [column for column in run_columns if column in runs.columns]
    run_fields = runs[available].drop_duplicates(
        subset=["use_case", "issue_id"],
        keep="last"
    )

    return details.merge(
        run_fields,
        on=["use_case", "issue_id"],
        how="left"
    )


def prepare_rank_fields(details, verifications):
    if verifications.empty:
        details["rank"] = ""
        return details

    rank_columns = [
        "use_case",
        "issue_id",
        "patch_id",
        "operation",
        "source",
        "ranking_score",
        "verified",
    ]
    available = [column for column in rank_columns if column in verifications.columns]
    ranks = verifications[available].copy()

    if "ranking_score" not in ranks.columns:
        details["rank"] = ""
        return details

    ranks["ranking_score"] = pd.to_numeric(
        ranks["ranking_score"],
        errors="coerce"
    ).fillna(0)
    ranks = ranks.sort_values(
        ["use_case", "issue_id", "ranking_score", "patch_id"],
        ascending=[True, True, False, True]
    )
    ranks["rank"] = ranks.groupby(["use_case", "issue_id"]).cumcount() + 1

    join_columns = [
        column
        for column in ["use_case", "issue_id", "patch_id", "operation", "source"]
        if column in ranks.columns and column in details.columns
    ]
    ranks = ranks[[*join_columns, "rank"]].drop_duplicates(
        subset=join_columns,
        keep="first"
    )

    return details.merge(ranks, on=join_columns, how="left")


def build_output_table(details, runs, verifications):
    if details.empty:
        raise ValueError("No evaluation_details rows found.")

    required = {"use_case", "issue_id", "issue_type", "patch_id", "operation"}
    missing = sorted(required - set(details.columns))
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    merged = prepare_run_fields(details.copy(), runs)
    merged = prepare_rank_fields(merged, verifications)
    merged["case study"] = merged["use_case"]

    for column in OUTPUT_COLUMNS:
        if column not in merged.columns:
            merged[column] = ""

    output = merged[OUTPUT_COLUMNS].sort_values(
        ["case study", "issue_id", "rank", "patch_id"],
        na_position="last"
    )
    return output.fillna("")


def autosize_columns(writer, sheet_name, frame):
    worksheet = writer.sheets[sheet_name]
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    for index, column in enumerate(frame.columns, start=1):
        values = [str(value) for value in frame[column].head(200).tolist()]
        max_len = max([len(str(column)), *(len(value) for value in values)])
        worksheet.column_dimensions[
            worksheet.cell(row=1, column=index).column_letter
        ].width = min(max(max_len + 2, 12), 42)


def write_outputs(table, output_dir):
    output_dir = Path(output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    combined_path = output_dir / "full_db_usecase_patch_table.csv"
    table.to_csv(combined_path, index=False)

    summary = (
        table.groupby("case study", dropna=False)
        .size()
        .reset_index(name="rows")
        .sort_values("case study")
    )
    summary.to_csv(output_dir / "full_db_usecase_patch_table_summary.csv", index=False)

    with pd.ExcelWriter(
        output_dir / "full_db_usecase_patch_tables.xlsx",
        engine="openpyxl"
    ) as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        autosize_columns(writer, "Summary", summary)

        table.to_excel(writer, sheet_name="All Use Cases", index=False)
        autosize_columns(writer, "All Use Cases", table)

        for use_case, group in table.groupby("case study", dropna=False):
            sheet_name = safe_filename(use_case)[:31]
            group.to_excel(writer, sheet_name=sheet_name, index=False)
            autosize_columns(writer, sheet_name, group)

    for use_case, group in table.groupby("case study", dropna=False):
        path = output_dir / f"{safe_filename(use_case)}_patch_table.csv"
        group.to_csv(path, index=False)

    return output_dir, summary


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Extract full database patch tables by use case with a fixed "
            "paper/report column order."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Input full report JSON or evaluation_details CSV. Default: {DEFAULT_INPUT}"
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output folder. Default: {DEFAULT_OUTPUT_DIR}"
    )
    args = parser.parse_args()

    frames = read_export(args.input)
    table = build_output_table(
        frames["evaluation_details"],
        frames["experiment_runs"],
        frames["experiment_verifications"]
    )
    output_dir, summary = write_outputs(table, args.output_dir)

    print(f"Rows: {len(table)}")
    print(f"Output folder: {output_dir}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
