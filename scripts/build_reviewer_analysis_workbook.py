#!/usr/bin/env python3
from pathlib import Path

import pandas as pd


ANALYSIS_DIR = Path("reviewer_completed_analysis")
OUTPUT_PATH = ANALYSIS_DIR / "reviewer_completed_analysis_clean_workbook.xlsx"


SHEETS = [
    ("summary", "Summary"),
    ("decision_counts", "Decision Counts"),
    ("acceptance_by_use_case", "Use Case Acceptance"),
    ("use_case_decisions", "Use Case Decisions"),
    ("issue_type_decisions", "Issue Type Decisions"),
    ("operation_decisions", "Operation Decisions"),
    ("source_decisions", "Source Decisions"),
    ("use_case_source_decisions", "Use Case Source Decisions"),
    ("reviewed_patches", "Reviewed Patch Details"),
    ("pending_patches", "Pending Patch Details"),
]


def csv_path(name):
    return ANALYSIS_DIR / f"reviewer_completed_analysis_{name}.csv"


def read_csv(name):
    path = csv_path(name)

    if not path.exists():
        return pd.DataFrame()

    return pd.read_csv(path)


def autosize_columns(writer, sheet_name, frame):
    worksheet = writer.sheets[sheet_name]
    worksheet.freeze_panes = "A2"
    worksheet.auto_filter.ref = worksheet.dimensions

    for index, column in enumerate(frame.columns, start=1):
        values = [str(value) for value in frame[column].head(200).tolist()]
        max_len = max([len(str(column)), *(len(value) for value in values)])
        worksheet.column_dimensions[
            worksheet.cell(row=1, column=index).column_letter
        ].width = min(max(max_len + 2, 12), 55)


def build_index(summary, decision_counts, acceptance):
    rows = []

    if not summary.empty:
        for _, row in summary.iterrows():
            rows.append({
                "section": "Overall",
                "metric": row.get("metric", ""),
                "value": row.get("value", "")
            })

    if not decision_counts.empty:
        for _, row in decision_counts.iterrows():
            rows.append({
                "section": "Decisions",
                "metric": row.get("decision", ""),
                "value": row.get("count", 0)
            })

    if not acceptance.empty:
        for _, row in acceptance.iterrows():
            rows.append({
                "section": "Acceptance by use case",
                "metric": row.get("use_case", ""),
                "value": (
                    f"{row.get('accepted', 0)}/{row.get('reviewed', 0)} "
                    f"({row.get('acceptance_rate', 0)})"
                )
            })

    rows.append({
        "section": "Where to look",
        "metric": "Reviewed Patch Details",
        "value": "All reviewed rows with patch id, issue type, operation, source, rules, and decision."
    })
    rows.append({
        "section": "Where to look",
        "metric": "Use Case Acceptance",
        "value": "Compact acceptance/rejection rates by use case."
    })
    rows.append({
        "section": "Where to look",
        "metric": "Issue Type Decisions",
        "value": "Decision counts grouped by issue type."
    })

    return pd.DataFrame(rows)


def main():
    ANALYSIS_DIR.mkdir(parents=True, exist_ok=True)

    frames = {name: read_csv(name) for name, _ in SHEETS}
    index = build_index(
        frames["summary"],
        frames["decision_counts"],
        frames["acceptance_by_use_case"]
    )

    with pd.ExcelWriter(OUTPUT_PATH, engine="openpyxl") as writer:
        index.to_excel(writer, sheet_name="Index", index=False)
        autosize_columns(writer, "Index", index)

        for name, sheet_name in SHEETS:
            frame = frames[name]
            frame.to_excel(writer, sheet_name=sheet_name[:31], index=False)
            autosize_columns(writer, sheet_name[:31], frame)

    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
