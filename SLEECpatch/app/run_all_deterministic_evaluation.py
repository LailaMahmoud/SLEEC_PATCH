import os
import json
import csv
import traceback
from datetime import datetime

from services.sleec_patch_workbench_engine import SLEECPatchWorkbenchEngine
from services.repair_operator_selector import RepairOperatorSelector
from services.deterministic_repair_engine import DeterministicRepairEngine


USE_CASES = [
    ("ALMI", "ALMI.sleec"),
    ("ASPEN", "aspen.sleec"),
    ("AutoCAR", "Autocar.sleec"),
    ("BSN", "BSN.sleec"),
    ("CSI", "CSI.sleec"),
    ("DAISY", "Daisy.sleec"),
    ("DPA", "DPA.sleec"),
    ("DressAssist", "DRESSASSIST.sleec"),
    ("SafeSCAD", "safescade.sleec"),
]


# Evaluation order requested: SC first.
WFI_ORDER = [
    "situational_conflicts",
    "conflicts",
    "concerns",
    "redundancies",
    "purpose_blocking",
]


def get_issue_values(structured, issue_key):
    """
    Convert detector output for one WFI category into individual issue values.
    Keeps each parsed finding separate.
    """
    value = structured.get(issue_key, [])

    if value is None:
        return []

    if isinstance(value, list):
        return [x for x in value if x]

    if isinstance(value, dict):
        # Some detector outputs may wrap findings.
        for key in ("findings", "issues", "results", "items"):
            if isinstance(value.get(key), list):
                return [x for x in value[key] if x]

        return [value] if value else []

    if isinstance(value, str):
        return [value] if value.strip() else []

    return [value]


def issue_text(issue):
    if isinstance(issue, str):
        return issue

    try:
        return json.dumps(issue, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(issue)


def safe_fingerprint(engine, issue_key, issue):
    try:
        return engine.issue_fingerprint(issue_key, issue)
    except Exception:
        return ""


def get_regression_fields(patch):
    report = patch.get("regression_report") or {}

    return {
        "target_fixed": bool(
            patch.get(
                "target_fixed",
                report.get("selected_issue_fixed", False)
            )
        ),
        "regression_passed": bool(
            patch.get(
                "regression_passed",
                report.get("regression_passed", False)
            )
        ),
        "new_issue_count": report.get(
            "new_issue_count",
            len(report.get("new_issues", []) or [])
        ),
        "new_issues_introduced": bool(
            report.get(
                "new_issues_introduced",
                bool(report.get("new_issues", []))
            )
        ),
    }


def result_row(
    use_case,
    filename,
    issue_key,
    issue_index,
    fingerprint,
    operator,
    status,
    patch=None,
    error="",
):
    patch = patch or {}
    regression = get_regression_fields(patch)

    semantic = patch.get("semantic_validation") or {}

    return {
        "use_case": use_case,
        "file": filename,
        "wfi_type": issue_key,
        "wfi_index": issue_index,
        "wfi_fingerprint": fingerprint,
        "operator": operator,
        "applicable": bool(patch.get("applicable", False)),
        "generated": bool(patch.get("generated", False)),

        "status": status,
        "patch_id": patch.get("patch_id", patch.get("id", "")),
        "source": patch.get("source", "deterministic"),

        "target_rule_id": patch.get("target_rule_id", ""),
        "original_rule": patch.get("original_rule", ""),
        "missing_element": patch.get("missing_element", ""),
        "proposed_rule": patch.get("proposed_rule", ""),

        "syntax_valid": bool(patch.get("syntax_valid", False)),
        "semantic_validation_passed": bool(
            patch.get(
                "semantic_validation_passed",
                semantic.get("valid", False)
            )
        ),
        "semantic_warning": bool(
            patch.get("semantic_warning", False)
        ),
        "semantic_warning_reason": patch.get(
            "semantic_warning_reason", ""
        ),
        "vocabulary_grounded": bool(
            patch.get("vocabulary_grounded", False)
        ),
        "diagnosis_aligned": bool(
            patch.get("diagnosis_aligned", False)
        ),
        "operator_valid": bool(
            patch.get("operator_valid", False)
        ),
        "temporal_alignment": bool(
            patch.get("temporal_alignment", False)
        ),

        "target_fixed": regression["target_fixed"],
        "new_issue_count": regression["new_issue_count"],
        "new_issues_introduced": regression[
            "new_issues_introduced"
        ],
        "regression_passed": regression["regression_passed"],

        "formally_verified": bool(
            patch.get("formally_verified", False)
        ),
        "verified": bool(patch.get("verified", False)),

        "failure_reason": patch.get(
            "failure_reason",
            error
        ),
        "natural_language_explanation": patch.get(
            "natural_language_explanation",
            patch.get("explanation", "")
        ),

        "error": error,
    }


def print_patch_result(row):
    print("      STATUS:", row["status"])

    if row["proposed_rule"]:
        print("      PROPOSED:", row["proposed_rule"])

    print("      SYNTAX VALID:", row["syntax_valid"])
    print(
        "      SEMANTIC VALID:",
        row["semantic_validation_passed"]
    )
    print(
        "      SEMANTIC WARNING:",
        row["semantic_warning"]
    )

    if row["semantic_warning_reason"]:
        print(
            "      SEMANTIC WARNING REASON:",
            row["semantic_warning_reason"]
        )

    print("      TARGET FIXED:", row["target_fixed"])
    print(
        "      NEW ISSUES INTRODUCED:",
        row["new_issues_introduced"]
    )
    print("      NEW ISSUE COUNT:", row["new_issue_count"])
    print(
        "      REGRESSION PASSED:",
        row["regression_passed"]
    )
    print(
        "      FORMALLY VERIFIED:",
        row["formally_verified"]
    )

    if row["failure_reason"]:
        print(
            "      FAILURE REASON:",
            row["failure_reason"]
        )


def main():
    engine = SLEECPatchWorkbenchEngine()
    selector = RepairOperatorSelector()
    deterministic_engine = DeterministicRepairEngine()

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_dir = os.path.join(
        "results",
        "DETERMINISTIC_ALL_USECASES_" + timestamp
    )
    os.makedirs(output_dir, exist_ok=True)

    rows = []

    print("=" * 80)
    print("SLEEC-PATCH — ALL DETERMINISTIC PATCH EVALUATION")
    print("=" * 80)
    print("Use cases:", len(USE_CASES))
    print("Formal verification: LEGOS target-fix + regression")
    print("Deterministic operators: diagnosis-driven applicability")
    print("=" * 80)

    for use_case, filename in USE_CASES:
        path = os.path.join("sleec_usecases", filename)

        print("\n")
        print("#" * 80)
        print("USE CASE:", use_case)
        print("FILE:", path)
        print("#" * 80)

        if not os.path.exists(path):
            print("FILE NOT FOUND:", path)
            rows.append({
                "use_case": use_case,
                "file": filename,
                "wfi_type": "",
                "wfi_index": "",
                "wfi_fingerprint": "",
                "operator": "",
                "status": "ERROR",
                "error": "File not found",
            })
            continue

        try:
            with open(path, "r", encoding="utf-8") as f:
                sleec_text = f.read()

            # ORIGINAL baseline analysis.
            original_analysis = engine.detector.run_text(sleec_text)
            original_structured = (
                original_analysis.get("structured", {})
                if isinstance(original_analysis, dict)
                else {}
            )

            rules_json = engine.sleec_text_to_rules_json(sleec_text)

            existing_events = engine.extract_defined_events(sleec_text)
            existing_measures = engine.extract_defined_measures(sleec_text)
            existing_responses = engine.extract_rule_actions(rules_json)

            print("RULES PARSED:", len(rules_json))

        except Exception as exc:
            print("BASELINE ERROR:", exc)
            traceback.print_exc()
            continue

        for issue_key in WFI_ORDER:
            issues = get_issue_values(
                original_structured,
                issue_key
            )

            if not issues:
                print(
                    f"\n[{issue_key}] "
                    "NO DETECTED WFI — SKIP"
                )
                continue


            print(
                f"\n[{issue_key}] "
                f"DETECTED FINDINGS: {len(issues)}"
            )

            for issue_index, selected_issue in enumerate(
                issues,
                start=1
            ):
                fingerprint = safe_fingerprint(
                    engine,
                    issue_key,
                    selected_issue
                )
                selection = selector.select(
                    issue_type=issue_key,
                    rules=rules_json,
                    selected_issue=selected_issue,
                    existing_events=existing_events,
                    existing_measures=existing_measures,
                    existing_responses=existing_responses,
                    system_description="",
                )
                deterministic_ops = selection.get("deterministic", [])
                applicability = selection.get("applicability", {})


                print("\n  " + "-" * 70)
                print(
                    f"  WFI {issue_index}/{len(issues)}"
                )
                print(
                    "  FINGERPRINT:",
                    fingerprint
                )
                print(
                    "  OPERATORS:",
                    deterministic_ops
                )

                for operator in deterministic_ops:
                    print(
                        f"\n    >>> DETERMINISTIC OPERATOR: {operator}"
                    )

                    try:
                        # Generate ONLY this deterministic operator so that
                        # every operator has independent evidence.
                        patches = deterministic_engine.generate(
                            issue_type=issue_key,
                            selected_issue=selected_issue,
                            rules=rules_json,
                            operators=[operator],
                            existing_events=existing_events,
                        )

                    except Exception as exc:
                        print(
                            "      DETERMINISTIC GENERATION ERROR:",
                            exc
                        )

                        rows.append(
                            result_row(
                                use_case,
                                filename,
                                issue_key,
                                issue_index,
                                fingerprint,
                                operator,
                                "ERROR",
                                {
                                    "applicable": True,
                                    "generated": False,
                                    "source": "deterministic",
                                },
                                error=str(exc),
                            )
                        )
                        continue

                    if not patches:
                        print(
                            "      NO CANDIDATE GENERATED"
                        )

                        rows.append(
                            result_row(
                                use_case,
                                filename,
                                issue_key,
                                issue_index,
                                fingerprint,
                                operator,
                                "NOT_GENERATED",
                                {
                                    "applicable": True,
                                    "generated": False,
                                    "source": "deterministic",
                                },
                            )
                        )
                        continue

                    for patch_no, patch in enumerate(
                        patches,
                        start=1
                    ):
                        patch["source"] = "deterministic"
                        patch["applicable"] = True
                        patch["generated"] = True

                        normalized = engine.normalize_patch(
                            patch,
                            sleec_text
                        )

                        if (
                            normalized.get("patch_id")
                            == "not_applicable"
                        ):
                            normalized["applicable"] = True
                            normalized["generated"] = False
                            row = result_row(
                                use_case,
                                filename,
                                issue_key,
                                issue_index,
                                fingerprint,
                                operator,
                                "NOT_APPLICABLE",
                                normalized,
                            )
                            rows.append(row)
                            print_patch_result(row)
                            continue

                        try:
                            verified = normalized
                            patched_sleec = engine.apply_patch_to_text(
                                sleec_text,
                                verified
                            )
                            verified["patched_sleec"] = patched_sleec

                            validation = engine.validate_patched_sleec(
                                patched_sleec
                            )
                            verified["syntax_valid"] = bool(
                                validation.get("syntax", {}).get("valid", False)
                            )
                            verified["syntax_validation"] = validation.get(
                                "syntax", {}
                            )

                            if not validation.get("valid", False):
                                verified["target_fixed"] = False
                                verified["regression_passed"] = False
                                verified["formally_verified"] = False
                                verified["verified"] = False
                                verified["failure_reason"] = validation.get(
                                    "failure_reason",
                                    "SLEEC validation failed"
                                )
                                status = "REJECTED"
                            else:
                                new_analysis = validation.get("analysis", {})
                                new_structured = new_analysis.get(
                                    "structured", {}
                                )

                                regression_report = engine.build_regression_report(
                                    issue_key,
                                    selected_issue,
                                    original_structured,
                                    new_structured
                                )
                                target_fixed = regression_report[
                                    "selected_issue_fixed"
                                ]

                                related_issue = engine.find_related_new_issue(
                                    patch=verified,
                                    new_structured=new_structured,
                                    original_structured=original_structured
                                )

                                formally_verified = bool(
                                    target_fixed
                                    and related_issue is None
                                    and regression_report["regression_passed"]
                                )

                                verified["target_fixed"] = target_fixed
                                verified["related_issue"] = related_issue
                                verified["validation_result"] = new_structured
                                verified["regression_report"] = regression_report
                                verified["regression_passed"] = regression_report[
                                    "regression_passed"
                                ]
                                verified["formally_verified"] = formally_verified
                                verified["verified"] = formally_verified

                                reasons = []
                                if not target_fixed:
                                    reasons.append("target issue not fixed")
                                if related_issue:
                                    reasons.append(
                                        "introduced related issue on edited rule"
                                    )
                                if regression_report.get(
                                    "new_issues_introduced", False
                                ):
                                    reasons.append(
                                        "introduced new WFI during regression"
                                    )

                                verified["failure_reason"] = (
                                    "; ".join(reasons)
                                    if reasons
                                    else ""
                                )

                                status = (
                                    "VERIFIED"
                                    if formally_verified
                                    else "REJECTED"
                                )

                            row = result_row(
                                use_case,
                                filename,
                                issue_key,
                                issue_index,
                                fingerprint,
                                operator,
                                status,
                                verified,
                            )

                            rows.append(row)
                            print_patch_result(row)

                        except Exception as exc:
                            print(
                                "      VERIFICATION ERROR:",
                                exc
                            )
                            traceback.print_exc()

                            rows.append(
                                result_row(
                                    use_case,
                                    filename,
                                    issue_key,
                                    issue_index,
                                    fingerprint,
                                    operator,
                                    "ERROR",
                                    normalized,
                                    error=str(exc),
                                )
                            )

    # ----------------------------------------------------------
    # SAVE CSV
    # ----------------------------------------------------------

    csv_path = os.path.join(
        output_dir,
        "deterministic_all_usecases_results.csv"
    )

    all_fields = []
    for row in rows:
        for key in row:
            if key not in all_fields:
                all_fields.append(key)

    with open(
        csv_path,
        "w",
        newline="",
        encoding="utf-8-sig"
    ) as f:
        writer = csv.DictWriter(
            f,
            fieldnames=all_fields
        )
        writer.writeheader()

        for row in rows:
            writer.writerow(row)

    # ----------------------------------------------------------
    # SAVE JSON
    # ----------------------------------------------------------

    json_path = os.path.join(
        output_dir,
        "deterministic_all_usecases_results.json"
    )

    with open(
        json_path,
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            rows,
            f,
            indent=2,
            ensure_ascii=False
        )

    # ----------------------------------------------------------
    # SUMMARY
    # ----------------------------------------------------------

    verified_count = sum(
        1 for r in rows
        if r.get("status") == "VERIFIED"
    )

    rejected_count = sum(
        1 for r in rows
        if r.get("status") == "REJECTED"
    )

    na_count = sum(
        1 for r in rows
        if r.get("status") == "NOT_APPLICABLE"
    )

    error_count = sum(
        1 for r in rows
        if r.get("status") == "ERROR"
    )

    print("\n")
    print("=" * 80)
    print("FINAL DETERMINISTIC EVALUATION SUMMARY")
    print("=" * 80)
    print("TOTAL RESULT RECORDS:", len(rows))
    print("VERIFIED:", verified_count)
    print("REJECTED:", rejected_count)
    print("NOT APPLICABLE:", na_count)
    print("ERRORS:", error_count)
    print("=" * 80)
    print("CSV:", csv_path)
    print("JSON:", json_path)
    print("=" * 80)


if __name__ == "__main__":
    main()
