#!/usr/bin/env python3
import argparse
import json
import re
from pathlib import Path

import pandas as pd


DEFAULT_DETAILS = Path("postgres_latest_review_report.json")
DEFAULT_FULL = Path("postgres_full_database_log.json")
DEFAULT_OUTPUT_DIR = Path("paper_tables")

CASE_ORDER = [
    "ALMI",
    "ASPEN",
    "AutoCAR",
    "BSN",
    "CSICobot",
    "DAISY",
    "SafeSCAD",
]
EXCLUDED_CASES = {"DPA", "DressAssist", "DRESSASSIST"}

OPERATION_LABELS = {
    "capability_refinement": "cap. ref.",
    "defeater_introduction": "def. intro.",
    "defeater_propagation": "def. prop.",
    "event_specialization": "event spec.",
    "measure_specialization": "measure spec.",
    "new_rule_generation": "new rule",
    "rule_decomposition": "decompose",
    "rule_merging": "merge",
    "rule_removal": "remove",
    "trigger_refinement": "trig. ref.",
    "trigger_strengthening": "trig. str.",
}


def latex_escape(value):
    value = "" if pd.isna(value) else str(value)
    replacements = {
        "\\": r"\textbackslash{}",
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "{": r"\{",
        "}": r"\}",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(char, char) for char in value)


def read_report_details(path):
    path = Path(path).expanduser().resolve()

    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text())
        return pd.DataFrame(data.get("evaluation_details", []))

    return pd.read_csv(path)


def read_full_export(path):
    data = json.loads(Path(path).expanduser().resolve().read_text())
    return {
        "runs": pd.DataFrame(data.get("experiment_runs", [])),
        "verifications": pd.DataFrame(data.get("experiment_verifications", [])),
    }


def truthy(value):
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() in {"1", "true", "yes", "y"}


def issue_sort_key(issue_id):
    parts = re.findall(r"\d+", str(issue_id or ""))
    return tuple(int(part) for part in parts) if parts else (9999,)


def operation_label(value):
    value = str(value or "")
    return OPERATION_LABELS.get(value, value.replace("_", " "))


def join_metadata(details, runs, verifications):
    merged = details.copy()

    if not runs.empty:
        run_fields = runs[
            [
                "use_case",
                "issue_id",
                "verified_patch_count",
                "generation_time_seconds",
                "validation_time_seconds",
            ]
        ].drop_duplicates(["use_case", "issue_id"], keep="last")
        merged = merged.merge(run_fields, on=["use_case", "issue_id"], how="left")

    if not verifications.empty:
        ranks = verifications.copy()
        ranks["ranking_score"] = pd.to_numeric(
            ranks.get("ranking_score", 0),
            errors="coerce"
        ).fillna(0)
        ranks = ranks.sort_values(
            ["use_case", "issue_id", "ranking_score", "patch_id"],
            ascending=[True, True, False, True]
        )
        ranks["rank"] = ranks.groupby(["use_case", "issue_id"]).cumcount() + 1
        rank_fields = ranks[
            ["use_case", "issue_id", "patch_id", "operation", "source", "rank"]
        ].drop_duplicates(
            ["use_case", "issue_id", "patch_id", "operation", "source"],
            keep="first"
        )
        merged = merged.merge(
            rank_fields,
            on=["use_case", "issue_id", "patch_id", "operation", "source"],
            how="left"
        )

    for column in [
        "verified_patch_count",
        "generation_time_seconds",
        "validation_time_seconds",
        "rank",
        "actions_refined",
        "capabilities_refined",
    ]:
        if column not in merged.columns:
            merged[column] = ""

    return merged


def build_table(details, full):
    details = join_metadata(details, full["runs"], full["verifications"])
    details = details[
        details["use_case"].isin(CASE_ORDER)
        & ~details["use_case"].isin(EXCLUDED_CASES)
        & details["verified"].map(truthy)
    ].copy()
    dedupe_columns = [
        column
        for column in [
            "use_case",
            "issue_id",
            "issue_type",
            "patch_id",
            "operation",
            "source",
            "target_rule_id",
            "proposed_rule",
        ]
        if column in details.columns
    ]
    details = details.drop_duplicates(dedupe_columns, keep="last")

    details["_case_order"] = details["use_case"].map(
        {case: index for index, case in enumerate(CASE_ORDER)}
    )
    details["_issue_sort"] = details["issue_id"].map(issue_sort_key)
    details["rank"] = pd.to_numeric(details["rank"], errors="coerce")
    details = details.sort_values(
        ["_case_order", "_issue_sort", "rank", "patch_id"],
        na_position="last"
    )
    return details


def format_number(value, digits=3):
    if pd.isna(value) or value == "":
        return "--"
    try:
        return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
    except (TypeError, ValueError):
        return str(value)


def format_int(value):
    if pd.isna(value) or value == "":
        return "--"
    try:
        return str(int(float(value)))
    except (TypeError, ValueError):
        return str(value)


def source_label(value):
    value = str(value or "").lower()
    if value == "deterministic":
        return "det."
    return value


def review_label(value):
    return "yes" if truthy(value) else "no"


def write_latex(table, output_path):
    lines = [
        r"% Auto-generated from SLEEC-PATCH PostgreSQL export.",
        r"% Requires \usepackage{booktabs,longtable,array}.",
        r"\begin{small}",
        r"\begin{longtable}{p{1.45cm} p{2.35cm} r r r r r r r r p{1.15cm} r p{1.2cm}}",
        r"\caption{Patch generation results across the evaluated case studies.}",
        r"\label{tab:results}\\",
        r"\toprule",
        r"PID & Op & \#RM & \#RA & \#RD & \#DA & \#TR & \#RR & \#CR & rank & source & m-sim. & e-review\\",
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        r"PID & Op & \#RM & \#RA & \#RD & \#DA & \#TR & \#RR & \#CR & rank & source & m-sim. & e-review\\",
        r"\midrule",
        r"\endhead",
    ]

    for case in CASE_ORDER:
        case_rows = table[table["use_case"] == case]
        if case_rows.empty:
            continue

        for issue_id, issue_rows in case_rows.groupby("issue_id", sort=False):
            first = issue_rows.iloc[0]
            patch_count = len(issue_rows)
            gen_time = format_number(first.get("generation_time_seconds"))
            val_time = format_number(first.get("validation_time_seconds"))
            issue_type = latex_escape(first.get("issue_type", ""))
            issue_id_tex = latex_escape(issue_id)
            case_tex = latex_escape(case if case != "CSICobot" else "CSI-Cobot")

            lines.append(r"\midrule")
            lines.append(
                rf"\multicolumn{{13}}{{l}}{{\textbf{{{case_tex}}} "
                rf"\quad IID: {issue_id_tex} "
                rf"\quad WFI: {issue_type} "
                rf"\quad \#Patch: {patch_count} "
                rf"\quad time (gen,val): ({gen_time}, {val_time})}}\\"
            )
            lines.append(r"\midrule")

            for _, row in issue_rows.iterrows():
                values = [
                    latex_escape(row.get("patch_id", "")),
                    latex_escape(operation_label(row.get("operation", ""))),
                    format_int(row.get("rules_modified", 0)),
                    format_int(row.get("rules_added", 0)),
                    format_int(row.get("rules_deleted", 0)),
                    format_int(row.get("defeaters_added", 0)),
                    format_int(row.get("conditions_refined", 0)),
                    format_int(row.get("actions_refined", 0)),
                    format_int(row.get("capabilities_refined", 0)),
                    format_int(row.get("rank", "")),
                    latex_escape(source_label(row.get("source", ""))),
                    format_number(row.get("expert_similarity", 0)),
                    review_label(row.get("requires_social_scientist_review", 0)),
                ]
                lines.append(" & ".join(values) + r"\\")

    lines.extend([
        r"\bottomrule",
        r"\end{longtable}",
        r"\end{small}",
        "",
        r"% Abbreviations: RM=rules modified; RA=rules added; RD=rules deleted;",
        r"% DA=defeaters added; TR=trigger/condition refinements;",
        r"% RR=response/action refinements; CR=capability refinements.",
    ])
    Path(output_path).write_text("\n".join(lines))


def main():
    parser = argparse.ArgumentParser(
        description="Generate the paper patch-generation results LaTeX table."
    )
    parser.add_argument("--details", default=DEFAULT_DETAILS)
    parser.add_argument("--full", default=DEFAULT_FULL)
    parser.add_argument("-o", "--output-dir", default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    details = read_report_details(args.details)
    full = read_full_export(args.full)
    table = build_table(details, full)

    csv_path = output_dir / "patch_generation_results_table_data.csv"
    tex_path = output_dir / "patch_generation_results_table.tex"

    table.to_csv(csv_path, index=False)
    write_latex(table, tex_path)

    print(f"Rows: {len(table)}")
    print(f"Wrote: {csv_path}")
    print(f"Wrote: {tex_path}")
    print(table["use_case"].value_counts().reindex(CASE_ORDER).dropna().astype(int).to_string())


if __name__ == "__main__":
    main()
