#!/usr/bin/env python3
import argparse
import json
import re
from collections import Counter
from pathlib import Path

import pandas as pd


DEFAULT_INPUT = Path("postgres_latest_review_report.json")
DEFAULT_OUTPUT_DIR = Path.cwd().parent / "sleec_patch_paper_clean_data"
DEFAULT_EXCLUDED_USE_CASES = {"dpa", "dressassist", "dress assist"}


def truthy(value):
    if isinstance(value, bool):
        return value

    if pd.isna(value):
        return False

    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def normalize_decision(value):
    if pd.isna(value):
        return "pending"

    value = str(value or "").strip().lower()
    return value or "pending"


def safe_filename(value):
    value = str(value or "blank").strip()
    value = re.sub(r"[^A-Za-z0-9._-]+", "_", value)
    return value.strip("._") or "blank"


def read_input(path):
    path = Path(path).expanduser().resolve()

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        rows = data.get("evaluation_details", [])
        if not rows:
            raise ValueError("JSON does not contain evaluation_details rows.")
        return pd.DataFrame(rows), data

    return pd.read_csv(path), {}


def write_count_table(counter, columns, path):
    rows = []

    for key, count in sorted(counter.items()):
        if not isinstance(key, tuple):
            key = (key,)
        rows.append({**dict(zip(columns, key)), "count": count})

    pd.DataFrame(rows, columns=[*columns, "count"]).to_csv(path, index=False)


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Create a paper-ready SLEEC-PATCH subset while preserving all "
            "original evaluation-detail columns."
        )
    )
    parser.add_argument(
        "input",
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Input report JSON or evaluation-details CSV. Default: {DEFAULT_INPUT}"
    )
    parser.add_argument(
        "-o",
        "--output-dir",
        default=DEFAULT_OUTPUT_DIR,
        help=f"Output folder. Default: {DEFAULT_OUTPUT_DIR}"
    )
    parser.add_argument(
        "--keep-review-pending",
        action="store_true",
        help="Keep rows whose philosopher/social-scientist decision is blank or pending."
    )
    parser.add_argument(
        "--keep-unverified",
        action="store_true",
        help="Keep rows whose verified column is false/blank."
    )
    args = parser.parse_args()

    df, raw_data = read_input(args.input)
    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    required = {"use_case", "verified"}
    missing = sorted(required - set(df.columns))
    if missing:
        raise ValueError(f"Missing required columns: {', '.join(missing)}")

    original_columns = list(df.columns)
    working = df.copy()
    working["_use_case_norm"] = (
        working["use_case"].fillna("").astype(str).str.strip().str.lower()
    )
    working["_verified_bool"] = working["verified"].map(truthy)

    if "philosopher_decision" in working.columns:
        working["_review_decision_norm"] = working["philosopher_decision"].map(
            normalize_decision
        )
    else:
        working["_review_decision_norm"] = "pending"

    filtered = working[
        ~working["_use_case_norm"].isin(DEFAULT_EXCLUDED_USE_CASES)
    ].copy()

    if not args.keep_unverified:
        filtered = filtered[filtered["_verified_bool"]].copy()

    if not args.keep_review_pending:
        filtered = filtered[
            ~filtered["_review_decision_norm"].isin({"", "pending"})
        ].copy()

    clean_details = filtered[original_columns].copy()
    clean_details_path = output_dir / "paper_clean_evaluation_details.csv"
    clean_details.to_csv(clean_details_path, index=False)

    for use_case, group in clean_details.groupby("use_case", dropna=False):
        path = output_dir / f"{safe_filename(use_case)}_paper_clean_details.csv"
        group.to_csv(path, index=False)

    summary_rows = [
        {"metric": "source_rows", "value": len(df)},
        {"metric": "clean_rows", "value": len(clean_details)},
        {
            "metric": "removed_rows",
            "value": len(df) - len(clean_details)
        },
        {
            "metric": "excluded_use_cases",
            "value": "DPA, DressAssist"
        },
        {
            "metric": "kept_unverified",
            "value": bool(args.keep_unverified)
        },
        {
            "metric": "kept_review_pending",
            "value": bool(args.keep_review_pending)
        },
    ]
    pd.DataFrame(summary_rows).to_csv(
        output_dir / "paper_clean_summary.csv",
        index=False
    )

    write_count_table(
        Counter(clean_details["use_case"]),
        ["use_case"],
        output_dir / "paper_clean_counts_by_use_case.csv"
    )
    write_count_table(
        Counter(clean_details["issue_type"]),
        ["issue_type"],
        output_dir / "paper_clean_counts_by_issue_type.csv"
    )
    write_count_table(
        Counter(clean_details["operation"]),
        ["operation"],
        output_dir / "paper_clean_counts_by_operation.csv"
    )
    write_count_table(
        Counter(clean_details["source"]),
        ["source"],
        output_dir / "paper_clean_counts_by_source.csv"
    )

    with pd.ExcelWriter(output_dir / "paper_clean_analysis.xlsx", engine="openpyxl") as writer:
        clean_details.to_excel(writer, sheet_name="clean_details", index=False)
        pd.read_csv(output_dir / "paper_clean_summary.csv").to_excel(
            writer,
            sheet_name="summary",
            index=False
        )
        pd.read_csv(output_dir / "paper_clean_counts_by_use_case.csv").to_excel(
            writer,
            sheet_name="by_use_case",
            index=False
        )
        pd.read_csv(output_dir / "paper_clean_counts_by_issue_type.csv").to_excel(
            writer,
            sheet_name="by_issue_type",
            index=False
        )
        pd.read_csv(output_dir / "paper_clean_counts_by_operation.csv").to_excel(
            writer,
            sheet_name="by_operation",
            index=False
        )
        pd.read_csv(output_dir / "paper_clean_counts_by_source.csv").to_excel(
            writer,
            sheet_name="by_source",
            index=False
        )

    print(f"Input rows: {len(df)}")
    print(f"Clean rows: {len(clean_details)}")
    print(f"Output folder: {output_dir}")
    print("Use-case counts:")
    for use_case, count in sorted(Counter(clean_details["use_case"]).items()):
        print(f"{use_case}: {count}")


if __name__ == "__main__":
    main()
