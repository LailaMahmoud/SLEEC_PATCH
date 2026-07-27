#!/usr/bin/env python3
import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd


DEFAULT_INPUT = Path("postgres_latest_review_report.json")
DEFAULT_PREFIX = "review_analysis"


def normalize_decision(value):
    if pd.isna(value):
        return "pending"

    value = str(value or "").strip().lower()
    return value or "pending"


def count_frame(counter, columns):
    rows = []
    for key, count in sorted(counter.items()):
        if not isinstance(key, tuple):
            key = (key,)
        rows.append({**dict(zip(columns, key)), "count": count})
    return pd.DataFrame(rows, columns=[*columns, "count"])


def main():
    parser = argparse.ArgumentParser(
        description="Create analysis-friendly tables from SLEEC-PATCH review export JSON."
    )
    parser.add_argument(
        "input_json",
        nargs="?",
        default=DEFAULT_INPUT,
        help=f"Report JSON from /api/sleec-patch/report-data. Default: {DEFAULT_INPUT}"
    )
    parser.add_argument(
        "-p",
        "--prefix",
        default=DEFAULT_PREFIX,
        help="Output file prefix."
    )
    args = parser.parse_args()

    input_path = Path(args.input_json).expanduser().resolve()
    data = json.loads(input_path.read_text())
    rows = data.get("evaluation_details", [])

    df = pd.DataFrame(rows)
    if df.empty:
        raise SystemExit("No evaluation_details rows found.")

    df["review_decision"] = df.get("philosopher_decision", "").map(normalize_decision)
    df["reviewed"] = df["review_decision"] != "pending"
    df["verified_bool"] = df.get("verified", False).astype(bool)
    df["source_norm"] = df.get("source", "").fillna("").astype(str).str.lower()

    reviewed_df = df[df["reviewed"]].copy()
    pending_df = df[~df["reviewed"]].copy()

    summary_rows = [
        {"metric": "total_patch_rows", "value": len(df)},
        {"metric": "reviewed_rows", "value": len(reviewed_df)},
        {"metric": "pending_rows", "value": len(pending_df)},
        {"metric": "verified_rows", "value": int(df["verified_bool"].sum())},
        {"metric": "llm_rows", "value": int((df["source_norm"] == "llm").sum())},
        {
            "metric": "deterministic_rows",
            "value": int((df["source_norm"] == "deterministic").sum())
        },
    ]
    summary_df = pd.DataFrame(summary_rows)

    decision_counts = Counter(df["review_decision"])
    use_case_decisions = Counter(
        zip(df["use_case"], df["review_decision"])
    )
    issue_decisions = Counter(
        zip(df["issue_type"], df["review_decision"])
    )
    operation_decisions = Counter(
        zip(df["operation"], df["review_decision"])
    )
    source_decisions = Counter(
        zip(df["source"], df["review_decision"])
    )
    use_case_source_decisions = Counter(
        zip(df["use_case"], df["source"], df["review_decision"])
    )

    acceptance_rows = []
    for use_case, group in reviewed_df.groupby("use_case", dropna=False):
        decisions = group["review_decision"]
        accepted = decisions.isin(["accept", "accepted", "approve", "approved"]).sum()
        rejected = decisions.isin(["reject", "rejected"]).sum()
        acceptance_rows.append({
            "use_case": use_case,
            "reviewed": len(group),
            "accepted": int(accepted),
            "rejected": int(rejected),
            "acceptance_rate": round(accepted / len(group), 4) if len(group) else 0
        })
    acceptance_df = pd.DataFrame(acceptance_rows).sort_values("use_case")

    outputs = {
        "summary": summary_df,
        "reviewed_patches": reviewed_df,
        "pending_patches": pending_df,
        "decision_counts": count_frame(decision_counts, ["decision"]),
        "use_case_decisions": count_frame(
            use_case_decisions,
            ["use_case", "decision"]
        ),
        "issue_type_decisions": count_frame(
            issue_decisions,
            ["issue_type", "decision"]
        ),
        "operation_decisions": count_frame(
            operation_decisions,
            ["operation", "decision"]
        ),
        "source_decisions": count_frame(
            source_decisions,
            ["source", "decision"]
        ),
        "use_case_source_decisions": count_frame(
            use_case_source_decisions,
            ["use_case", "source", "decision"]
        ),
        "acceptance_by_use_case": acceptance_df,
    }

    prefix = Path(args.prefix)
    output_dir = prefix.parent if str(prefix.parent) != "." else Path(".")
    output_dir.mkdir(parents=True, exist_ok=True)

    for name, frame in outputs.items():
        frame.to_csv(f"{prefix}_{name}.csv", index=False)

    with pd.ExcelWriter(f"{prefix}.xlsx", engine="openpyxl") as writer:
        for name, frame in outputs.items():
            frame.to_excel(writer, sheet_name=name[:31], index=False)

    print(f"Input: {input_path}")
    print(f"Rows: {len(df)}")
    print(f"Reviewed: {len(reviewed_df)}")
    print(f"Pending: {len(pending_df)}")
    print(f"Wrote: {prefix}.xlsx")
    for name in outputs:
        print(f"Wrote: {prefix}_{name}.csv")


if __name__ == "__main__":
    main()
